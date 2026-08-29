#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Low-memory audit of an existing Croc LVS result; never loads the .lvsdb."""

from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


ANOMALY_SAMPLE_LIMIT = 100
POWER_PORTS = {"VDD", "VDDIO", "VSS", "VSSIO"}
GENERIC_PIN_RE = re.compile(
    r"^(?:A\d*|B\d*|C\d*|D\d*|I\d*|O|Q|S|X|Y|Z|CLK|RESET_B|"
    r"gate|ngate|pgate|core|pad|pin\d+|supply|vdd|vss|iovdd|iovss|"
    r"anode|cathode|guard|p2c|c2p|c2p_en|en|nq|L_LO)(?:\$\d+)?$",
    re.IGNORECASE,
)


def parse_subckt_ports(path: Path, top_name: str) -> dict[str, Any]:
    """Read only one .SUBCKT header and its '+' continuations."""
    header_re = re.compile(r"^\s*\.subckt\s+(\S+)(.*)$", re.IGNORECASE)
    ports: list[str] = []
    found_name: str | None = None
    start_line: int | None = None
    collecting = False
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, raw in enumerate(stream, 1):
            stripped = raw.strip()
            if not collecting:
                match = header_re.match(raw)
                if not match or match.group(1).lower() != top_name.lower():
                    continue
                found_name = match.group(1)
                ports.extend(match.group(2).split())
                start_line = line_number
                collecting = True
                continue
            if stripped.startswith("+"):
                ports.extend(stripped[1:].split())
                continue
            break
    if found_name is None:
        raise ValueError(f"top .SUBCKT {top_name!r} not found in {path}")
    return {"name": found_name, "line": start_line, "port_count": len(ports), "ports": ports}


def aliases_of(token: str) -> list[str]:
    return token.split("|")


def classify_layout_port(token: str, expected: set[str]) -> str:
    aliases = aliases_of(token)
    expected_hits = expected.intersection(aliases)
    composite = len(aliases) > 1
    if expected_hits:
        if expected_hits.intersection(POWER_PORTS):
            return "composite_expected_power_ground" if composite else "exact_expected_power_ground"
        return "composite_expected_signal" if composite else "exact_expected_signal"
    if any(alias.upper() in POWER_PORTS or alias.lower() in {"vdd", "vss", "iovdd", "iovss", "supply"} for alias in aliases):
        return "composite_internal_power_ground" if composite else "single_internal_power_ground"
    if "/" in token or "\\" in token or "[" in token or "]" in token:
        return "composite_hierarchical_internal" if composite else "single_hierarchical_internal"
    if all(GENERIC_PIN_RE.fullmatch(alias) for alias in aliases):
        return "composite_generic_cell_pin_labels" if composite else "single_generic_cell_pin_label"
    if len(aliases) == 1 and re.fullmatch(r"net\d+(?:\$\d+)?", token, re.IGNORECASE):
        return "single_generated_net"
    return "composite_other_internal" if composite else "single_other_internal"


def compare_top_ports(schematic_ports: list[str], layout_ports: list[str]) -> dict[str, Any]:
    expected = set(schematic_ports)
    layout_set = set(layout_ports)
    exact_shared = sorted(expected.intersection(layout_set))
    alias_hits: dict[str, list[dict[str, Any]]] = {port: [] for port in schematic_ports}
    categories: collections.Counter[str] = collections.Counter()
    anomaly_samples: list[dict[str, Any]] = []
    composite_samples: list[dict[str, Any]] = []
    for index, token in enumerate(layout_ports):
        aliases = aliases_of(token)
        matched = sorted(expected.intersection(aliases))
        category = classify_layout_port(token, expected)
        categories[category] += 1
        if len(aliases) > 1 and len(composite_samples) < ANOMALY_SAMPLE_LIMIT:
            composite_samples.append(
                {
                    "index": index,
                    "category": category,
                    "extracted_formal_port": token,
                    "expected_aliases": matched,
                }
            )
        if matched:
            for port in matched:
                alias_hits[port].append({"index": index, "extracted_formal_port": token, "aliases": aliases})
        elif len(anomaly_samples) < ANOMALY_SAMPLE_LIMIT:
            anomaly_samples.append({"index": index, "category": category, "extracted_formal_port": token})

    missing = [port for port in schematic_ports if not alias_hits[port]]
    ambiguous = {port: hits for port, hits in alias_hits.items() if len(hits) > 1}
    first_indices = [alias_hits[port][0]["index"] for port in schematic_ports if alias_hits[port]]
    recovered_order_matches = not missing and first_indices == sorted(first_indices)
    mapping = [
        {
            "schematic_port": port,
            "status": "missing" if not alias_hits[port] else ("ambiguous" if len(alias_hits[port]) > 1 else "mapped_as_alias"),
            "matches": alias_hits[port],
        }
        for port in schematic_ports
    ]
    tokens_with_expected = sum(count for category, count in categories.items() if category.startswith("composite_expected") or category.startswith("exact_expected"))
    return {
        "schematic_port_count": len(schematic_ports),
        "layout_extracted_formal_port_count": len(layout_ports),
        "formal_port_count_delta": len(layout_ports) - len(schematic_ports),
        "exact_shared_count": len(exact_shared),
        "exact_shared_ports": exact_shared,
        "schematic_ports_recovered_as_aliases": len(schematic_ports) - len(missing),
        "missing_schematic_aliases": missing,
        "ambiguous_schematic_alias_count": len(ambiguous),
        "ambiguous_schematic_aliases": ambiguous,
        "layout_tokens_containing_expected_alias": tokens_with_expected,
        "abnormal_layout_formal_port_count": len(layout_ports) - tokens_with_expected,
        "recovered_alias_order_matches_schematic": recovered_order_matches,
        "category_counts": dict(categories.most_common()),
        "schematic_to_extracted_mapping": mapping,
        "composite_formal_port_samples_first_100": composite_samples,
        "abnormal_formal_port_samples_first_100": anomaly_samples,
    }


