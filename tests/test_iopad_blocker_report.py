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

    def test_report_is_local_and_not_published(self) -> None:
        self.assertEqual(
            self.report["classification"],
            "local_upstream_issue_draft_not_published",
        )
        publication = self.report["publication"]
        self.assertFalse(publication["github_issue_created"])
        self.assertFalse(publication["remote_repository_created"])
        self.assertFalse(publication["pushed"])
        self.assertTrue(publication["authorization_required"])

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
