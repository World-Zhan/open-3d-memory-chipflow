# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_pin3d_hbt_spacing", ROOT / "scripts" / "analyze_pin3d_hbt_spacing.py"
)
assert SPEC is not None and SPEC.loader is not None
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


class Pin3dHbtSpacingTests(unittest.TestCase):
    def test_rectangle_edge_gap_uses_cut_edges_not_center_only(self):
        first = {"x_um": 0.0, "y_um": 0.0}
        second = {"x_um": 1.0, "y_um": 1.0}
        self.assertAlmostEqual(
            ANALYZER.rectangle_edge_gap_um(first, second, 0.032, 0.032),
            (2 * (1.0 - 0.032) ** 2) ** 0.5,
        )

    def test_existing_geometry_exactly_reproduces_cut_pair_and_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            base = Path(tmp)
            lef = base / "tech.lef"
            route = base / "route.def"
            drc = base / "route_drc.rpt"
            partition = base / "partition.log"
            lef.write_text(
                """LAYER hb_layer
  TYPE CUT ;
  SPACING 1.568 ;
  WIDTH 0.032 ;
END hb_layer
VIA hb_layer_0 DEFAULT
  LAYER M7 ; RECT -0.016 -0.027 0.016 0.027 ;
  LAYER hb_layer ; RECT -0.016 -0.016 0.016 0.016 ;
  LAYER M6_m ; RECT -0.027 -0.016 0.027 0.016 ;
END hb_layer_0
""",
                encoding="utf-8",
            )
            route.write_text(
                """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 4000 4000 ) ;
TRACKS X 16 DO 64 STEP 64 LAYER M7 ;
TRACKS Y 16 DO 64 STEP 64 LAYER M7 ;
NETS 3 ;
- net_a
  + ROUTED M7 ( 16 16 ) hb_layer_0
;
- net_b
  + ROUTED M7 ( 80 16 ) hb_layer_0
;
- net_c
  + ROUTED M7 ( 2000 2000 ) hb_layer_0
;
END NETS
END DESIGN
""",
                encoding="utf-8",
            )
            drc.write_text(
                """violation type: Cut Spacing
\tsrcs: net:net_a net:net_b
\tbbox = (0.0000, 0.0000) - (0.0960, 0.0320) on Layer hb_layer
violation type: Short
\tsrcs: net:net_a net:net_b
\tbbox = (0.0000, 0.0000) - (0.0100, 0.0100) on Layer M1_m
""",
                encoding="utf-8",
            )
            partition.write_text(
                """INFO: HB layer=hb_layer width=0.500um spacing=0.500um (pitch=1.000um) density=0.500 cuts_per_net=1 tol=0
INFO: STAT cut=2 target=1 tol=0 feasible=0
INFO: FINAL mode=UB_SWEEP best_tag=fixture cut=2 feasible=0 -> partition.txt
""",
                encoding="utf-8",
            )
            payload = ANALYZER.analyze(
                run_id="fixture",
                tech_lef_path=lef,
                route_def_path=route,
                drc_report_path=drc,
                partition_log_path=partition,
                root=base,
            )
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["route_geometry"]["hbt_via_count"], 3)
            self.assertEqual(payload["drc"]["cut_spacing_markers"], 1)
            self.assertEqual(payload["drc"]["predicted_cut_spacing_pairs"], 1)
            self.assertTrue(payload["checks"]["predicted_pairs_exactly_match_drc"])
            self.assertTrue(payload["conclusion"]["hb_cut_spacing_root_cause_proven"])
            self.assertFalse(payload["checks"]["partition_hbt_rule_matches_tech_lef"])
            self.assertFalse(payload["checks"]["partition_selected_feasible"])
            self.assertFalse(payload["conclusion"]["all_route_drc_root_causes_proven"])
            self.assertFalse(payload["conclusion"]["full_smoke_gate_open"])


if __name__ == "__main__":
    unittest.main()