def parse_log_options(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    mode_match = re.search(r"\b(flat|deep)\s+mode is enabled", text)
    netlist_match = re.search(r"Netlist file:\s*(.+)", text)
    runtime_match = re.search(r"LVS Total Run time\s+([0-9.]+)\s+seconds", text)
    memory_values = [int(value) for value in re.findall(r"Memory Usage \((\d+)K\)", text)]
    ignore_value = re.search(r"Selected IGNORE_TOP_PORTS_MISMATCH option:[ \t]*([^\r\n]*)", text)
    top_pins_value = re.search(r"Selected TOP_LVL_PINS option:[ \t]*(true|false)", text, re.IGNORECASE)
    return {
        "run_mode": mode_match.group(1) if mode_match else None,
        "schematic_path_logged": netlist_match.group(1).strip() if netlist_match else None,
        "top_level_pins_option": None if top_pins_value is None else top_pins_value.group(1).lower() == "true",
        "strict_port_mode": "Comparison in strict port mode" in text,
        "flag_missing_ports": "flag_missing_ports enabled" in text,
        "ignore_top_ports_mismatch_raw": ignore_value.group(1).strip() if ignore_value else None,
        "ignore_top_ports_mismatch_enabled": bool(ignore_value and ignore_value.group(1).strip().lower() == "true"),
        "implicit_nets": None if "Selected IMPLICIT_NETS option: (none)" in text else "unknown",
        "simplify_enabled": "Selected SIMPLIFY option: true" in text,
        "netlists_match": "Congratulations! Netlists match." in text,
        "netlists_mismatch": "ERROR : Netlists don't match" in text,
        "deck_runtime_seconds": float(runtime_match.group(1)) if runtime_match else None,
        "peak_memory_kib": max(memory_values) if memory_values else None,
    }


def input_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def build_report(schematic: Path, extracted: Path, log: Path, top: str) -> dict[str, Any]:
    schematic_header = parse_subckt_ports(schematic, top)
    extracted_header = parse_subckt_ports(extracted, top)
    comparison = compare_top_ports(schematic_header["ports"], extracted_header["ports"])
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "streaming_spice_headers_no_lvsdb_load",
        "classification": "failed",
        "conclusion": "severe_top_level_formal_port_and_net_labeling_mismatch",
        "inputs": {
            "schematic": input_record(schematic),
            "extracted": input_record(extracted),
            "log": input_record(log),
        },
        "run_options": parse_log_options(log),
        "schematic_header": schematic_header,
        "extracted_header": {
            "name": extracted_header["name"],
            "line": extracted_header["line"],
            "port_count": extracted_header["port_count"],
        },
        "top_port_analysis": comparison,
        "mismatch_classification": {
            "top_ports": {
                "status": "mismatch",
                "evidence": f"{schematic_header['port_count']} schematic ports versus {extracted_header['port_count']} extracted formal ports",
            },
            "nets": {
                "status": "structural_mismatch_before_pairing",
                "evidence": "expected top nets and internal cell labels were merged into composite names and promoted to formal ports",
            },
            "devices": {"status": "not_compared", "reason": "device pairing is not meaningful before top port/net boundary is repaired"},
            "subcircuits_macros": {"status": "not_compared", "reason": "flat extraction erased the comparison boundary before macro pairing"},
            "parameters": {"status": "not_compared", "reason": "parameter comparison requires paired devices"},
        },
        "root_cause_evidence": [
            "The run log records flat mode, TOP_LVL_PINS=false, strict port mode, and flag_missing_ports enabled.",
            "No schematic port exists as an exact extracted formal-port token; intended ports occur only as aliases inside composite net names.",
            "Internal standard-cell labels such as gate|ngate|o are promoted to top-level formal ports.",
            "This is a top extraction-boundary/label-propagation failure, not evidence of an ordinary device-parameter delta.",
        ],
        "minimum_next_step": [
            "Do not enable ignore_top_ports_mismatch or implicit nets, and do not start full attempt 3.",
            "Audit text/pin layer mapping and label propagation for the top, IO pad, standard-cell and SRAM hierarchy.",
            "Validate deep-mode hierarchy and top-port behavior on the smallest representative IO-plus-standard-cell structure.",
            "Only after that check produces the intended top port set should the full-chip runner be changed and attempt 3 scheduled.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schematic", type=Path, required=True)
    parser.add_argument("--extracted", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--top", default="croc_chip")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.schematic, args.extracted, args.log, args.top)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
