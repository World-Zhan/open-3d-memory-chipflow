# SPDX-License-Identifier: Apache-2.0
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from test_contracts import ROOT, load_module

sys.path.insert(0, str(ROOT / 'scripts'))
audit = load_module('audit_croc_full_cts_fanout', ROOT / 'scripts/audit_croc_full_cts_fanout.py')


SDC = '# Thu Sep 10 13:59:44 2026\ncreate_clock -period 10.0000 [get_ports {clk_i}]\nset_load -pin_load 15.0000 [get_ports {gpio0_io}]\n'
CHECKS = [{'check': name, 'tcl_catch_code': '0', 'message': message}
          for name, message in [('check_placement', ''), ('check_power_grid_VDD', '1'), ('check_power_grid_VSS', '1')]]
LOG = 'PLACEMENT_LEGALITY_END catch=0 result=\n' + '\n'.join(
    f'[INFO PSM-0040] All shapes on net {net} are connected.' for net in ('VDD', 'VSS'))


class FullCtsFanoutTests(unittest.TestCase):
    def test_saved_timestamp_can_change_without_relaxing_sdc(self):
        self.assertEqual(audit.check_constraints(SDC, SDC.replace('13:59:44', '14:03:00'), SDC)['io_load_pf'], 15)

    def test_clock_period_change_is_rejected(self):
        with self.assertRaises(ValueError):
            audit.check_constraints(SDC, SDC, SDC.replace('10.0000', '20.0000'))

    def test_lower_load_is_rejected_even_when_all_arms_agree(self):
        changed = SDC.replace('15.0000', '1.5000')
        with self.assertRaises(ValueError):
            audit.check_constraints(changed, changed, changed)

    def test_missing_load_is_not_zero_or_pass(self):
        missing = SDC.split('set_load')[0]
        with self.assertRaises(ValueError):
            audit.check_constraints(missing, missing, missing)

    def test_added_exception_is_not_ignored_as_timestamp(self):
        with self.assertRaises(ValueError):
            audit.check_constraints(SDC, SDC, SDC + 'set_false_path -from [all_registers]\n')

    def test_pg_needs_actual_connected_logs_and_checked_rows(self):
        self.assertEqual(audit.check_placement_pg(CHECKS, LOG)['result'], 'PASS')
        with self.assertRaises(ValueError):
            audit.check_placement_pg(CHECKS, LOG.replace('All shapes on net VSS are connected.', ''))

    def test_error_log_cannot_be_hidden_by_success_rows(self):
        with self.assertRaises(ValueError):
            audit.check_placement_pg(CHECKS, LOG + '\n[ERROR DPL-0001] overlap')

    def test_nonzero_placement_or_duplicate_pg_rows_are_rejected(self):
        changed = copy.deepcopy(CHECKS)
        changed[0]['tcl_catch_code'] = '1'
        with self.assertRaises(ValueError):
            audit.check_placement_pg(changed, LOG)
        with self.assertRaises(ValueError):
            audit.check_placement_pg(CHECKS + [CHECKS[1]], LOG)

    def test_pg_failed_result_is_not_just_tcl_catch_success(self):
        changed = copy.deepcopy(CHECKS)
        changed[1]['message'] = '0'
        with self.assertRaises(ValueError):
            audit.check_placement_pg(changed, LOG)

    def test_current_source_capture_is_not_inherited_from_old_eco(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, candidate = root / 'current-source', root / 'candidate'
            source.mkdir()
            candidate.mkdir()
            for kind in ('instances', 'iterms', 'bterms', 'bpin_boxes', 'bounds'):
                (source / ('after_' + kind + '.tsv')).write_text('key\tvalue\noriginal\tcurrent\n')
                (candidate / ('before_' + kind + '.tsv')).write_text('key\tvalue\noriginal\tcurrent\n')
            self.assertEqual(audit.check_source_capture(source, candidate)['result'], 'PASS')
            (candidate / 'before_iterms.tsv').write_text('key\tvalue\noriginal\told_candidate\n')
            with self.assertRaises(ValueError):
                audit.check_source_capture(source, candidate)

    def test_raw_default_power_does_not_invent_missing_tt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.rpt'
            path.write_text('report_power ff\n-----\nTotal 1 2 3 4\n')
            self.assertIsNone(audit.raw_power(path))


if __name__ == '__main__':
    unittest.main()
