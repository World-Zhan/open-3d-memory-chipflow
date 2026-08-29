# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "lvs_iopad_diagnostic", SCRIPTS / "run_lvs_iopad_diagnostic.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LvsIopadDiagnosticTests(unittest.TestCase):
    def test_subckt_body_and_exact_net_references(self) -> None:
        text = """.SUBCKT pad pad iovss iovss$1
X1 \\$1 iovss pad child
X2 \\$1 iovss$1 pad child
R1 iovss$1 \\$1 ptap1
.ENDS
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.cir"
            path.write_text(text, encoding="utf-8")
            statements = MODULE.parse_subckt_statements(path, "pad")
        self.assertEqual(len(statements), 3)
        self.assertEqual(MODULE.statements_referencing(statements, "iovss"), ["X1 \\$1 iovss pad child"])
        self.assertEqual(
            MODULE.statements_referencing(statements, "iovss$1"),
            ["X2 \\$1 iovss$1 pad child", "R1 iovss$1 \\$1 ptap1"],
        )
        self.assertEqual(len(MODULE.statements_referencing(statements, "$1")), 3)

    def test_library_summary_detects_repeated_iovss_split(self) -> None:
        cases = [
            {
                "top_cell": "sg13g2_IOPadIn",
                "status": "FAIL",
                "schematic_port_order": ["pad", "iovss"],
                "extracted_port_order": ["pad", "iovss", "iovss$1"],
            },
            {
                "top_cell": "sg13g2_IOPadOut",
                "status": "FAIL",
                "schematic_port_order": ["pad", "iovss"],
                "extracted_port_order": ["pad", "iovss", "iovss$1"],
            },
        ]
        result = MODULE.summarize_cases(cases)
        self.assertTrue(result["repeated_across_iopad_library"])
        self.assertFalse(result["single_cell_data_problem_supported"])
        self.assertEqual(result["extra_formal_port_frequency"], {"iovss$1": 2})
        self.assertEqual(
            result["cells_with_extra_iovss_component"],
            ["sg13g2_IOPadIn", "sg13g2_IOPadOut"],
        )
        self.assertFalse(result["root_cause_fully_identified"])
        self.assertFalse(result["full_chip_135057_port_mismatch_attributed_to_io_only"])
        self.assertFalse(result["full_chip_attempt_3_authorized"])

    def test_library_summary_categorizes_power_split_composite_and_missing_ports(self) -> None:
        cases = [
            {
                "top_cell": "pad_a",
                "status": "FAIL",
                "schematic_port_order": ["pad", "padres", "iovdd", "vdd"],
                "extracted_port_order": ["pad|padres", "iovdd", "iovdd$1"],
            },
            {
                "top_cell": "pad_b",
                "status": "FAIL",
                "schematic_port_order": ["iovss"],
                "extracted_port_order": ["iovss", "iovss$1"],
            },
        ]
        result = MODULE.summarize_cases(cases)
        self.assertEqual(result["cells_with_extra_iovdd_component"], ["pad_a"])
        self.assertEqual(result["cells_with_extra_iovss_component"], ["pad_b"])
        self.assertEqual(result["cells_with_composite_formal_ports"], {"pad_a": ["pad|padres"]})
        self.assertEqual(
            result["cells_with_missing_schematic_ports"],
            {"pad_a": ["pad", "padres", "vdd"]},
        )

    def test_library_summary_keeps_single_cell_result_conservative(self) -> None:
        cases = [
            {
                "top_cell": "sg13g2_IOPadIn",
                "status": "FAIL",
                "schematic_port_order": ["pad", "iovss"],
                "extracted_port_order": ["pad", "iovss", "iovss$1"],
            }
        ]
        result = MODULE.summarize_cases(cases)
        self.assertTrue(result["single_cell_data_problem_supported"])
        self.assertFalse(result["repeated_across_iopad_library"])
        self.assertFalse(result["root_cause_fully_identified"])


if __name__ == "__main__":
    unittest.main()
