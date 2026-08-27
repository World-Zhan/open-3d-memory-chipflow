# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_json = load_module("validate_json", ROOT / "scripts/validate_json.py")
collect_croc = load_module("collect_croc_evidence", ROOT / "scripts/collect_croc_evidence.py")
collect_pin3d = load_module("collect_pin3d_evidence", ROOT / "scripts/collect_pin3d_evidence.py")
run_stage = load_module("run_stage", ROOT / "scripts/run_stage.py")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class ContractTests(unittest.TestCase):
    def passing_public_summary(self):
        data = json.loads((ROOT / "config/signoff_summary.template.json").read_text(encoding="utf-8"))
        data["classification"] = "public_rule_signoff"
        data["versions"]["repository_commit"] = "0" * 40
        data["versions"]["container_digest"] = "sha256:" + "0" * 64
        data["timing"].update({"wns_ns": 0.0, "tns_ns": 0.0, "setup_violations": 0, "hold_violations": 0})
        data["physical"].update({"unrouted_nets": 0, "pdn_connected": True})
        data["signoff"].update(
            {
                "drc_unwaived": 0,
                "antenna_unwaived": 0,
                "density_unwaived": 0,
                "offgrid_unwaived": 0,
                "lvs_exact_match": True,
            }
        )
        data["evidence"] = ["runs/example/signoff"]
        return data

    def test_json_files_parse(self):
        for path in list((ROOT / "schemas").glob("*.json")) + list((ROOT / "config").glob("*.json")) + [ROOT / "versions.lock.json"]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_open3dflow_is_reference_not_hotspot_dependency(self):
        lock = json.loads((ROOT / "versions.lock.json").read_text(encoding="utf-8"))
        reference = lock["upstreams"]["open3dflow_reference"]
        self.assertIsNone(reference["path"])
        self.assertFalse(reference["hotspot_harness_compatible"])

    def test_traffic_contract(self):
        data = json.loads((ROOT / "config/traffic_spec.json").read_text(encoding="utf-8"))
        validate_json.validate_traffic(data)

    def test_traffic_window_is_fixed(self):
        data = json.loads((ROOT / "config/traffic_spec.json").read_text(encoding="utf-8"))
        data["address"]["base"] = "0x20002000"
        with self.assertRaises(ValueError):
            validate_json.validate_traffic(data)

    def test_public_signoff_rejects_nonzero_drc(self):
        data = self.passing_public_summary()
        data["signoff"]["drc_unwaived"] = 1
        with self.assertRaises(ValueError):
            validate_json.validate_signoff(data)

    def test_public_signoff_requires_connected_pdn(self):
        data = self.passing_public_summary()
        data["physical"]["pdn_connected"] = False
        with self.assertRaises(ValueError):
            validate_json.validate_signoff(data)

    def test_complete_public_signoff_contract_passes(self):
        validate_json.validate_signoff(self.passing_public_summary())

    def test_run_id_policy(self):
        self.assertTrue(RUN_ID_RE.fullmatch("croc-baseline-001"))
        self.assertFalse(RUN_ID_RE.fullmatch("../overwrite"))

    def test_failed_stage_retry_gets_immutable_attempt_name(self):
        self.assertEqual(run_stage.next_attempt([], "croc-gds"), 1)
        failed = [{"name": "croc-gds", "status": "failed"}]
        self.assertEqual(run_stage.next_attempt(failed, "croc-gds"), 2)
        failed.append({"name": "croc-gds", "status": "failed", "attempt": 2})
        self.assertEqual(run_stage.next_attempt(failed, "croc-gds"), 3)
        with self.assertRaises(ValueError):
            run_stage.next_attempt([{"name": "croc-gds", "status": "passed"}], "croc-gds")

    def test_croc_timing_parser(self):
        text = """05_croc.final report_tns
--------------------------------------------------------------------------
0.0000
05_croc.final report_wns
--------------------------------------------------------------------------
0.1250
setup violation count 0
hold violation count 0
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.rpt"
            path.write_text(text, encoding="utf-8")
            parsed = collect_croc.final_timing(path)
        self.assertEqual(parsed["wns_ns"], 0.125)
        self.assertEqual(parsed["tns_ns"], 0.0)
        self.assertEqual(parsed["setup_violations"], 0)
        self.assertEqual(parsed["hold_violations"], 0)

    def test_pin3d_tier_instance_counter(self):
        text = """COMPONENTS 3 ;
