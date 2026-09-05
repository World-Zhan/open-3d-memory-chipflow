# SPDX-License-Identifier: Apache-2.0
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_croc_ppa import attach_probe, collect, delta, parse_area, parse_clocks, parse_def, parse_power, sha


class PpaTests(unittest.TestCase):
    def test_area_scopes_and_conflicting_duplicate(self):
        text = "Die Area: 4000000 um2\nCore Area: 1000000 um2\nTotal Area: 2000000 um2\nTotal Active Area: 450000 um2\nCore Utilization: 0.45\n"
        area = parse_area(text)
        self.assertEqual(area["die_area_um2"], 4000000)
        self.assertEqual(area["active_area_um2"], 450000)
        self.assertIsNone(area["stdcell_utilization"])
        self.assertIsNone(parse_area(text + "Die Area: 2000000 um2\n")["die_area_um2"])
        self.assertIsNone(parse_area("Die Area: nan um2\n")["die_area_um2"])
        self.assertIsNone(parse_area("Die Area: -2 um2\n")["die_area_um2"])

    def test_power_units_and_unknown_not_zero(self):
        text = "05_croc.final report_power tt\n----\nGroup Internal Switching Leakage Total\n Power Power Power Power (Watts)\nTotal 3.57e-02 6.77e-03 6.86e-06 4.24e-02 100.0%\n====\n"
        self.assertEqual(parse_power(text)[0]["groups"]["total"]["total"], 42.4)
        self.assertEqual(parse_power(text.replace("(Watts)", "(unknown)")), [])
        self.assertNotIn("total", parse_power(text.replace("4.24e-02", "nan"))[0]["groups"])
        self.assertEqual(parse_power(""), [])

    def test_def_geometry_units_and_sram_scope(self):
        text = "UNITS DISTANCE MICRONS 2000 ;\nDIEAREA ( 0 0 ) ( 2000000 4000000 ) ;\nCOMPONENTS 2 ;\n- a RM_IHPSG13_1P_512x32_c2_bm_bist + FIXED ( 0 0 ) N ;\n- b RM_IHPSG13_1P_512x32_c2_bm_bist + FIXED ( 1 1 ) N ;\nEND COMPONENTS\n"
        result = parse_def(text)
        self.assertEqual(result["die_area_um2"], 2000000)
        self.assertEqual(result["sram_bytes"], 4096)
        self.assertEqual(result["sram_macro_count"], 2)
        self.assertIsNone(parse_def("")["sram_bytes"])
        self.assertIsNone(parse_def(text.replace("MICRONS 2000", "MICRONS 0"))["die_area_um2"])

    def test_clock_constraint_is_named_and_invalid_rejected(self):
        text = "create_clock -name {clk_sys} -period 10.0000 [get_ports clk_i]\ncreate_clock -name bad -period 0 [get_ports bad]\n# create_clock -name comment -period 2 [get_ports x]\n"
        self.assertEqual(parse_clocks(text), {"clk_sys": {"period_ns": 10.0, "constraint_frequency_mhz": 100.0}})

    def test_missing_reports_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            result = collect(Path(folder), "test")
        self.assertFalse(result["acceptance"]["electrical_passed"])
        self.assertFalse(result["acceptance"]["tapeout_ready"])
        self.assertIsNone(result["power"]["estimated_tt_total_mw"])
        self.assertIsNone(result["performance"]["achieved_frequency_mhz"])
        self.assertIsNone(result["area"]["die_area_um2"])

    def test_signoff_from_different_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "signoff.json"
            path.write_text(json.dumps({"run_id": "another-run"}))
            with self.assertRaisesRegex(ValueError, "source run"):
                collect(Path(folder), "test", path)

    def test_delta_reused_and_incompatible_data(self):
        with tempfile.TemporaryDirectory() as folder:
            before = collect(Path(folder), "before")
        self.assertEqual(delta(before, before)["status"], "physical_report_unavailable")
        before["comparison_context"].update(technology="sg13g2", pdk_commit="abc", sram_bytes=4096)
        before["sources"]["final_report"]["sha256"] = "same-hash"
        before["area"]["die_area_um2"] = 100
        after = copy.deepcopy(before)
        after["area"]["die_area_um2"] = 90
        result = delta(after, before)
        self.assertEqual(result["status"], "same_physical_report_reused")
        self.assertEqual(result["metrics"]["die_area_um2"]["delta"], -10)
        self.assertIsNone(result["power_delta_mw"])
        after["comparison_context"]["sram_bytes"] = 2048
        result = delta(after, before)
        self.assertIsNone(result["metrics"]["die_area_um2"]["delta"])
        self.assertFalse(result["metrics"]["die_area_um2"]["comparable"])
        before["area"]["core_area_um2"] = float("nan")
        after["area"]["core_area_um2"] = 1
        self.assertIsNone(delta(after, before)["metrics"]["core_area_um2"]["delta"])

    def test_probe_rejects_unfinished_changed_or_unbound_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            payload = collect(run, "test")
            manifest = {"status": "completed", "returncode": 0, "layout_modified": True,
                        "source_hashes_unchanged": True}
            (run / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "unchanged layout"):
                attach_probe(payload, run)
            manifest["layout_modified"] = False
            (run / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "source identity"):
                attach_probe(payload, run)

    def test_probe_output_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_run = root / "runs/baseline"
            source_dir = source_run / "artifacts/pnr/upstream/croc/openroad/out"
            source_dir.mkdir(parents=True)
            for name in ("croc.odb", "croc.sdc"):
                (source_dir / name).write_text("immutable-source")
            probe_run = root / "runs/probe"
            probe_run.mkdir()
            report = probe_run / "probe_extracted_typ_rc.rpt"
            report.write_text("changed output")
            manifest = {"status": "completed", "returncode": 0, "layout_modified": False,
                        "source_hashes_unchanged": True,
                        "source_sha256": {str(path.relative_to(root)): sha(path) for path in source_dir.iterdir()},
                        "outputs_sha256": {report.name: "not-the-current-hash"}}
            (probe_run / "manifest.json").write_text(json.dumps(manifest))
            with patch("collect_croc_ppa.ROOT", root):
                payload = collect(source_run, "test")
                with self.assertRaisesRegex(ValueError, "output hash mismatch"):
                    attach_probe(payload, probe_run)


if __name__ == "__main__":
    unittest.main()
