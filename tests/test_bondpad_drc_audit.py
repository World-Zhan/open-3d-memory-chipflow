# SPDX-License-Identifier: Apache-2.0
import unittest
from test_contracts import ROOT,load_module
audit=load_module('audit_bondpad_drc',ROOT/'scripts/audit_bondpad_drc.py')
class AntennaCompletionTests(unittest.TestCase):
    def test_terminal_rule_and_all_output_categories_required(self):
        categories=audit.antenna_categories()
        self.assertEqual(len(categories),31)
        self.assertTrue(audit.antenna_complete('Executing rule Ant.i',categories))
        self.assertFalse(audit.antenna_complete('Executing rule Ant.i',categories-{'Ant.d_TopVia2'}))
        self.assertFalse(audit.antenna_complete('Executing rule Ant.h',categories))
    def test_task_error_cannot_be_hidden_by_category_presence(self):
        self.assertFalse(audit.antenna_complete('Executing rule Ant.i\nERROR: evaluation failed',audit.antenna_categories()))
