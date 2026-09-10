# SPDX-License-Identifier: Apache-2.0
import copy
import sys
import unittest
from test_contracts import ROOT, load_module
sys.path.insert(0, str(ROOT / 'scripts'))
a = load_module('audit_ihp_io_suite_digital_sta', ROOT / 'scripts/audit_ihp_io_suite_digital_sta.py')


class OfficialIOSuiteTests(unittest.TestCase):
    def sdc(self):
        text = 'create_clock -name clk_sys -period 10.0000 [get_ports {clk_pad}]\nset_max_transition 1.2000 [current_design]\n'
        for p in ('out_pad','bi_tx_pad','bi_rx_pad','bi_z_pad'):
            text += 'set_load -pin_load 15.0000 [get_ports {' + p + '}]\n'
        for p in ('in_core','clk_core','bi_tx_rx','bi_rx_rx','bi_z_rx'):
            text += 'set_load -pin_load 0.0500 [get_ports {' + p + '}]\n'
        for p, v in [('bi_tx_en',1),('bi_rx_en',0),('bi_z_en',0)]:
            text += 'set_case_analysis ' + str(v) + ' [get_ports {' + p + '}]\n'
        return text

    def test_original_contract(self):
        self.assertEqual(a.validate_sdc(self.sdc())['load_pf'], 15)

    def test_slew_relaxation_rejected(self):
        with self.assertRaisesRegex(ValueError, '1.2 ns'):
            a.validate_sdc(self.sdc().replace('1.2000', '3.5000'))

    def test_load_relaxation_rejected(self):
        with self.assertRaisesRegex(ValueError, 'external load'):
            a.validate_sdc(self.sdc().replace('15.0000', '5.0000'))

    def test_enable_change_rejected(self):
        with self.assertRaisesRegex(ValueError, 'mode/enable'):
            a.validate_sdc(self.sdc().replace('set_case_analysis 1', 'set_case_analysis 0'))

    def test_lost_corner_path_rejected(self):
        with self.assertRaisesRegex(ValueError, 'min/max'):
            a.path_slacks('Path Type: max\n1.0 slack (MET)\n')

    def test_negative_slack_cannot_be_called_met(self):
        with self.assertRaisesRegex(ValueError, 'conflict'):
            a.path_slacks('Path Type: min\n-1.0 slack (MET)\n')

    def test_highz_no_path_is_distinct(self):
        self.assertEqual(a.path_slacks('No paths found.\n'), {'path_found': False})

    def test_electrical_row_keeps_real_limit(self):
        row = a.violations('max slew\npad 1.20000005 3.56007743 -2.36007762 (VIOLATED)')[0]
        self.assertAlmostEqual(row['limit'], 1.2, places=6)

    def test_fake_violation_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Inconsistent'):
            a.violations('max slew\npad 1.2 0.3 0.9 (VIOLATED)')

    def execution(self):
        state = {'Status':'exited','Running':False,'OOMKilled':False,'ExitCode':0}
        return {'terminal_container_state':state,'returncode':0,'outer_timeout':False,'cleanup_returncode':0,'execution_complete':True}, state

    def test_oom_rejected(self):
        record, state = self.execution();state['OOMKilled'] = True
        with self.assertRaisesRegex(ValueError, 'healthy'):
            a.terminal(record, state)

    def test_boolean_exit_rejected(self):
        record, state = self.execution();record['returncode'] = False
        with self.assertRaisesRegex(ValueError, 'Integer'):
            a.terminal(record, state)

    def test_failed_execution_must_remain_failed(self):
        record, state = self.execution();record['returncode']=1;state['ExitCode']=1;record['execution_complete']=False
        a.terminal(record,state,False)
        with self.assertRaisesRegex(ValueError, 'status inconsistent'):
            a.terminal(record,state,True)

    def test_continuation_omits_missing_api(self):
        tcl = a.continuation.tcl()
        self.assertFalse(any(line.startswith('report_case_analysis') for line in tcl.splitlines()))
        for corner in ('tt','ff','ss'):
            self.assertIn('report_check_types -corner ' + corner, tcl)
