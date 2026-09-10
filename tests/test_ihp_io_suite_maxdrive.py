# SPDX-License-Identifier: Apache-2.0
import sys
import unittest
from test_contracts import ROOT, load_module
sys.path.insert(0, str(ROOT / 'scripts'))
a = load_module('audit_ihp_io_suite_maxdrive', ROOT / 'scripts/audit_ihp_io_suite_maxdrive.py')


class MaxdriveIsolationTests(unittest.TestCase):
    def pair(self):
        original = '- out16 sg13g2_IOPadOut16mA + FIXED ( 0 0 ) N ;\n- net ( out16 pad ) ;\n'
        return original, original.replace('sg13g2_IOPadOut16mA', 'sg13g2_IOPadOut30mA')

    def test_one_master_allowed(self):
        a.single_master_change(*self.pair())

    def test_net_change_rejected(self):
        old, new = self.pair()
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            a.single_master_change(old, new.replace('( out16 pad )', '( other pad )'))

    def test_two_changes_rejected(self):
        old, new = self.pair()
        with self.assertRaisesRegex(ValueError, 'Exactly one'):
            a.single_master_change(old + old, new + new)

    def test_move_rejected(self):
        old, new = self.pair()
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            a.single_master_change(old, new.replace('( 0 0 )', '( 100 0 )'))
