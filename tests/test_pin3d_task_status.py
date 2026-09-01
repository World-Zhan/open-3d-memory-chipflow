# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_pin3d_task_status", ROOT / "scripts/check_pin3d_task_status.py"
)
assert SPEC is not None and SPEC.loader is not None
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class Pin3dTaskStatusTests(unittest.TestCase):
    def test_ok_task_returns_zero(self):
        self.assertEqual(STATUS.task_exit_code({"status": "ok", "dispatch_rc": 0}), 0)

    def test_failed_task_propagates_dispatch_returncode(self):
        self.assertEqual(STATUS.task_exit_code({"status": "failed", "dispatch_rc": 2}), 2)

    def test_nonterminal_or_malformed_status_fails_closed(self):
        self.assertEqual(STATUS.task_exit_code({"status": "running", "dispatch_rc": None}), STATUS.STATUS_ERROR)
        self.assertEqual(STATUS.task_exit_code({"status": "ok", "dispatch_rc": True}), STATUS.STATUS_ERROR)

    def test_wrapper_includes_upper_pin_layer_and_status_gate(self):
        wrapper = (ROOT / "scripts/pin3d_flow.sh").read_text(encoding="utf-8")
        self.assertIn('MAX_ROUTING_LAYER="${MAX_ROUTING_LAYER:-M1_m}"', wrapper)
        self.assertIn("check_pin3d_task_status.py", wrapper)


if __name__ == "__main__":
    unittest.main()
