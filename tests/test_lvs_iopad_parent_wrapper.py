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
    "lvs_iopad_parent_wrapper", SCRIPTS / "run_lvs_iopad_parent_wrapper.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LvsIopadParentWrapperTests(unittest.TestCase):
    def test_instance_order_matches_one_croc_edge_segment(self) -> None:
        self.assertEqual(
            [spec["cell"] for spec in MODULE.INSTANCES],
            [
                "sg13g2_IOPadIOVss",
                "sg13g2_IOPadIOVdd",
                "sg13g2_IOPadIn",
                "sg13g2_IOPadVss",
                "sg13g2_IOPadVdd",
            ],
        )
        self.assertEqual(MODULE.CELL_PITCH_DBU, 80_000)

    def test_top_cdl_has_six_formal_ports_and_five_instances(self) -> None:
        from analyze_croc_lvs import parse_subckt_ports

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrapper.cdl"
            text = MODULE.build_top_cdl("* io library\n")
            path.write_text(text, encoding="utf-8")
            header = parse_subckt_ports(path, MODULE.TOP_CELL)
        self.assertEqual(header["ports"], list(MODULE.TOP_PORTS))
        self.assertEqual(header["port_count"], 6)
        self.assertEqual(sum(line.startswith("X") for line in text.splitlines()), 5)

    def test_label_sources_cover_interface_exactly(self) -> None:
        self.assertEqual(set(MODULE.LABEL_SOURCES), set(MODULE.TOP_PORTS))
        self.assertEqual(MODULE.LABEL_SOURCES["IOVSS"], ("XIOVSS", "iovss"))
        self.assertEqual(MODULE.LABEL_SOURCES["IOVDD"], ("XIOVDD", "iovdd"))

    def test_conclusion_requires_both_strict_pass_and_exact_port_set(self) -> None:
        passing = {
            "status": "PASS",
            "extracted_port_set_exact": True,
            "schematic_formal_ports": 6,
            "extracted_formal_ports": 6,
            "schematic_port_order": list(MODULE.TOP_PORTS),
            "extracted_port_order": list(MODULE.TOP_PORTS),
        }
        conclusion = MODULE.build_conclusion(passing)
        self.assertTrue(conclusion["parent_wrapper_strict_lvs_exact_match"])
        self.assertTrue(conclusion["parent_supply_segment_hypothesis_supported"])
        self.assertFalse(conclusion["full_chip_root_cause_fully_identified"])
        self.assertFalse(conclusion["full_chip_attempt_3_authorized"])

        port_only = dict(passing, status="FAIL")
        conclusion = MODULE.build_conclusion(port_only)
        self.assertFalse(conclusion["parent_wrapper_strict_lvs_exact_match"])
        self.assertFalse(conclusion["parent_supply_segment_hypothesis_supported"])

    def test_existing_variant_command_is_reconstructed_without_weakening(self) -> None:
        recorded = (
            "python3 run_lvs.py --layout=a.gds --netlist=a.cdl "
            "--run_dir=/work/run/strict_deep --topcell=top --run_mode=deep"
        )
        command = MODULE.build_existing_variant_command(
            recorded, "/work/run/strict_deep_combine_devices", True
        )
        self.assertIn("--run_dir=/work/run/strict_deep_combine_devices", command)
        self.assertIn("--combine_devices", command)
        self.assertNotIn("--ignore_top_ports_mismatch", command)
        self.assertNotIn("--implicit_nets", command)

    def test_conclusion_preserves_failed_lvs_with_exact_ports(self) -> None:
        failed = {
            "name": "strict_deep_baseline",
            "status": "FAIL",
            "extracted_port_set_exact": True,
            "schematic_formal_ports": 6,
            "extracted_formal_ports": 6,
            "schematic_port_order": list(MODULE.TOP_PORTS),
            "extracted_port_order": list(MODULE.TOP_PORTS),
            "requested_options": {"combine_devices": False},
        }
        conclusion = MODULE.build_conclusion(failed, [failed], [])
        self.assertFalse(conclusion["parent_wrapper_strict_lvs_exact_match"])
        self.assertEqual(conclusion["variant_status"]["strict_deep_baseline"]["strict_lvs"], "FAIL")

    def test_conclusion_reports_extra_and_missing_ports(self) -> None:
        result = {
            "status": "FAIL",
            "extracted_port_set_exact": False,
            "schematic_formal_ports": 6,
            "extracted_formal_ports": 6,
            "schematic_port_order": ["PAD", "P2C", "VDD"],
            "extracted_port_order": ["PAD", "P2C", "iovss$1"],
        }
        conclusion = MODULE.build_conclusion(result)
        self.assertEqual(conclusion["extra_extracted_formal_ports"], ["iovss$1"])
        self.assertEqual(conclusion["missing_schematic_formal_ports"], ["VDD"])
        self.assertFalse(conclusion["full_chip_135057_port_mismatch_attributed_to_io_only"])


if __name__ == "__main__":
    unittest.main()
