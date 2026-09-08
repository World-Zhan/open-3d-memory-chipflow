# SPDX-License-Identifier: Apache-2.0
"""Adversarial checks for stage interpretation, independent of EDA execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('stages',ROOT/'scripts/audit_lvs_dcn_stages.py')
MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)

class StageEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=ROOT/'runs'/MOD.RUN_ID/'snapshots'
        cls.snapshots={p.name.removesuffix('.inventory.json'):json.loads(p.read_text()) for p in folder.glob('*.inventory.json')}

    def test_actual_archive_records_exact_failure_stages(self):
        findings=MOD.evaluate_stages(self.snapshots)
        self.assertEqual(findings['snapshot_count'],31)
        self.assertEqual(findings['layout_guard_first_removed'],'rfmos_model_mapping.target_netlist.purge')

    def test_missing_snapshot_rejected(self):
        records=copy.deepcopy(self.snapshots);records.pop('schematic_after_reader')
        with self.assertRaisesRegex(ValueError,'missing or unexpected'):MOD.evaluate_stages(records)

    def test_changed_inventory_bytes_rejected(self):
        record=copy.deepcopy(self.snapshots['layout_netlist_raw_before_rf_mapping'])
        record['inventory']['circuits'][0]['nets'].pop(0)
        with self.assertRaisesRegex(ValueError,'inventory hash'):MOD.validate_snapshot(record)

    def test_observer_changed_netlist_rejected(self):
        record=copy.deepcopy(self.snapshots['layout_after_compare'])
        record['observation_preserved_inventory']=False
        with self.assertRaisesRegex(ValueError,'observation changed'):MOD.validate_snapshot(record)

    def test_observer_hash_disagreement_rejected(self):
        record=copy.deepcopy(self.snapshots['layout_after_compare']);record['after_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'hashes differ'):MOD.validate_snapshot(record)

    def test_semantically_missing_raw_guard_rejected_even_if_rehashed(self):
        records=copy.deepcopy(self.snapshots);record=records['layout_netlist_raw_before_rf_mapping']
        nets=record['inventory']['circuits'][0]['nets'];nets[:]=[n for n in nets if n['name']!='guard']
        for i,n in enumerate(nets):n['ordinal']=i
        value=hashlib.sha256(json.dumps(record['inventory'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        record['before_sha256']=record['after_sha256']=value
        with self.assertRaisesRegex(ValueError,'guard absent'):MOD.evaluate_stages(records)

if __name__=='__main__':unittest.main()
