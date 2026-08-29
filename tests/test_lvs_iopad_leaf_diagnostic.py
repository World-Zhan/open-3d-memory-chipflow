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
    "lvs_iopad_leaf_diagnostic",
    SCRIPTS / "run_lvs_iopad_leaf_diagnostic.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LvsIopadLeafDiagnosticTests(unittest.TestCase):
    def test_targets_are_exactly_the_two_io_diode_leaves(self) -> None:
        self.assertEqual(
            [(case["cell"], case["split_net"]) for case in MODULE.LEAF_CASES],
            [
                ("sg13g2_DCNDiode", "cathode"),
                ("sg13g2_DCPDiode", "anode"),
            ],
        )

    def test_minimal_cdl_preserves_exact_three_port_header(self) -> None:
        library = """
* header
.SUBCKT sg13g2_DCNDiode anode cathode guard
DD1 sub! cathode dantenna m=1
DD0 sub! cathode dantenna m=1
XR0 anode sub! ptap1 A=1p P=1u
.ENDS
.SUBCKT unrelated a b
R0 a b 1
.ENDS
"""
        text = MODULE.build_minimal_cdl(library, "sg13g2_DCNDiode")
        self.assertIn(".SUBCKT sg13g2_DCNDiode anode cathode guard", text)
        self.assertNotIn(".SUBCKT unrelated", text)
        self.assertEqual(text.lower().count(".subckt"), 1)

    def test_public_support_scan_does_not_invent_io_abstract_option(self) -> None:
        result = MODULE.scan_public_support(
            "parser.add_argument('--run_mode')\nparser.add_argument('--layout_netlist')",
            "--run_mode flat deep --disable_tap_extraction --implicit_nets",
            'cheat("*") { extract_devices(...) }',
            "re-hierarchisation supports cheats",
            "cheat(SRAM_SHAREDSD_CELLS) { ... }",
            ["testing/test_inv.gds"],
        )
        self.assertFalse(
            result["supported_io_leaf_abstract_or_selective_flatten_found"]
        )
        self.assertTrue(result["internal_tap_cheat"]["present"])
        self.assertFalse(
            result["internal_tap_cheat"]["user_selectable_io_leaf_abstraction"]
        )
        self.assertFalse(result["official_dcn_dcp_regression_fixture_found"])

    def test_public_support_scan_reports_explicit_flatten_option_if_present(self) -> None:
        result = MODULE.scan_public_support(
            "parser.add_argument('--selective-flatten')",
            "",
            "",
            "",
            "",
            [],
        )
        self.assertEqual(
            result["documented_io_leaf_abstract_or_selective_flatten_options"],
            ["--selective-flatten"],
        )

    def test_leaf_detail_reproduces_named_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schematic = root / "leaf.cdl"
            extracted = root / "leaf.cir"
            schematic.write_text(
                ".SUBCKT leaf anode cathode guard\n"
                "D0 sub! cathode dantenna\n"
                "D1 sub! cathode dantenna\n"
                ".ENDS\n",
                encoding="utf-8",
            )
            extracted.write_text(
                ".SUBCKT leaf anode cathode cathode$1 guard\n"
                "X0 $1 cathode dantenna\n"
                "X1 $1 cathode$1 dantenna\n"
                ".ENDS\n",
                encoding="utf-8",
            )
            result = MODULE.build_leaf_detail(
                "leaf",
                "cathode",
                "dantenna",
                schematic,
                extracted,
                {"direct_text_labels": [{"text": "cathode"}]},
            )
        self.assertTrue(result["split_net_reproduced"])
        self.assertEqual(len(result["schematic_references"]), 2)
        self.assertEqual(len(result["extracted_base_net_references"]), 1)
        self.assertEqual(len(result["extracted_split_net_references"]), 1)

    def test_conclusion_remains_conservative(self) -> None:
        cases = [
            {
                "cell": case["cell"],
                "result": {"status": "FAIL"},
                "detail": {"split_net_reproduced": True},
            }
            for case in MODULE.LEAF_CASES
        ]
        support = {"supported_io_leaf_abstract_or_selective_flatten_found": False}
        conclusion = MODULE.build_conclusion(cases, support)
        self.assertTrue(conclusion["both_target_splits_reproduced"])
        self.assertFalse(conclusion["root_cause_fully_identified"])
        self.assertFalse(conclusion["full_chip_135057_port_mismatch_attributed_to_io_only"])
        self.assertFalse(conclusion["full_chip_attempt_3_authorized"])

    def test_forbidden_options_are_not_in_a_strict_command(self) -> None:
        command = [
            "python3",
            "run_lvs.py",
            "--layout=leaf.gds",
            "--netlist=leaf.cdl",
            "--run_dir=run",
            "--topcell=leaf",
            "--run_mode=deep",
        ]
        MODULE.validate_strict_command(command)
        for option in MODULE.FORBIDDEN_OR_UNUSED_OPTIONS:
            self.assertNotIn(option, command)


if __name__ == "__main__":
    unittest.main()
