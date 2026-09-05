# SPDX-License-Identifier: Apache-2.0
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_bondpad_pin_access import access_counts, pin_rectangles

LOG = '''#scanned instances = 2
#unique  instances = 2
#macroGenAp = 3234
#macroValidPlanarAp = 480
#macroValidViaAp = 0
#macroNoAp = 0
[INFO DRT-0166] Complete pin access.
'''


class AccessAuditTests(unittest.TestCase):
    def test_zero_via_remains_observed_zero(self):
        result = access_counts(LOG, 0)
        self.assertTrue(result['aggregate_macro_access_check_passed'])
        self.assertEqual(result['macroValidViaAp'], 0)

    def test_missing_or_duplicate_count_rejected(self):
        for text in (LOG.replace('#macroNoAp = 0\n', ''), LOG + '#macroNoAp = 0\n'):
            with self.assertRaises(ValueError):
                access_counts(text, 0)

    def test_no_access_or_no_completion_or_tool_failure_rejected(self):
        for text, rc in ((LOG.replace('#macroNoAp = 0', '#macroNoAp = 1'), 0),
                         (LOG.replace('[INFO DRT-0166] Complete pin access.', ''), 0),
                         (LOG, 1), (LOG + '[ERROR DRT-0001] failed', 0)):
            self.assertFalse(access_counts(text, rc)['aggregate_macro_access_check_passed'])

    def test_missing_pin_layer_rejected(self):
        with self.assertRaises(ValueError):
            pin_rectangles('layer\txmin_dbu\tymin_dbu\txmax_dbu\tymax_dbu\nMetal2\t0\t0\t70000\t4070\n')

    def test_inverted_rectangle_rejected(self):
        with self.assertRaises(ValueError):
            pin_rectangles('layer\txmin_dbu\tymin_dbu\txmax_dbu\tymax_dbu\nMetal2\t0\t70000\t70000\t4070\n')
