# SPDX-License-Identifier: Apache-2.0
"""Geometry interpretation must fail closed when evidence changes."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('geometry_audit',ROOT/'reports/lvs/tap-geometry-20260910-audit.py')
MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)

class TapGeometryEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry=json.loads((ROOT/'runs/tap-geometry-20260910-001/geometry.json').read_text())
        cls.raw=json.loads((ROOT/'runs/croc-lvs-tap-reader-dcn-ab-20260910-001/candidate/snapshots/layout_netlist_raw_before_rf_mapping.inventory.json').read_text())
        text=(ROOT/'runs/croc-lvs-tap-reader-dcn-ab-20260910-001/control/inputs/sg13g2_DCNDiode.cdl').read_text()
        cls.cdl=MOD.parse_cdl(text)

    def evaluate(self,g=None,s=None,c=None):
        return MOD.evaluate(g or self.geometry,s or self.raw,c or self.cdl,0.005,9.8e-10,9.8e-4)

    def test_observed_outer_plus_two_holes_explains_extraction(self):
        result=self.evaluate();g=result['physical_geometry_proven']
        self.assertAlmostEqual(g['hull_perimeter_um']+g['hole_perimeter_sum_um'],221.76)
        self.assertTrue(g['matches_raw_strict_extraction'])
        self.assertFalse(result['equivalent_square_hypothesis']['original_IO_schematic_generator_proven'])

    def test_shape_area_independent_of_region_report(self):
        g=copy.deepcopy(self.geometry);g['regions']['ptap1_tie']['area_um2']=141.253
        with self.assertRaisesRegex(ValueError,'area disagrees'):self.evaluate(g=g)

    def test_holes_cannot_be_silently_excluded(self):
        g=copy.deepcopy(self.geometry);g['regions']['ptap1_tie']['perimeter_um']=86.64
        with self.assertRaisesRegex(ValueError,'perimeter disagrees'):self.evaluate(g=g)

    def test_missing_hole_vertices_rejected(self):
        g=copy.deepcopy(self.geometry);g['regions']['ptap1_tie']['polygons'][0]['holes_vertices_dbu'].pop()
        with self.assertRaisesRegex(ValueError,'hole inventory'):self.evaluate(g=g)

    def test_extra_component_rejected(self):
        g=copy.deepcopy(self.geometry);g['regions']['ptap1_tie']['merged_component_count']=2
        with self.assertRaisesRegex(ValueError,'topology'):self.evaluate(g=g)

    def test_changed_layout_units_rejected(self):
        g=copy.deepcopy(self.geometry);g['dbu_um']=0.005
        with self.assertRaisesRegex(ValueError,'DBU'):self.evaluate(g=g)

    def test_changed_cdl_parameter_rejects_square_hypothesis(self):
        c=copy.deepcopy(self.cdl);c['perimeter_um']=221.76
        with self.assertRaisesRegex(ValueError,'quantized equivalent square'):self.evaluate(c=c)

    def test_real_guard_terminal_precludes_unloaded_model_claim(self):
        c=copy.deepcopy(self.cdl);c['guard_device_references']=1
        with self.assertRaisesRegex(ValueError,'guard has schematic'):self.evaluate(c=c)

    def test_well_marker_would_change_guard_interpretation(self):
        g=copy.deepcopy(self.geometry);g['derivation_observations']['ntap1_marker_selected_well_text_count']=1
        with self.assertRaisesRegex(ValueError,'guard marked'):self.evaluate(g=g)

    def test_missing_contacts_precludes_physical_guard_claim(self):
        g=copy.deepcopy(self.geometry);g['derivation_observations']['guard_contact_count']=0
        with self.assertRaisesRegex(ValueError,'physical guard path'):self.evaluate(g=g)

if __name__=='__main__':unittest.main()
