# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "small_lvsdb", ROOT / "scripts/analyze_small_lvsdb.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeNamed:
    def __init__(self, name: str):
        self.name = name


class FakePair:
    def __init__(self, status: str, first=None, second=None):
        self._status = status
        self._first = first
        self._second = second

    def status(self):
        return self._status

    def first(self):
        return self._first

    def second(self):
        return self._second


class SmallLvsdbAnalysisTests(unittest.TestCase):
    def test_size_guard_refuses_large_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.lvsdb"
            path.write_bytes(b"12345")
            self.assertEqual(MODULE.enforce_size_limit(path, 5), 5)
            with self.assertRaisesRegex(ValueError, "refusing to load"):
                MODULE.enforce_size_limit(path, 4)

    def test_object_pair_summary_is_bounded(self) -> None:
        pairs = [
            FakePair("Match", FakeNamed("a"), FakeNamed("a")),
            FakePair("NoMatch", FakeNamed("b"), None),
            FakePair("Mismatch", None, FakeNamed("c")),
        ]
        result = MODULE.summarize_object_pairs(pairs, sample_limit=1)
        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(
            result["classification_counts"],
            {"layout_only": 1, "match": 1, "schematic_only": 1},
        )
        self.assertEqual(result["nonmatch_count"], 2)
        self.assertEqual(result["status_counts"], {"Match": 1, "Mismatch": 1, "NoMatch": 1})
        self.assertEqual(len(result["nonmatch_samples"]), 1)
        self.assertTrue(result["samples_truncated"])

    def test_pair_classification_distinguishes_paired_mismatch(self) -> None:
        result = MODULE.summarize_object_pairs(
            [
                FakePair("Mismatch", FakeNamed("layout"), FakeNamed("schematic")),
                FakePair("Mismatch", FakeNamed("layout-only"), None),
                FakePair("Mismatch", None, FakeNamed("schematic-only")),
            ],
            sample_limit=10,
        )
        self.assertEqual(
            result["classification_counts"],
            {"layout_only": 1, "paired_mismatch": 1, "schematic_only": 1},
        )
        self.assertEqual(
            [item["classification"] for item in result["nonmatch_samples"]],
            ["paired_mismatch", "layout_only", "schematic_only"],
        )

    def test_summary_identifies_leaf_pairing_blocker(self) -> None:
        empty = {
            "status_counts": {},
            "classification_counts": {},
            "pair_count": 0,
            "nonmatch_count": 0,
        }
        no_match = {
            "layout_circuit": "leaf",
            "schematic_circuit": "LEAF",
            "status": "NoMatch",
            "pin": empty,
            "net": empty,
            "device": {
                **empty,
                "status_counts": {"Mismatch": 2},
                "classification_counts": {"layout_only": 1, "schematic_only": 1},
            },
            "subcircuit": empty,
        }
        skipped = {
            "layout_circuit": "top",
            "schematic_circuit": "TOP",
            "status": "Skipped",
            "pin": empty,
            "net": empty,
            "device": empty,
            "subcircuit": empty,
        }
        result = MODULE.build_summary([skipped, no_match])
        self.assertEqual(result["circuit_status_counts"], {"NoMatch": 1, "Skipped": 1})
        self.assertEqual(result["no_match_layout_circuits"], ["leaf"])
        self.assertTrue(result["comparison_blocked_at_leaf_circuit_pairing"])
        self.assertEqual(result["parameter_comparison"], "partly_blocked_by_unpaired_devices")
        self.assertEqual(
            result["object_pair_classification_counts"]["device"],
            {"layout_only": 1, "schematic_only": 1},
        )

    def test_parameter_classification_handles_paired_device_mismatch(self) -> None:
        empty = {"status_counts": {}, "classification_counts": {}}
        record = {kind: dict(empty) for kind in MODULE.KINDS}
        record.update({"layout_circuit": "a", "schematic_circuit": "A", "status": "NoMatch"})
        record["device"] = {"status_counts": {"Mismatch": 1}, "classification_counts": {"paired_mismatch": 1}}
        result = MODULE.build_summary([record])
        self.assertEqual(result["parameter_comparison"], "paired_device_mismatches_require_review")

    def test_default_limit_is_far_below_full_chip_database(self) -> None:
        self.assertEqual(MODULE.DEFAULT_MAX_BYTES, 64 * 1024 * 1024)
        self.assertLess(MODULE.DEFAULT_MAX_BYTES, 609_009_139)


if __name__ == "__main__":
    unittest.main()
