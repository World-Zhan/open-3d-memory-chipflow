# SPDX-License-Identifier: Apache-2.0
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_contracts import ROOT, load_module

report = load_module("chipflow_report", ROOT / "scripts/report.py")


class ReportAuditTests(unittest.TestCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_latest_attempt_uses_numeric_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for attempt in (2, 10):
                self.write(run / f"signoff.attempt-{attempt}/signoff_summary.json", {"attempt": attempt})
            self.assertEqual(report.find_summary(run)[1]["attempt"], 10)

    def test_incomplete_latest_attempt_cannot_reuse_old_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.write(run / "signoff/signoff_summary.json", {"classification": "public_rule_signoff"})
            (run / "signoff.attempt-2").mkdir()
            self.assertIsNone(report.find_summary(run)[1])

    def test_report_exposes_audit_without_rewriting_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {"run_id": "baseline", "stages": [{"name": "croc-pnr", "status": "passed"}]}
            manifest_path = root / "runs/baseline/manifest.json"
            self.write(manifest_path, manifest)
            original = manifest_path.read_bytes()
            self.write(root / "runs/croc-acceptance-audit-test/summary.json", {
                "source_run_id": "baseline", "status": "electrical_acceptance_failed",
                "observed_timing": {"max_slew_violations": 76, "max_capacitance_violations": 71,
                                    "max_fanout_violations": 200}})
            with patch.object(report, "ROOT", root), patch("sys.argv", ["report.py", "--runs", "runs", "--output", "out"]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(report.main(), 0)
            data = json.loads((root / "out/runs_summary.json").read_text())
            self.assertEqual(data["runs"][0]["stages"][0]["status"], "passed")
            self.assertEqual(data["runs"][0]["acceptance_audits"][0]["summary"]["status"], "electrical_acceptance_failed")
            self.assertIn("76 / 71 / 200", (root / "out/runs_summary.md").read_text())
            self.assertEqual(manifest_path.read_bytes(), original)
