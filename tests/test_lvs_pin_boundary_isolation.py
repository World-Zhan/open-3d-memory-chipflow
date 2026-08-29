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
    "lvs_pin_boundary_isolation", SCRIPTS / "run_lvs_pin_boundary_isolation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LvsPinBoundaryIsolationTests(unittest.TestCase):
    def test_cases_are_the_two_direct_pdk_cells(self) -> None:
        self.assertEqual(
            [(case["name"], case["top_cell"]) for case in MODULE.CASES],
            [
                ("inverter_only", "sg13g2_inv_1"),
                ("io_pad_only", "sg13g2_IOPadIn"),
            ],
        )

    def test_conclusion_requires_inverter_pass_and_only_io_substrate_extra(self) -> None:
        results = [
            {
                "name": "inverter_only",
                "status": "PASS",
                "schematic_port_order": ["Y", "A", "VDD", "VSS"],
                "extracted_port_order": ["VDD", "VSS", "A", "Y"],
            },
            {
                "name": "io_pad_only",
                "status": "FAIL",
                "schematic_port_order": ["pad", "p2c", "vdd", "vss", "iovdd", "iovss"],
                "extracted_port_order": ["$1", "pad", "iovss", "iovdd", "vdd", "vss", "p2c"],
            },
        ]
        conclusion = MODULE.build_conclusion(results)
        self.assertTrue(conclusion["remaining_mismatch_isolated_to_io_substrate_boundary"])
        self.assertTrue(conclusion["scope_narrowed_to_io_pad_hierarchy"])
        self.assertEqual(conclusion["io_pad_extra_extracted_formal_ports"], ["$1"])
        self.assertEqual(conclusion["observed_split_io_net"], "$1")
        self.assertFalse(conclusion["root_cause_fully_identified"])
        self.assertFalse(conclusion["full_chip_attempt_3_authorized"])

    def test_conclusion_rejects_additional_unexpected_ports(self) -> None:
        results = [
            {"name": "inverter_only", "status": "PASS"},
            {
                "name": "io_pad_only",
                "status": "FAIL",
                "schematic_port_order": ["pad"],
                "extracted_port_order": ["$1", "pad", "guard"],
            },
        ]
        conclusion = MODULE.build_conclusion(results)
        self.assertFalse(conclusion["remaining_mismatch_isolated_to_io_substrate_boundary"])
        self.assertFalse(conclusion["scope_narrowed_to_io_pad_hierarchy"])
        self.assertIsNone(conclusion["observed_split_io_net"])

    def test_actual_iovss_split_is_not_mislabeled_as_substrate_only(self) -> None:
        results = [
            {"name": "inverter_only", "status": "PASS"},
            {
                "name": "io_pad_only",
                "status": "FAIL",
                "schematic_port_order": ["pad", "iovss"],
                "extracted_port_order": ["pad", "iovss", "iovss$1"],
            },
        ]
        conclusion = MODULE.build_conclusion(results)
        self.assertTrue(conclusion["scope_narrowed_to_io_pad_hierarchy"])
        self.assertFalse(conclusion["remaining_mismatch_isolated_to_io_substrate_boundary"])
        self.assertFalse(conclusion["substrate_only_hypothesis_confirmed"])
        self.assertEqual(conclusion["observed_split_io_net"], "iovss$1")
        self.assertFalse(conclusion["root_cause_fully_identified"])


if __name__ == "__main__":
    unittest.main()
