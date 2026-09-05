# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_pin3d_hbt_capacity_contract",
    ROOT / "scripts" / "analyze_pin3d_hbt_capacity_contract.py",
)
assert SPEC is not None and SPEC.loader is not None
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)
PATCH = ROOT / "patches" / "taiwei-pin-3d" / "0001-tech-derived-hbt-capacity-contract.patch"
WRAPPER = ROOT / "scripts" / "with_taiwei_hbt_contract_patch.sh"


class Pin3dHbtCapacityContractTests(unittest.TestCase):
    def test_current_die_has_only_twenty_five_legal_sites(self):
        capacity = ANALYZER.grid_capacity(6.676, 6.676, 0.032, 0.032, 1.568)
        self.assertEqual(capacity["sites_x"], 5)
        self.assertEqual(capacity["sites_y"], 5)
        self.assertEqual(capacity["total_sites"], 25)

    def test_partition_demand_expands_to_discrete_reserved_grid(self):
        plan = ANALYZER.required_core_plan(62, 0.8, 1.0, 0.032, 0.032, 1.568)
        self.assertEqual(plan["required_sites"], 78)
        self.assertEqual(plan["sites_x"], 9)
        self.assertEqual(plan["sites_y"], 9)
        self.assertEqual(plan["total_sites"], 81)
        self.assertTrue(math.isclose(plan["area_um2"], 198.4, abs_tol=1e-9))

    def test_real_existing_evidence_opens_only_static_stage_gate(self):
        payload = ANALYZER.analyze(
            run_id="fixture",
            spacing_analysis_path=ROOT
            / "runs"
            / "pin3d-openroad-pa-ab-20260901-003"
            / "hbt_spacing_analysis.json",
            platform_config_path=ROOT
            / "upstream"
            / "taiwei-pin-3d"
            / "platforms"
            / "asap7_3D"
            / "config.mk",
            patch_path=PATCH,
            wrapper_path=WRAPPER,
        )
        self.assertEqual(payload["contract_inputs"]["partition_selected_cut_demand"], 62)
        self.assertEqual(payload["contract_inputs"]["observed_final_route_hbt_count"], 70)
        self.assertEqual(payload["current_floorplan"]["usable_capacity_at_limit"], 20)
        self.assertTrue(payload["gates"]["static_contract_gate_open"])
        self.assertTrue(payload["gates"]["partition_pre_floorplan_ab_gate_open"])
        self.assertFalse(payload["gates"]["full_route_gate_open"])
        self.assertFalse(payload["checks"]["floorplan_stage_ab_executed"])

    def test_patch_applies_to_pinned_taiwei_and_preserves_strict_rules(self):
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT / "upstream" / "taiwei-pin-3d"),
                "apply",
                "--check",
                str(PATCH),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("rule_from_db", text)
        self.assertIn("hbt_capacity.contract.tcl", text)
        self.assertIn("capacity_validated", text)
        self.assertIn("site_snap_guarded", text)
        self.assertIn("actual_core_bbox", text)
        self.assertNotIn("SPACING 1.568", text)
        self.assertNotIn("-no_pin_access", text)
        self.assertNotIn("waiver", text.lower())

    def test_wrapper_restores_submodule_without_destructive_git(self):
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("apply --check", text)
        self.assertIn("apply --reverse --check", text)
        self.assertNotIn("reset --hard", text)
        self.assertNotIn("clean -fd", text)


if __name__ == "__main__":
    unittest.main()
