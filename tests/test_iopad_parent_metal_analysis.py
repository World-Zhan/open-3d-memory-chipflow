# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "iopad_parent_metal_analysis", SCRIPTS / "analyze_iopad_parent_metal.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class IopadParentMetalAnalysisTests(unittest.TestCase):
    def test_scope_is_exactly_two_leaf_cells_under_iopadin(self) -> None:
        self.assertEqual(MODULE.PARENT_CELL, "sg13g2_IOPadIn")
        self.assertEqual(
            [(item["leaf_cell"], item["split_net"]) for item in MODULE.TARGETS],
            [
                ("sg13g2_DCNDiode", "cathode"),
                ("sg13g2_DCPDiode", "anode"),
            ],
        )

    def test_shared_parent_components_requires_one_common_component(self) -> None:
        self.assertEqual(MODULE.shared_parent_components([[1, 4], [4, 7]]), [4])
        self.assertEqual(MODULE.shared_parent_components([[1], [2]]), [])
        self.assertEqual(MODULE.shared_parent_components([]), [])

    def test_conclusion_opens_ab_gate_only_when_both_are_closed(self) -> None:
        targets = [
            {
                "leaf_cell": "sg13g2_DCNDiode",
                "official_parent_direct_m1_closure_observed": True,
            },
            {
                "leaf_cell": "sg13g2_DCPDiode",
                "official_parent_direct_m1_closure_observed": True,
            },
        ]
        result = MODULE.build_conclusion(targets)
        self.assertTrue(result["both_target_parent_closures_observed"])
        self.assertTrue(result["parent_metal_closure_lvs_ab_gate_open"])
        self.assertFalse(result["root_cause_fully_identified"])
        self.assertFalse(result["full_chip_attempt_3_authorized"])

    def test_conclusion_keeps_gate_closed_for_partial_evidence(self) -> None:
        targets = [
            {
                "leaf_cell": "sg13g2_DCNDiode",
                "official_parent_direct_m1_closure_observed": True,
            },
            {
                "leaf_cell": "sg13g2_DCPDiode",
                "official_parent_direct_m1_closure_observed": False,
            },
        ]
        result = MODULE.build_conclusion(targets)
        self.assertFalse(result["both_target_parent_closures_observed"])
        self.assertFalse(result["parent_metal_closure_lvs_ab_gate_open"])
        self.assertFalse(result["full_chip_attempt_3_authorized"])


if __name__ == "__main__":
    unittest.main()
