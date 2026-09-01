# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/openroad/0001-top-routing-layer-standard-cell-down-via.patch"
BUILD = ROOT / "scripts/build_pin3d_openroad_patch.sh"
FLOW = ROOT / "scripts/pin3d_flow.sh"


class Pin3dOpenroadPatchTests(unittest.TestCase):
    def test_patch_is_narrow_and_preserves_pin_access(self):
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("FlexPA_acc_point.cpp", text)
        self.assertIn("router_cfg_->TOP_ROUTING_LAYER", text)
        self.assertIn("collect_vias(layer_num - 1", text)
        self.assertNotIn("min_access_points", text)
        self.assertNotIn("-no_pin_access", text)

    def test_build_wrapper_restores_pinned_source(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn("apply --check", text)
        self.assertIn("apply --reverse", text)
        self.assertIn("--parallel \"${NUM_CORES:-6}\"", text)
        self.assertNotIn("reset --hard", text)
        self.assertNotIn("clean -fd", text)

    def test_flow_forbids_pin_access_bypass(self):
        text = FLOW.read_text(encoding="utf-8")
        self.assertIn("DETAILED_ROUTE_ARGS", text)
        self.assertIn("-no_pin_access is forbidden", text)
        default_line = next(line for line in text.splitlines() if line.startswith("export DETAILED_ROUTE_ARGS="))
        self.assertNotIn("-no_pin_access", default_line)


if __name__ == "__main__":
    unittest.main()
