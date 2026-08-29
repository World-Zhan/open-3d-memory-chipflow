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
SPEC = importlib.util.spec_from_file_location("lvs_pin_boundary", SCRIPTS / "run_lvs_pin_boundary_ab.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LvsPinBoundaryTests(unittest.TestCase):
    def test_expected_top_ports_are_unique_and_ordered(self) -> None:
        self.assertEqual(
            MODULE.expected_top_ports(),
            [
                "IO_PAD",
                "IO_P2C",
                "IO_VDD",
                "IO_VSS",
                "IO_IOVDD",
                "IO_IOVSS",
                "INV_Y",
                "INV_A",
                "INV_VDD",
                "INV_VSS",
            ],
        )
        self.assertEqual(len(set(MODULE.expected_top_ports())), 10)

    def test_extract_subckt_block_is_bounded(self) -> None:
        text = ".SUBCKT first A B\nR1 A B 1k\n.ENDS\n.SUBCKT target X Y\nM1 X Y 0 0 n\n.ENDS target\n"
        self.assertEqual(
            MODULE.extract_subckt_block(text, "target"),
            ".SUBCKT target X Y\nM1 X Y 0 0 n\n.ENDS target\n",
        )
        with self.assertRaises(ValueError):
            MODULE.extract_subckt_block(text, "missing")

    def test_variant_commands_preserve_strict_defaults(self) -> None:
        base = dict(
            python="python3",
            runner=Path("run_lvs.py"),
            layout=Path("case.gds"),
            schematic=Path("case.cdl"),
            run_dir=Path("out"),
        )
        deep_off = MODULE.build_variant_command(**base, run_mode="deep", top_lvl_pins=False)
        flat_on = MODULE.build_variant_command(**base, run_mode="flat", top_lvl_pins=True)
        self.assertIn("--run_mode=deep", deep_off)
        self.assertNotIn("--top_lvl_pins", deep_off)
        self.assertIn("--run_mode=flat", flat_on)
        self.assertIn("--top_lvl_pins", flat_on)
        for command in (deep_off, flat_on):
            self.assertFalse(any(token.split("=", 1)[0] in MODULE.FORBIDDEN_OPTIONS for token in command))

    def test_forbidden_options_are_rejected(self) -> None:
        for option in sorted(MODULE.FORBIDDEN_OPTIONS):
            with self.subTest(option=option):
                with self.assertRaises(ValueError):
                    MODULE.validate_strict_command(["python3", "run_lvs.py", option])

    def test_top_cdl_has_ten_formal_ports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.cdl"
            path.write_text(MODULE.build_top_cdl("* io library\n", ".SUBCKT sg13g2_inv_1 Y A VDD VSS\n.ENDS\n"))
            from analyze_croc_lvs import parse_subckt_ports

            header = parse_subckt_ports(path, MODULE.TOP_CELL)
            self.assertEqual(header["port_count"], 10)
            self.assertEqual(header["ports"], MODULE.expected_top_ports())


if __name__ == "__main__":
    unittest.main()