- u0 AND2x2_upper + PLACED ( 0 0 ) N ;
- u1 DFFHQNx1_bottom + PLACED ( 0 0 ) N ;
- u2 INVx1_bottom + PLACED ( 0 0 ) N ;
END COMPONENTS
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.def"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(collect_pin3d.instance_counts(path), (1, 2))

    def test_signoff_scripts_do_not_disable_rules(self):
        text = (ROOT / "scripts/croc_signoff.sh").read_text(encoding="utf-8")
        forbidden = ["--no_density", "--no_offgrid", "--no_angle", "--ignore_top_ports_mismatch", "--implicit_nets"]
        for flag in forbidden:
            with self.subTest(flag=flag):
                self.assertNotIn(flag, text)
        self.assertIn("--antenna", text)

    def test_bondpad_cdl_matches_public_one_port_view(self):
        signoff = (ROOT / "scripts/croc_signoff.sh").read_text(encoding="utf-8")
        cdl = (ROOT / "scripts/cdl/bondpad_70x70.cdl").read_text(encoding="utf-8")
        self.assertIn("/work/scripts/cdl/bondpad_70x70.cdl", signoff)
        self.assertIn(".SUBCKT bondpad_70x70 pad", cdl)
        device_lines = [line for line in cdl.splitlines() if line and line[0].upper() in {"M", "R", "C", "D", "Q", "X"}]
        self.assertEqual(device_lines, [])

    def test_croc_filler_uses_pinned_pdk_read_only(self):
        text = (ROOT / "scripts/croc_flow.sh").read_text(encoding="utf-8")
        self.assertIn('IHP_PDK="${ROOT}/upstream/ihp-open-pdk/ihp-sg13g2"', text)
        self.assertIn('/fosic/designs/croc/ihp13/pdk/ihp-sg13g2:ro', text)

    def test_tcl_status_prefixes_are_not_command_substitutions(self):
        acceptance = (ROOT / "scripts/check_croc_final.tcl").read_text(encoding="utf-8")
        cdl = (ROOT / "scripts/write_croc_cdl.tcl").read_text(encoding="utf-8")
        self.assertNotIn('puts "[ACCEPTANCE]', acceptance)
        self.assertNotIn('puts "[SIGNOFF]', cdl)

    def test_container_runtime_uses_verified_image_id(self):
        script = (ROOT / "scripts/verify_container_lock.py").read_text(encoding="utf-8")
        self.assertIn("actual_image_id", script)
        self.assertIn("print(actual_image_id)", script)

    def test_container_fallback_is_digest_pinned(self):
        lock = json.loads((ROOT / "versions.lock.json").read_text(encoding="utf-8"))
        fallback = lock["container"]["fallback_reference"]
        self.assertIn("@sha256:", fallback)
        self.assertTrue(fallback.endswith(lock["container"]["fallback_index_digest"]))

    def test_makefile_public_targets_exist(self):
        text = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in ("doctor", "croc-rtl", "croc-netlist-sim", "croc-pnr", "croc-gds", "croc-signoff", "pin3d-smoke", "pin3d-full", "report"):
            with self.subTest(target=target):
                self.assertIn(f"{target}:", text)

    def test_orfs_build_caps_parallelism_and_disables_lto(self):
        text = (ROOT / "scripts/build_orfs.sh").read_text(encoding="utf-8")
        self.assertIn("--threads 6", text)
        self.assertIn("LINK_TIME_OPTIMIZATION=OFF", text)

    def test_croc_stages_require_same_run_predecessors(self):
        text = (ROOT / "Makefile").read_text(encoding="utf-8")
        for predecessor in ("croc-rtl", "croc-netlist-sim", "croc-pnr", "croc-gds"):
            with self.subTest(predecessor=predecessor):
                self.assertIn(f"--requires {predecessor}", text)

    def test_failed_croc_tool_still_collects_evidence(self):
        text = (ROOT / "scripts/croc_flow.sh").read_text(encoding="utf-8")
        collect = text.index("collect_croc_evidence.py")
        tool_return = text.index('if [[ ${tool_rc} -ne 0 ]]')
        self.assertLess(collect, tool_return)

    def test_docker_bootstrap_retries_official_key_download(self):
        text = (ROOT / "scripts/bootstrap_docker_ubuntu.sh").read_text(encoding="utf-8")
        self.assertIn("--retry 5", text)
        self.assertIn("--ipv4", text)
        self.assertIn("Acquire::ForceIPv4=true", text)
        self.assertIn("https://download.docker.com/linux/ubuntu/gpg", text)

    def test_croc_gds_download_is_bounded_and_retried(self):
        flow = (ROOT / "scripts/croc_flow.sh").read_text(encoding="utf-8")
        shim = (ROOT / "scripts/download-shims/curl").read_text(encoding="utf-8")
        self.assertIn("/flow-scripts/download-shims:$PATH", flow)
        for option in ("max_attempts=8", "--ipv4", "--http1.1", "--continue-at -", "--speed-time 60", "--max-time 900"):
            with self.subTest(option=option):
                self.assertIn(option, shim)
        self.assertNotIn("--retry ", shim)


if __name__ == "__main__":
    unittest.main()
