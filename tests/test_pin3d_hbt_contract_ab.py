# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "collect_pin3d_hbt_contract_ab",
    ROOT / "scripts" / "collect_pin3d_hbt_contract_ab.py",
)
assert SPEC is not None and SPEC.loader is not None
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


class Pin3dHbtContractAbTests(unittest.TestCase):
    def test_flat_tcl_contract_is_typed(self):
        raw = COLLECTOR.parse_flat_tcl_dict(
            "layer hb_layer estimated_hbt_demand 62 capacity_utilization 0.8 capacity_validated 1"
        )
        typed = COLLECTOR.numeric_contract(raw)
        self.assertEqual(typed["layer"], "hb_layer")
        self.assertEqual(typed["estimated_hbt_demand"], 62)
        self.assertEqual(typed["capacity_utilization"], 0.8)
        self.assertEqual(typed["capacity_validated"], 1)

    def test_actual_core_bbox_not_requested_size_is_parsed(self):
        bbox = COLLECTOR.parse_core_bbox(
            "[INFO IFP-0101] Core BBox: (  0.216  0.270 ) ( 14.796 14.580 ) um\n"
        )
        self.assertAlmostEqual(bbox["width_um"], 14.58)
        self.assertAlmostEqual(bbox["height_um"], 14.31)
        self.assertAlmostEqual(bbox["area_um2"], 208.6398)

    def test_site_guarded_core_has_ninety_legal_sites(self):
        capacity = COLLECTOR.discrete_capacity(14.58, 14.31, 0.032, 1.568)
        self.assertEqual(capacity, {"sites_x": 10, "sites_y": 9, "total_sites": 90})


if __name__ == "__main__":
    unittest.main()
