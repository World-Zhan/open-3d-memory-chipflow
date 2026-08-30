# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analyze = load_module("analyze_croc_lvs", ROOT / "scripts/analyze_croc_lvs.py")


class LvsAnalysisTests(unittest.TestCase):
    def test_parse_subckt_continuations_only(self):
        text = """* comment
.SUBCKT croc_chip VDD VSS clk_i
+ gpio0_io uart_tx_o
X0 VDD VSS foo
.ENDS
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "croc.cdl"
            path.write_text(text, encoding="utf-8")
            result = analyze.parse_subckt_ports(path, "croc_chip")
        self.assertEqual(result["ports"], ["VDD", "VSS", "clk_i", "gpio0_io", "uart_tx_o"])

    def test_composite_alias_mapping_does_not_count_as_exact(self):
        expected = ["VDD", "VSS", "gpio0_io"]
        extracted = [
            "VDD|VDD!|supply|vdd",
            "VSS|VSS!|vss",
            "anode|cathode|core|gpio0_io|pad",
            "gate|ngate|o",
        ]
        result = analyze.compare_top_ports(expected, extracted)
        self.assertEqual(result["exact_shared_count"], 0)
        self.assertEqual(result["schematic_ports_recovered_as_aliases"], 3)
        self.assertEqual(result["abnormal_layout_formal_port_count"], 1)

    def test_port_categories_are_mutually_exclusive(self):
        expected = {"VDD", "gpio0_io"}
        tokens = [
            "VDD|supply|vdd",
            "anode|gpio0_io|pad",
            "i_core/u0/A",
            "gate|ngate|o",
            "net123",
        ]
        categories = [analyze.classify_layout_port(token, expected) for token in tokens]
        self.assertEqual(len(categories), len(tokens))
        self.assertEqual(len(set(enumerate(categories))), len(tokens))
        self.assertEqual(categories[-1], "single_generated_net")

    def test_blank_ignore_top_ports_option_does_not_consume_next_log_line(self):
        text = (
            "Selected IGNORE_TOP_PORTS_MISMATCH option: \n"
            "Selected IMPLICIT_NETS option: (none)\n"
            "flat  mode is enabled.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "croc.log"
            path.write_text(text, encoding="utf-8")
            result = analyze.parse_log_options(path)
        self.assertEqual(result["ignore_top_ports_mismatch_raw"], "")
        self.assertFalse(result["ignore_top_ports_mismatch_enabled"])

    def test_top_level_pins_boolean_is_observed_from_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lvs.log"
            path.write_text("Selected TOP_LVL_PINS option: true\n", encoding="utf-8")
            self.assertTrue(analyze.parse_log_options(path)["top_level_pins_option"])
            path.write_text("Selected TOP_LVL_PINS option: false\n", encoding="utf-8")
            self.assertFalse(analyze.parse_log_options(path)["top_level_pins_option"])
            path.write_text("no top pin option in legacy log\n", encoding="utf-8")
            self.assertIsNone(analyze.parse_log_options(path)["top_level_pins_option"])

    def test_negative_deck_runtime_is_null_but_raw_log_is_preserved(self):
        line = (
            "2026-08-30 10:37:06 +0200: Memory Usage (474824K) : "
            "LVS Total Run time -1.431181 seconds"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lvs.log"
            path.write_text(line + "\n", encoding="utf-8")
            result = analyze.parse_log_options(path)
        self.assertIsNone(result["deck_runtime_seconds"])
        self.assertEqual(result["deck_runtime_raw_seconds"], -1.431181)
        self.assertFalse(result["deck_runtime_valid"])
        self.assertEqual(
            result["deck_runtime_invalid_reason"],
            "negative_runtime_reported_by_deck",
        )
        self.assertEqual(result["deck_runtime_log_line"], line)

    def test_nonnegative_deck_runtime_remains_valid(self):
        line = "LVS Total Run time 0.979272 seconds"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lvs.log"
            path.write_text(line + "\n", encoding="utf-8")
            result = analyze.parse_log_options(path)
        self.assertEqual(result["deck_runtime_seconds"], 0.979272)
        self.assertEqual(result["deck_runtime_raw_seconds"], 0.979272)
        self.assertTrue(result["deck_runtime_valid"])
        self.assertIsNone(result["deck_runtime_invalid_reason"])

    def test_attempt2_checkpoint_invariants(self):
        run = ROOT / "runs/croc-sg13g2-baseline-20260827-001"
        port_report = json.loads(
            (run / "signoff.attempt-2/lvs/port_mismatch_analysis.json").read_text(encoding="utf-8")
        )
        analysis = port_report["top_port_analysis"]
        self.assertEqual(analysis["schematic_port_count"], 52)
        self.assertEqual(analysis["layout_extracted_formal_port_count"], 135057)
        self.assertEqual(analysis["exact_shared_count"], 0)
        self.assertEqual(sum(analysis["category_counts"].values()), 135057)
        self.assertEqual(len(analysis["composite_formal_port_samples_first_100"]), 100)
        self.assertTrue(
            all("|" in sample["extracted_formal_port"] for sample in analysis["composite_formal_port_samples_first_100"])
        )
        self.assertEqual(len(analysis["abnormal_formal_port_samples_first_100"]), 100)

        milestone = json.loads((run / "milestone.json").read_text(encoding="utf-8"))
        self.assertFalse(milestone["public_rule_signoff"])
        self.assertEqual(sum(rule["count"] for rule in milestone["drc"]["rules"]), 1585)
        self.assertFalse(milestone["lvs"]["exact_match"])


if __name__ == "__main__":
    unittest.main()
