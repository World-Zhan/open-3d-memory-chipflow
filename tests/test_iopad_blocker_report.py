# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/blockers/ihp-sg13g2-io-diode-strict-lvs.json"


class IopadBlockerReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_report_records_publication_without_changing_conclusion(self) -> None:
        self.assertEqual(
            self.report["classification"],
            "upstream_issue_published",
        )
        publication = self.report["publication"]
        self.assertTrue(publication["github_issue_created"])
        self.assertEqual(publication["github_issue_number"], 1130)
        self.assertEqual(
            publication["github_issue_url"],
            "https://github.com/IHP-GmbH/IHP-Open-PDK/issues/1130",
        )
        self.assertTrue(publication["remote_repository_created"])
        self.assertEqual(publication["remote_repository_visibility"], "PUBLIC")
        self.assertEqual(publication["remote_default_branch"], "main")
        self.assertTrue(publication["pushed"])
        self.assertFalse(publication["authorization_required"])
        self.assertFalse(self.report["conclusion"]["root_cause_fully_identified"])
        self.assertFalse(self.report["conclusion"]["full_chip_attempt_3_authorized"])

    def test_two_official_leaf_failures_are_preserved(self) -> None:
        cases = {case["cell"]: case for case in self.report["leaf_cases"]}
        self.assertEqual(set(cases), {"sg13g2_DCNDiode", "sg13g2_DCPDiode"})
        self.assertEqual(cases["sg13g2_DCNDiode"]["status"], "fail")
        self.assertEqual(
            cases["sg13g2_DCNDiode"]["extra_extracted_ports"],
            ["cathode$1"],
        )
        self.assertEqual(cases["sg13g2_DCNDiode"]["missing_schematic_ports"], ["guard"])
        self.assertEqual(cases["sg13g2_DCPDiode"]["status"], "fail")
        self.assertEqual(
            cases["sg13g2_DCPDiode"]["extra_extracted_ports"], ["anode$1"]
        )
        self.assertEqual(cases["sg13g2_DCPDiode"]["missing_schematic_ports"], [])

    def test_generated_gds_hashes_are_explicitly_run_specific(self) -> None:
        contract = self.report["generated_minimal_gds_identity_contract"]
        self.assertTrue(contract["raw_sha256_is_run_specific"])
        self.assertFalse(contract["bitwise_deterministic_across_exports"])
        self.assertFalse(contract["semantic_geometry_digest_claimed"])
        self.assertEqual(
            self.report["official_inputs"]["io_gds"]["sha256"],
            "4281a855377b6a1ca46356e9391258dc14e8efc3b8051a65befc0fe9db3c7825",
        )
        for case in self.report["leaf_cases"]:
            generated = case["minimal_inputs"]["gds"]
            self.assertFalse(generated["bitwise_deterministic_across_exports"])
            self.assertIn("run-specific", generated["sha256_scope"])

    def test_latest_reverification_preserves_runtime_validity(self) -> None:
        rerun = self.report["latest_reverification"]
        self.assertEqual(len(rerun["cases"]), 2)
        self.assertTrue(all(case["status"] == "fail" for case in rerun["cases"]))
        self.assertTrue(
            all(case["deck_runtime_valid"] for case in rerun["cases"])
        )
        invalid = rerun["invalid_runtime_evidence"]
        self.assertLess(invalid["raw_seconds"], 0)
        self.assertIsNone(invalid["normalized_seconds"])
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["reason"], "negative_runtime_reported_by_deck")

    def test_parent_geometry_gate_remains_closed(self) -> None:
        parent = self.report["parent_geometry"]
        self.assertFalse(parent["speculative_parent_metal_added"])
        self.assertFalse(parent["closure_lvs_ab_run"])
        for case in parent["cases"]:
            self.assertFalse(case["official_parent_direct_m1_closure_observed"])
            self.assertEqual(case["shared_parent_component_ids"], [])
        self.assertFalse(
            self.report["conclusion"]["parent_metal_closure_lvs_ab_gate_open"]
        )

    def test_full_chip_flat_mismatch_is_separate(self) -> None:
        full_chip = self.report["coexisting_full_chip_flat_mismatch"]
        self.assertEqual(full_chip["schematic_formal_ports"], 52)
        self.assertEqual(full_chip["extracted_formal_ports"], 135057)
        self.assertEqual(full_chip["exact_shared_ports"], 0)
        self.assertFalse(full_chip["attributed_to_io_leaf_blocker_only"])
        self.assertFalse(self.report["conclusion"]["full_chip_attempt_3_authorized"])


if __name__ == "__main__":
    unittest.main()
