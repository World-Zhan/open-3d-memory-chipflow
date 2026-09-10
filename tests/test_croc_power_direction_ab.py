# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
import sys
from test_contracts import ROOT, load_module
sys.path.insert(0, str(ROOT / 'scripts'))
a = load_module('audit_croc_power_direction_ab', ROOT / 'scripts/audit_croc_power_direction_ab.py')


class PowerDirectionAuditTests(unittest.TestCase):
    def state(self):
        state = {'Status': 'exited', 'Running': False, 'OOMKilled': False, 'ExitCode': 0}
        arm = {'returncode': 0, 'status': 'completed', 'execution_complete': True, 'outer_timeout_expired': False,
               'cleanup_returncode': 0, 'terminal_container_state': state}
        return arm, state, 'OpenROAD v2.0-27244-gfecb04286 POWER_DIRECTION_AB_COMPLETE'

    def test_terminal_healthy(self):
        a.complete_state(*self.state())

    def test_oom_rejected_even_with_sentinel(self):
        arm, state, log = self.state()
        state['OOMKilled'] = True
        with self.assertRaisesRegex(ValueError, 'healthy'):
            a.complete_state(arm, state, log)

    def test_missing_exit_rejected(self):
        arm, state, log = self.state()
        arm.pop('returncode')
        with self.assertRaisesRegex(ValueError, 'exit zero'):
            a.complete_state(arm, state, log)

    def test_boolean_exit_rejected(self):
        arm, state, log = self.state()
        arm['returncode'] = False
        with self.assertRaisesRegex(ValueError, 'exit zero'):
            a.complete_state(arm, state, log)

    def test_terminal_observation_mismatch_rejected(self):
        arm, state, log = self.state()
        observed = dict(state, Running=True)
        with self.assertRaisesRegex(ValueError, 'observation differs'):
            a.complete_state(arm, observed, log)

    def test_wrong_tool_rejected(self):
        arm, state, log = self.state()
        with self.assertRaisesRegex(ValueError, 'Tool version'):
            a.complete_state(arm, state, log.replace('27244', '0'))

    def test_direction_only_replacement(self):
        source = 'DIRECTION INOUT ;\nRECT 0 0 70 70 ;'
        self.assertEqual(a.direction_lef(source, 'INPUT'), 'DIRECTION INPUT ;\nRECT 0 0 70 70 ;')
        with self.assertRaisesRegex(ValueError, 'precisely one'):
            a.direction_lef(source + source, 'INPUT')

    def tsv(self, direction, net='clk'):
        return 'instance\tmaster\tpin\tdirection\tnet\nbond\tbondpad70_m2_ring\tpad\t' + direction + '\t' + net + '\n'

    def test_direction_pairs_preserve_endpoint(self):
        self.assertEqual(a.compare_directions(self.tsv('INOUT'), self.tsv('INPUT'), 1), 1)

    def test_changed_endpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, 'endpoints changed'):
            a.compare_directions(self.tsv('INOUT'), self.tsv('INPUT', 'data'), 1)

    def test_missing_pad_rejected(self):
        with self.assertRaisesRegex(ValueError, 'count changed'):
            a.compare_directions(self.tsv('INOUT'), self.tsv('INPUT'), 64)

    def test_invalid_power_rejected(self):
        groups = {g: {'internal_w': 1., 'switching_w': 1., 'leakage_w': 1., 'total_w': 3.}
                  for g in ('Sequential', 'Combinational', 'Clock', 'Macro', 'Pad', 'Total')}
        a.check_power(groups)
        for value in (float('nan'), float('inf'), -1.):
            bad = copy.deepcopy(groups)
            bad['Macro']['internal_w'] = value
            with self.assertRaisesRegex(ValueError, 'finite'):
                a.check_power(bad)

    def test_missing_power_group_rejected(self):
        with self.assertRaisesRegex(ValueError, 'group missing'):
            a.check_power({'Total': {}})

    def test_sdc_only_removes_comments(self):
        self.assertNotEqual(a.normalized_sdc('# comment\nset_load 15 [all_outputs]\n'),
                            a.normalized_sdc('# comment\nset_load 5 [all_outputs]\n'))

    def test_electrical_endpoint_and_value_parsed(self):
        report = 'max slew\npad_gpio0_io/pad 1.20 2.72 -1.52 (VIOLATED)\n'
        self.assertEqual(a.electrical_rows(report)[('max slew', 'pad_gpio0_io/pad')]['actual'], 2.72)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            a.electrical_rows(report + report)
