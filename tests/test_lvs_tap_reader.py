# SPDX-License-Identifier: Apache-2.0
"""Negative tests for reader/leaf evidence acceptance; no EDA execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('tap_audit',ROOT/'scripts/audit_lvs_tap_reader.py')
MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)

def rehash(record):
    digest=hashlib.sha256(json.dumps(record['inventory'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    record['before_sha256']=record['after_sha256']=digest

class TapReaderEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader=[json.loads((ROOT/'runs'/MOD.READER_ID/a/'results.json').read_text()) for a in ('control','candidate')]
        cls.leaf=[MOD.snapshots(ROOT/'runs'/MOD.LEAF_ID/a/'snapshots') for a in ('control','candidate')]
        cls.execution=json.loads((ROOT/'runs'/MOD.READER_ID/'candidate/execution.json').read_text())

    def test_real_reader_twenty_cases(self):
        result=MOD.READER.evaluate_reader(*self.reader)
        self.assertEqual((result['result'],result['case_count'],result['negative_cases']),('PASS',20,12))

    def test_reader_missing_case_rejected(self):
        candidate=copy.deepcopy(self.reader[1]);candidate['cases'].pop('bad_multiplier')
        with self.assertRaisesRegex(ValueError,'missing'):MOD.READER.evaluate_reader(self.reader[0],candidate)

    def test_reader_swapped_terminals_rejected(self):
        candidate=copy.deepcopy(self.reader[1]);d=MOD.READER.top(candidate['cases']['ptap_si'])['devices'][0]
        d['terminals']={'TIE':'W','WELL':'T'}
        with self.assertRaisesRegex(ValueError,'terminal order'):MOD.READER.evaluate_reader(self.reader[0],candidate)

    def test_reader_si_units_not_silently_passed_through(self):
        candidate=copy.deepcopy(self.reader[1]);d=MOD.READER.top(candidate['cases']['ptap_si'])['devices'][0]
        d['parameters']['A']=141.253e-12
        with self.assertRaisesRegex(ValueError,'units'):MOD.READER.evaluate_reader(self.reader[0],candidate)

    def test_ordinary_resistor_change_rejected(self):
        candidate=copy.deepcopy(self.reader[1]);d=MOD.READER.top(candidate['cases']['ordinary_r'])['devices'][0]
        d['parameters']['R']=0
        with self.assertRaisesRegex(ValueError,'ordinary_r unchanged'):MOD.READER.evaluate_reader(self.reader[0],candidate)

    def test_unknown_subcircuit_must_remain_hierarchical(self):
        candidate=copy.deepcopy(self.reader[1]);MOD.READER.top(candidate['cases']['unknown_defined'])['subcircuits']=[]
        with self.assertRaisesRegex(ValueError,'unknown_defined unchanged'):MOD.READER.evaluate_reader(self.reader[0],candidate)

    def test_bad_multiplier_must_be_rejected(self):
        candidate=copy.deepcopy(self.reader[1]);candidate['cases']['bad_multiplier']['status']='read'
        with self.assertRaisesRegex(ValueError,'bad_multiplier rejected'):MOD.READER.evaluate_reader(self.reader[0],candidate)

    def test_actual_leaf_repairs_reader_only(self):
        result=MOD.evaluate_leaf(*self.leaf)
        self.assertTrue(result['schematic_anode_port_preserved'])
        self.assertTrue(result['guard_still_removed'])
        self.assertFalse(result['tap_parameter_comparison_qualified'])

    def test_leaf_missing_snapshot_rejected(self):
        candidate=copy.deepcopy(self.leaf[1]);candidate.pop('schematic_after_compare')
        with self.assertRaisesRegex(ValueError,'missing'):MOD.evaluate_leaf(self.leaf[0],candidate)

    def test_leaf_tap_loss_rejected_even_when_rehashed(self):
        candidate=copy.deepcopy(self.leaf[1]);record=candidate['schematic_after_align']
        MOD.STAGES.top(candidate,'schematic_after_align')['devices'][:]=[
            d for d in MOD.STAGES.top(candidate,'schematic_after_align')['devices'] if d['class']!='PTAP1']
        rehash(record)
        with self.assertRaisesRegex(ValueError,'missing or duplicate tap'):MOD.evaluate_leaf(self.leaf[0],candidate)

    def test_leaf_unreviewed_layout_change_rejected_even_when_rehashed(self):
        candidate=copy.deepcopy(self.leaf[1]);record=candidate['layout_after_compare']
        MOD.tap(MOD.STAGES.top(candidate,'layout_after_compare'))['parameters'][1]['value']=47.54
        rehash(record)
        with self.assertRaisesRegex(ValueError,'layout inventory changed'):MOD.evaluate_leaf(self.leaf[0],candidate)

    def test_false_exit_code_is_not_integer_zero(self):
        e=copy.deepcopy(self.execution);e['returncode']=False
        with self.assertRaisesRegex(ValueError,'runner exit'):MOD.validate_terminal(e,e['terminal_state'])

    def test_oom_is_not_success(self):
        e=copy.deepcopy(self.execution);e['terminal_state']['OOMKilled']=True
        with self.assertRaisesRegex(ValueError,'not healthy'):MOD.validate_terminal(e,e['terminal_state'])

    def test_terminal_observation_disagreement_rejected(self):
        e=copy.deepcopy(self.execution);state=copy.deepcopy(e['terminal_state']);state['ExitCode']=137
        with self.assertRaisesRegex(ValueError,'observation differs'):MOD.validate_terminal(e,state)

if __name__=='__main__':unittest.main()
