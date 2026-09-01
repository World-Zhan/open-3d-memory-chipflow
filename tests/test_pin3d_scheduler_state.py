# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "archive_pin3d_task_status", ROOT / "scripts/archive_pin3d_task_status.py"
)
assert SPEC is not None and SPEC.loader is not None
ARCHIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARCHIVE)


class Pin3dSchedulerStateTests(unittest.TestCase):
    def roots(self, base: Path):
        status_root = base / "status"
        runs_root = base / "runs"
        run_dir = runs_root / "test-run"
        status_root.mkdir()
        run_dir.mkdir(parents=True)
        return status_root, runs_root, run_dir

    def test_terminal_status_is_moved_into_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_root, runs_root, run_dir = self.roots(Path(tmp))
            status_file = status_root / "ord__asap7_3D__gcd.json"
            payload = {"status": "failed", "dispatch_rc": 2}
            status_file.write_text(json.dumps(payload), encoding="utf-8")
            destination = ARCHIVE.archive_terminal_status(
                status_file, run_dir, "pin3d-smoke.attempt-3", status_root=status_root, runs_root=runs_root
            )
            self.assertIsNotNone(destination)
            self.assertFalse(status_file.exists())
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), payload)

    def test_nonterminal_status_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_root, runs_root, run_dir = self.roots(Path(tmp))
            status_file = status_root / "ord__asap7_3D__gcd.json"
            status_file.write_text('{"status":"running"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ARCHIVE.archive_terminal_status(
                    status_file, run_dir, "pin3d-smoke", status_root=status_root, runs_root=runs_root
                )
            self.assertTrue(status_file.exists())

    def test_missing_status_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_root, runs_root, run_dir = self.roots(Path(tmp))
            status_file = status_root / "ord__asap7_3D__gcd.json"
            self.assertIsNone(
                ARCHIVE.archive_terminal_status(
                    status_file, run_dir, "pin3d-smoke", status_root=status_root, runs_root=runs_root
                )
            )

    def test_unsafe_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_root, runs_root, run_dir = self.roots(Path(tmp))
            with self.assertRaises(ValueError):
                ARCHIVE.archive_terminal_status(
                    status_root / "status.json", run_dir, "../escape", status_root=status_root, runs_root=runs_root
                )


if __name__ == "__main__":
    unittest.main()
