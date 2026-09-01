# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_pin3d_route_ab", ROOT / "scripts/analyze_pin3d_route_ab.py"
)
assert SPEC is not None and SPEC.loader is not None
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


class Pin3dRouteAbTests(unittest.TestCase):
    def test_report_parser_counts_types_and_layers(self):
        report = """violation type: Cut Spacing
\tbbox = (0, 0) - (1, 1) on Layer hb_layer
violation type: Short
\tbbox = (0, 0) - (1, 1) on Layer M1_m
"""
        total, by_type, by_layer = ANALYZER.parse_drc_report(report)
        self.assertEqual(total, 2)
        self.assertEqual(by_type, {"Cut Spacing": 1, "Short": 1})
        self.assertEqual(by_layer, {"M1_m": 1, "hb_layer": 1})

    def test_analysis_fails_closed_on_nonzero_drc(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            base = Path(tmp)
            run_dir = base / "runs" / "fixture"
            run_dir.mkdir(parents=True)
            manifest = run_dir / "manifest.json"
            log = run_dir / "route.log"
            drc = base / "route_drc.rpt"
            binary = base / "openroad"
            patch = base / "change.patch"
            cts = base / "4_cts.odb"
            route = base / "5_route.odb"
            manifest.write_text(
                json.dumps({"stages": [{"exit_code": 0, "status": "passed", "command": ["ord-route"]}]}),
                encoding="utf-8",
            )
            log.write_text(
                "#stdCellPinNoAp = 0\n#stdCellPinCnt = 10\n"
                "[INFO DRT-0199]   Number of violations = 1.\n"
                "[INFO DRT-0198] Complete detail routing.\n"
                "[INFO ANT-0002] Found 0 net violations.\n"
                "[INFO ANT-0001] Found 0 pin violations.\n",
                encoding="utf-8",
            )
            drc.write_text(
                "violation type: Cut Spacing\n\tbbox = (0,0) - (1,1) on Layer hb_layer\n",
                encoding="utf-8",
            )
            for path in (binary, patch, cts, route):
                path.write_bytes(b"x")
            payload = ANALYZER.analyze(
                run_id="fixture",
                manifest_path=manifest,
                log_path=log,
                drc_report_path=drc,
                openroad_path=binary,
                patch_path=patch,
                cts_paths=[cts],
                route_paths=[route, drc],
            )
            self.assertEqual(payload["status"], "failed")
            self.assertFalse(payload["checks"]["route_drc_zero"])
            self.assertTrue(payload["conclusion"]["pin_access_patch_effective"])
            self.assertFalse(payload["conclusion"]["full_smoke_gate_open"])


if __name__ == "__main__":
    unittest.main()
