#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded KLayout LVSDB cross-reference analyzer for small diagnostic cases.

This tool deliberately refuses databases larger than 64 MiB by default.  It is
not a replacement for the streaming full-chip analyzer and must not be used on
the 609 MB Croc attempt-2 LVSDB.
"""

from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_MAX_BYTES = 64 * 1024 * 1024
KINDS = ("pin", "net", "device", "subcircuit")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def enforce_size_limit(path: Path, max_bytes: int) -> int:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"refusing to load {size} byte LVSDB; configured limit is {max_bytes} bytes"
        )
    return size


def _read_member(obj: Any, name: str) -> Any:
    value = getattr(obj, name, None)
    if callable(value):
        try:
            return value()
        except TypeError:
            return None
    return value


def object_description(obj: Any) -> dict[str, Any] | None:
    if obj is None:
        return None
    description: dict[str, Any] = {"type": type(obj).__name__}
    for member in ("expanded_name", "qname", "name", "id"):
        value = _read_member(obj, member)
        if value not in (None, ""):
            description[member] = str(value)
    device_class = _read_member(obj, "device_class")
    if device_class is not None:
        class_name = _read_member(device_class, "name")
        if class_name not in (None, ""):
            description["device_class"] = str(class_name)
    return description


def pair_record(pair: Any) -> dict[str, Any]:
    status = str(pair.status())
    layout = object_description(pair.first())
    schematic = object_description(pair.second())
    if status == "Match":
        classification = "match"
    elif layout is not None and schematic is None:
        classification = "layout_only"
    elif layout is None and schematic is not None:
        classification = "schematic_only"
    elif layout is not None and schematic is not None:
        classification = "paired_mismatch"
    else:
        classification = "unresolved_without_objects"
    return {
        "status": status,
        "classification": classification,
        "layout": layout,
        "schematic": schematic,
    }


def summarize_object_pairs(
    pairs: Iterable[Any], sample_limit: int
) -> dict[str, Any]:
    records = [pair_record(pair) for pair in pairs]
    counts = collections.Counter(record["status"] for record in records)
    classifications = collections.Counter(
        record["classification"] for record in records
    )
    mismatches = [record for record in records if record["status"] != "Match"]
    return {
        "pair_count": len(records),
        "status_counts": dict(sorted(counts.items())),
        "classification_counts": dict(sorted(classifications.items())),
        "nonmatch_count": len(mismatches),
        "nonmatch_samples": mismatches[:sample_limit],
        "samples_truncated": len(mismatches) > sample_limit,
    }


def build_summary(circuit_records: list[dict[str, Any]]) -> dict[str, Any]:
    circuit_counts = collections.Counter(record["status"] for record in circuit_records)
    object_counts: dict[str, collections.Counter[str]] = {
        kind: collections.Counter() for kind in KINDS
    }
    object_classifications: dict[str, collections.Counter[str]] = {
        kind: collections.Counter() for kind in KINDS
    }
    for circuit in circuit_records:
        for kind in KINDS:
            object_counts[kind].update(circuit[kind]["status_counts"])
            object_classifications[kind].update(
                circuit[kind].get("classification_counts", {})
            )
    no_match = [
        record["layout_circuit"]
        for record in circuit_records
        if record["status"] == "NoMatch"
    ]
    skipped = [
        record["layout_circuit"]
        for record in circuit_records
        if record["status"] == "Skipped"
    ]
    device_classifications = object_classifications["device"]
    if (
        device_classifications.get("layout_only", 0)
        or device_classifications.get("schematic_only", 0)
    ):
        parameter_comparison = "partly_blocked_by_unpaired_devices"
    elif device_classifications.get("paired_mismatch", 0):
        parameter_comparison = "paired_device_mismatches_require_review"
    else:
        parameter_comparison = "no_device_pairing_blocker_observed"
    return {
        "circuit_pair_count": len(circuit_records),
        "circuit_status_counts": dict(sorted(circuit_counts.items())),
        "no_match_layout_circuits": no_match,
        "skipped_layout_circuits": skipped,
        "object_pair_status_counts": {
            kind: dict(sorted(counts.items())) for kind, counts in object_counts.items()
        },
        "object_pair_classification_counts": {
            kind: dict(sorted(counts.items()))
            for kind, counts in object_classifications.items()
        },
        "comparison_blocked_at_leaf_circuit_pairing": bool(no_match),
        "parameter_comparison": parameter_comparison,
        "classification_semantics": {
            "layout_only": "layout object present, schematic object absent",
            "schematic_only": "schematic object present, layout object absent",
            "paired_mismatch": "both objects present but KLayout did not mark the pair Match",
            "match": "KLayout marked the object pair Match",
        },
    }


def analyze(path: Path, sample_limit: int) -> dict[str, Any]:
    import pya

    database = pya.LayoutVsSchematic()
    database.read(str(path))
    xref = database.xref()
    iterator_by_kind: dict[str, Callable[[Any], Iterable[Any]]] = {
        "pin": xref.each_pin_pair,
        "net": xref.each_net_pair,
        "device": xref.each_device_pair,
        "subcircuit": xref.each_subcircuit_pair,
    }
    circuit_records: list[dict[str, Any]] = []
    for pair in xref.each_circuit_pair():
        layout_circuit = pair.first()
        schematic_circuit = pair.second()
        anchor = layout_circuit if layout_circuit is not None else schematic_circuit
        record: dict[str, Any] = {
            "layout_circuit": _read_member(layout_circuit, "name")
            if layout_circuit is not None
            else None,
            "schematic_circuit": _read_member(schematic_circuit, "name")
            if schematic_circuit is not None
            else None,
            "status": str(pair.status()),
        }
        for kind, iterator in iterator_by_kind.items():
            record[kind] = summarize_object_pairs(iterator(anchor), sample_limit)
        circuit_records.append(record)

    return {
        "circuit_pairs": circuit_records,
        "summary": build_summary(circuit_records),
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lvsdb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--sample-limit", type=int, default=50)
    args = parser.parse_args()

    path = args.lvsdb.resolve()
    size = enforce_size_limit(path, args.max_bytes)
    result = analyze(path, args.sample_limit)
    report = {
        "schema_version": "1.1.0",
        "generated_at": utc_now(),
        "analysis_mode": "bounded_klayout_layout_vs_schematic_cross_reference",
        "source_lvsdb": str(path),
        "source_bytes": size,
        "source_sha256": sha256_file(path),
        "configured_max_bytes": args.max_bytes,
        "sample_limit_per_object_kind_per_circuit": args.sample_limit,
        "full_chip_lvsdb_loading_forbidden": True,
        **result,
    }
    write_json(args.output.resolve(), report)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
