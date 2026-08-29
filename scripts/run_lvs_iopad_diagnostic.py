#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict deep-LVS diagnosis of SG13G2 IOPad label and net boundaries."""

from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

from run_lvs_pin_boundary_ab import (
    IMAGE_DIGEST,
    IMAGE_REFERENCE,
    PDK_COMMIT,
    build_variant_command,
    explicit_option_state,
    variant_result,
)


IOPAD_PREFIX = "sg13g2_IOPad"
FOCUS_CELL = "sg13g2_IOPadIn"
FOCUS_LABELS = {"iovss", "vss", "iovdd", "vdd", "guard", "sub", "sub!"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_subckt_names(path: Path, prefix: str) -> list[str]:
    names: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            fields = raw.split()
            if len(fields) >= 2 and fields[0].lower() == ".subckt" and fields[1].startswith(prefix):
                names.append(fields[1])
    return sorted(set(names))


def normalized_token(token: str) -> str:
    return token[1:] if token.startswith("\\") else token


def parse_subckt_statements(path: Path, top_cell: str) -> list[str]:
    """Stream one subcircuit body and join only its '+' continuations."""
    statements: list[str] = []
    found = False
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            stripped = raw.strip()
            if not found:
                fields = stripped.split()
                if len(fields) >= 2 and fields[0].lower() == ".subckt" and fields[1].lower() == top_cell.lower():
                    found = True
                continue
            if stripped.lower().startswith(".ends"):
                return statements
            if not stripped or stripped.startswith("*"):
                continue
            if stripped.startswith("+"):
                if statements:
                    statements[-1] += " " + stripped[1:].strip()
                continue
            statements.append(stripped)
    if not found:
        raise ValueError(f".SUBCKT {top_cell} not found in {path}")
    raise ValueError(f".ENDS for {top_cell} not found in {path}")


def statements_referencing(statements: list[str], net: str) -> list[str]:
    matches: list[str] = []
    for statement in statements:
        tokens = [normalized_token(token) for token in statement.split()]
        if net in tokens[1:]:
            matches.append(statement)
    return matches


def collect_gds_labels(gds_path: Path, target_cells: list[str]) -> dict[str, Any]:
    import klayout.db as kdb

    layout = kdb.Layout()
    layout.read(str(gds_path))
    available = {cell.name for cell in layout.each_cell()}
    labels: dict[str, Any] = {}
    for name in target_cells:
        if name not in available:
            continue
        cell = layout.cell(name)
        direct: list[dict[str, Any]] = []
        for layer_index in layout.layer_indices():
            info = layout.get_info(layer_index)
            for shape in cell.shapes(layer_index).each():
                if not shape.is_text():
                    continue
                text = shape.text
                direct.append(
                    {
                        "text": text.string,
                        "layer": info.layer,
                        "datatype": info.datatype,
                        "x_dbu": text.trans.disp.x,
                        "y_dbu": text.trans.disp.y,
                    }
                )
        label_counts = collections.Counter(item["text"] for item in direct)
        labels[name] = {
            "direct_text_count": len(direct),
            "direct_text_counts_by_name": dict(sorted(label_counts.items())),
            "focus_power_guard_labels": [
                item for item in direct if item["text"].lower() in FOCUS_LABELS
            ],
        }
    return labels


def build_focus_detail(
    schematic: Path,
    extracted: Path,
    label_data: dict[str, Any],
) -> dict[str, Any]:
    schematic_statements = parse_subckt_statements(schematic, FOCUS_CELL)
    extracted_statements = parse_subckt_statements(extracted, FOCUS_CELL)
    components = {
        net: statements_referencing(extracted_statements, net)
        for net in ("iovss", "iovss$1", "$1")
    }
    return {
        "cell": FOCUS_CELL,
        "classification": "io_pad_iovss_split_observed_root_cause_not_fully_identified",
        "root_cause_fully_identified": False,
        "schematic_logical_iovss_connections": statements_referencing(
            schematic_statements, "iovss"
        ),
        "schematic_substrate_global_connections": statements_referencing(
            schematic_statements, "sub!"
        ),
        "extracted_distinct_components": components,
        "extracted_logical_iovss_component_count": sum(
            bool(components[net]) for net in ("iovss", "iovss$1")
        ),
        "guard_substrate_device_statements": sorted(
            set(components["$1"])
            | {statement for statement in extracted_statements if "ptap1" in statement.split()}
        ),
        "gds_direct_power_guard_labels": label_data[FOCUS_CELL][
            "focus_power_guard_labels"
        ],
        "interpretation": [
            "The schematic uses one iovss formal net for LevelDown, DCNDiode, DCPDiode and the IOVSS substrate tap.",
            "Deep extraction exposes two distinct formal components, iovss and iovss$1.",
            "The split may reflect library geometry intended to be joined by parent IO-ring routing, label promotion, or substrate/guard connectivity; this run does not choose among them.",
        ],
    }


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    extra_frequency: collections.Counter[str] = collections.Counter()
    split_iovss_cells: list[str] = []
    split_iovdd_cells: list[str] = []
    composite_port_cells: dict[str, list[str]] = {}
    missing_port_cells: dict[str, list[str]] = {}
    affected_cells: set[str] = set()
    pass_cells: list[str] = []
    fail_cells: list[str] = []
    for case in cases:
        top_cell = case["top_cell"]
        if case.get("status") == "PASS":
            pass_cells.append(top_cell)
        elif case.get("status") == "FAIL":
            fail_cells.append(top_cell)
        extras = sorted(
            set(case.get("extracted_port_order", []))
            - set(case.get("schematic_port_order", []))
        )
        case["extra_extracted_formal_ports"] = extras
        extra_frequency.update(extras)
        if any(extra.startswith("iovss$") for extra in extras):
            split_iovss_cells.append(top_cell)
        if any(extra.startswith("iovdd$") for extra in extras):
            split_iovdd_cells.append(top_cell)
        composites = [extra for extra in extras if "|" in extra]
        if composites:
            composite_port_cells[top_cell] = composites
        missing = sorted(
            set(case.get("schematic_port_order", []))
            - set(case.get("extracted_port_order", []))
        )
        if missing:
            missing_port_cells[top_cell] = missing
        if extras or missing:
            affected_cells.add(top_cell)
    return {
        "tested_cell_count": len(cases),
        "strict_lvs_pass_count": len(pass_cells),
        "strict_lvs_fail_count": len(fail_cells),
        "pass_cells": sorted(pass_cells),
        "fail_cells": sorted(fail_cells),
        "cells_with_extra_iovss_component": sorted(split_iovss_cells),
        "cells_with_extra_iovdd_component": sorted(split_iovdd_cells),
        "cells_with_composite_formal_ports": dict(sorted(composite_port_cells.items())),
        "cells_with_missing_schematic_ports": dict(sorted(missing_port_cells.items())),
        "extra_formal_port_frequency": dict(extra_frequency.most_common()),
        "single_cell_data_problem_supported": len(affected_cells) == 1,
        "repeated_across_iopad_library": len(affected_cells) > 1,
        "root_cause_fully_identified": False,
        "full_chip_135057_port_mismatch_attributed_to_io_only": False,
        "full_chip_attempt_3_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--summarize-existing", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    run_dir = args.run_dir.resolve()
    summary_path = run_dir / "summary.json"
    if args.summarize_existing:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["library_summary"] = summarize_cases(summary["cases"])
        summary["classification"] = "complete_root_cause_not_fully_identified"
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)
        print(summary_path)
        return 0

    pdk = repo / "upstream/ihp-open-pdk/ihp-sg13g2"
    gds = pdk / "libs.ref/sg13g2_io/gds/sg13g2_io.gds"
    cdl = pdk / "libs.ref/sg13g2_io/cdl/sg13g2_io.cdl"
    runner = pdk / "libs.tech/klayout/tech/lvs/run_lvs.py"
    target_cells = parse_subckt_names(cdl, IOPAD_PREFIX)
    label_data = collect_gds_labels(gds, target_cells)
    target_cells = [name for name in target_cells if name in label_data]
    if FOCUS_CELL not in target_cells:
        raise ValueError(f"focus cell {FOCUS_CELL} is missing from GDS/CDL intersection")

    run_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "classification": "in_progress",
        "purpose": "strict_deep_lvs_iopad_iovss_boundary_diagnosis",
        "container_reference": IMAGE_REFERENCE,
        "container_digest": IMAGE_DIGEST,
        "ihp_pdk_commit": PDK_COMMIT,
        "strictness": explicit_option_state("deep", False),
        "target_cells": target_cells,
        "gds_direct_label_inventory": label_data,
        "cases": [],
    }
    write_json(summary_path, summary)

    for cell_name in target_cells:
        case_dir = run_dir / cell_name
        case_dir.mkdir(parents=True, exist_ok=True)
        command = build_variant_command(
            sys.executable,
            runner,
            gds,
            cdl,
            case_dir,
            "deep",
            False,
            top_cell=cell_name,
        )
        (case_dir / "command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
        with (case_dir / "runner-console.log").open("w", encoding="utf-8") as log_stream:
            completed = subprocess.run(
                command,
                cwd=repo,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        extracted = case_dir / "sg13g2_io_extracted.cir"
        layout_log = case_dir / "sg13g2_io.log"
        result = variant_result(
            cell_name,
            "deep",
            False,
            command,
            completed.returncode,
            cdl,
            extracted,
            layout_log,
            top_cell=cell_name,
        )
        result["top_cell"] = cell_name
        result["artifacts"] = {
            "command": str((case_dir / "command.txt").relative_to(run_dir)),
            "runner_console_log": str((case_dir / "runner-console.log").relative_to(run_dir)),
            "layout_log": str(layout_log.relative_to(run_dir)) if layout_log.exists() else None,
            "extracted_netlist": str(extracted.relative_to(run_dir)) if extracted.exists() else None,
            "lvsdb": str((case_dir / "sg13g2_io.lvsdb").relative_to(run_dir))
            if (case_dir / "sg13g2_io.lvsdb").exists()
            else None,
        }
        summary["cases"].append(result)
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)

    focus_case = next(case for case in summary["cases"] if case["top_cell"] == FOCUS_CELL)
    focus_extracted = run_dir / focus_case["artifacts"]["extracted_netlist"]
    focus_detail = build_focus_detail(cdl, focus_extracted, label_data)
    write_json(run_dir / "iopad_in_detail.json", focus_detail)
    summary["library_summary"] = summarize_cases(summary["cases"])
    summary["focus_detail"] = "iopad_in_detail.json"
    summary["classification"] = "complete_root_cause_not_fully_identified"
    summary["generated_at"] = utc_now()
    write_json(summary_path, summary)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
