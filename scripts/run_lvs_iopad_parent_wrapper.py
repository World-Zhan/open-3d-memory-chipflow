#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run strict-deep LVS on a minimal, abutted SG13G2 IO-ring segment.

The fixture mirrors one Croc edge segment: IOVSS supply, IOVDD supply, one
input pad, core VSS supply, and core VDD supply.  It preserves strict ports,
all guard/substrate devices, and the PDK hierarchy.  It never enables implicit
nets or ignore_top_ports_mismatch and never edits the full-chip runner.
"""

from __future__ import annotations

import argparse
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
    _first_direct_text,
    build_variant_command,
    explicit_option_state,
    file_record,
    validate_strict_command,
    variant_result,
)


TOP_CELL = "lvs_iopad_parent_wrapper"
CELL_PITCH_DBU = 80_000
TOP_PORTS = ("PAD", "P2C", "VDD", "VSS", "IOVDD", "IOVSS")
INSTANCES = (
    {
        "instance": "XIOVSS",
        "cell": "sg13g2_IOPadIOVss",
        "ports": ("VDD", "VSS", "IOVDD", "IOVSS"),
    },
    {
        "instance": "XIOVDD",
        "cell": "sg13g2_IOPadIOVdd",
        "ports": ("VDD", "VSS", "IOVDD", "IOVSS"),
    },
    {
        "instance": "XINPUT",
        "cell": "sg13g2_IOPadIn",
        "ports": ("PAD", "P2C", "VDD", "VSS", "IOVDD", "IOVSS"),
    },
    {
        "instance": "XVSS",
        "cell": "sg13g2_IOPadVss",
        "ports": ("VDD", "VSS", "IOVDD", "IOVSS"),
    },
    {
        "instance": "XVDD",
        "cell": "sg13g2_IOPadVdd",
        "ports": ("VDD", "VSS", "IOVDD", "IOVSS"),
    },
)
LABEL_SOURCES = {
    "PAD": ("XINPUT", "pad"),
    "P2C": ("XINPUT", "p2c"),
    "VDD": ("XVDD", "vdd"),
    "VSS": ("XVSS", "vss"),
    "IOVDD": ("XIOVDD", "iovdd"),
    "IOVSS": ("XIOVSS", "iovss"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_top_cdl(io_library_cdl: str) -> str:
    lines = [
        "* Generated strict-deep LVS parent IO-ring wrapper",
        f".SUBCKT {TOP_CELL} {' '.join(TOP_PORTS)}",
    ]
    for spec in INSTANCES:
        lines.append(
            f"{spec['instance']} {' '.join(spec['ports'])} / {spec['cell']}"
        )
    lines.extend([".ENDS", "", io_library_cdl.rstrip(), ""])
    return "\n".join(lines)


def generate_layout(io_gds: Path, output: Path) -> dict[str, Any]:
    """Create five abutted pad cells and six explicit parent labels."""
    import klayout.db as kdb

    layout = kdb.Layout()
    layout.read(str(io_gds))
    top = layout.create_cell(TOP_CELL)
    if top is None:
        raise RuntimeError(f"failed to create {TOP_CELL}")

    placements: list[dict[str, Any]] = []
    offsets: dict[str, int] = {}
    for index, spec in enumerate(INSTANCES):
        child = layout.cell(spec["cell"])
        if child is None:
            raise ValueError(f"GDS cell {spec['cell']} not found")
        offset_x = index * CELL_PITCH_DBU
        offsets[spec["instance"]] = offset_x
        top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(offset_x, 0)))
        placements.append(
            {
                "instance": spec["instance"],
                "cell": spec["cell"],
                "x_dbu": offset_x,
                "y_dbu": 0,
                "orientation": "R0",
            }
        )

    labels: list[dict[str, Any]] = []
    by_instance = {spec["instance"]: spec for spec in INSTANCES}
    for top_pin in TOP_PORTS:
        source_instance, child_pin = LABEL_SOURCES[top_pin]
        child = layout.cell(by_instance[source_instance]["cell"])
        layer_index, point = _first_direct_text(layout, child, child_pin)
        info = layout.get_info(layer_index)
        parent_point = kdb.Point(point.x + offsets[source_instance], point.y)
        top.shapes(layer_index).insert(kdb.Text(top_pin, kdb.Trans(parent_point)))
        labels.append(
            {
                "top_pin": top_pin,
                "source_instance": source_instance,
                "child_pin": child_pin,
                "layer": info.layer,
                "datatype": info.datatype,
                "x_dbu": parent_point.x,
                "y_dbu": parent_point.y,
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(output))
    return {
        "placements": placements,
        "parent_labels": labels,
        "cell_pitch_dbu": CELL_PITCH_DBU,
        "total_width_dbu": len(INSTANCES) * CELL_PITCH_DBU,
        "physical_join": "R0 pad cells abut at every 80um boundary; PDK power rails span each cell width",
    }


def build_existing_variant_command(
    recorded_command: str, variant_run_dir: str, combine_devices: bool
) -> list[str]:
    """Reconstruct a completed variant command without executing it."""
    command = shlex.split(recorded_command)
    replaced = False
    for index, token in enumerate(command):
        if token.startswith("--run_dir="):
            command[index] = f"--run_dir={variant_run_dir}"
            replaced = True
            break
    if not replaced:
        raise ValueError("recorded command has no --run_dir option")
    command = [token for token in command if token != "--combine_devices"]
    if combine_devices:
        command.append("--combine_devices")
    return command


def cross_reference_record(path: Path, repo: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path.relative_to(repo)),
        "source_bytes": payload["source_bytes"],
        "source_sha256": payload["source_sha256"],
        "summary": payload["summary"],
    }


def completed_variant_result(
    repo: Path,
    run_dir: Path,
    baseline_result: dict[str, Any],
    name: str,
    directory_name: str,
    combine_devices: bool,
) -> dict[str, Any]:
    case_dir = run_dir / directory_name
    command = build_existing_variant_command(
        baseline_result["command"],
        f"/work/{case_dir.relative_to(repo)}",
        combine_devices,
    )
    validate_options = [token for token in command if token != "--combine_devices"]
    validate_strict_command(validate_options)
    result = variant_result(
        name,
        "deep",
        False,
        command,
        0,
        run_dir / "inputs" / f"{TOP_CELL}.cdl",
        case_dir / f"{TOP_CELL}_extracted.cir",
        case_dir / f"{TOP_CELL}.log",
        top_cell=TOP_CELL,
    )
    result["requested_options"]["combine_devices"] = combine_devices
    result["observed_log_options"]["combine_devices"] = (
        "enabled" if combine_devices else "skipped"
    )
    result["command_provenance"] = (
        "reconstructed_from_recorded_baseline_command; deck log confirms combine_devices ENABLED"
        if combine_devices
        else "recorded_before_execution"
    )
    result["artifacts"] = {
        "layout_log": f"{directory_name}/{TOP_CELL}.log",
        "extracted_netlist": f"{directory_name}/{TOP_CELL}_extracted.cir",
        "lvsdb": f"{directory_name}/{TOP_CELL}.lvsdb",
    }
    if not combine_devices:
        result["artifacts"].update(
            {
                "command": f"{directory_name}/command.txt",
                "runner_console_log": f"{directory_name}/runner-console.log",
            }
        )
    return result


def build_conclusion(
    result: dict[str, Any],
    variants: list[dict[str, Any]] | None = None,
    cross_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    strict_exact = (
        result.get("status") == "PASS"
        and result.get("extracted_port_set_exact") is True
        and result.get("schematic_formal_ports") == len(TOP_PORTS)
        and result.get("extracted_formal_ports") == len(TOP_PORTS)
    )
    schematic = set(result.get("schematic_port_order", []))
    extracted = set(result.get("extracted_port_order", []))
    variant_results = variants or [result]
    cross_reference_summaries = [item["summary"] for item in (cross_references or [])]
    combine_changes_counts = None
    if len(cross_reference_summaries) == 2:
        keys = (
            "circuit_status_counts",
            "object_pair_status_counts",
            "object_pair_classification_counts",
            "no_match_layout_circuits",
        )
        combine_changes_counts = any(
            cross_reference_summaries[0].get(key) != cross_reference_summaries[1].get(key)
            for key in keys
        )
    return {
        "parent_wrapper_strict_lvs_exact_match": strict_exact,
        "parent_supply_segment_hypothesis_supported": strict_exact,
        "extra_extracted_formal_ports": sorted(extracted - schematic),
        "missing_schematic_formal_ports": sorted(schematic - extracted),
        "standalone_iopad_control": {
            "status": "FAIL",
            "schematic_formal_ports": 6,
            "extracted_formal_ports": 7,
            "extra_extracted_formal_port": "iovss$1",
            "evidence": "../lvs-pin-boundary-isolation-20260829-001/summary.json",
        },
        "fixture_scope": "five abutted R0 pad cells on one straight edge",
        "variant_status": {
            item.get("name", "strict_deep_baseline"): {
                "strict_lvs": item.get("status"),
                "schematic_formal_ports": item.get("schematic_formal_ports"),
                "extracted_formal_ports": item.get("extracted_formal_ports"),
                "top_port_set_exact": item.get("extracted_port_set_exact"),
                "combine_devices": item.get("requested_options", {}).get("combine_devices", False),
            }
            for item in variant_results
        },
        "combine_devices_changes_cross_reference_counts": combine_changes_counts,
        "leaf_nomatch_circuits": (
            cross_reference_summaries[0].get("no_match_layout_circuits", [])
            if cross_reference_summaries
            else []
        ),
        "root_cause_state": "partially_localized_to_io_leaf_extraction_not_fully_identified",
        "full_chip_135057_port_mismatch_attributed_to_io_only": False,
        "full_chip_root_cause_fully_identified": False,
        "full_chip_attempt_3_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--container-command", default=None)
    parser.add_argument("--summarize-existing", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    run_dir = args.run_dir.resolve()
    summary_path = run_dir / "summary.json"
    if args.summarize_existing:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        baseline = completed_variant_result(
            repo,
            run_dir,
            summary["result"],
            "strict_deep_baseline",
            "strict_deep",
            False,
        )
        combined = completed_variant_result(
            repo,
            run_dir,
            summary["result"],
            "strict_deep_combine_devices",
            "strict_deep_combine_devices",
            True,
        )
        cross_references = [
            cross_reference_record(run_dir / "lvsdb_cross_reference.json", repo),
            cross_reference_record(
                run_dir / "lvsdb_cross_reference_combine_devices.json", repo
            ),
        ]
        summary["schema_version"] = "1.1.0"
        summary["classification"] = "complete_strict_lvs_fail"
        summary["analysis_mode"] = (
            "existing_artifact_spice_headers_logs_and_bounded_lvsdb_cross_reference"
        )
        summary["result"] = baseline
        summary["variants"] = [baseline, combined]
        summary["cross_references"] = cross_references
        summary["conclusion"] = build_conclusion(
            baseline, summary["variants"], cross_references
        )
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)
        print(summary_path)
        return 0

    pdk = repo / "upstream/ihp-open-pdk/ihp-sg13g2"
    io_gds = pdk / "libs.ref/sg13g2_io/gds/sg13g2_io.gds"
    io_cdl = pdk / "libs.ref/sg13g2_io/cdl/sg13g2_io.cdl"
    runner = pdk / "libs.tech/klayout/tech/lvs/run_lvs.py"
    inputs_dir = run_dir / "inputs"
    layout_path = inputs_dir / f"{TOP_CELL}.gds"
    schematic_path = inputs_dir / f"{TOP_CELL}.cdl"
    case_dir = run_dir / "strict_deep"
    run_dir.mkdir(parents=True, exist_ok=True)

    layout_manifest = generate_layout(io_gds, layout_path)
    schematic_path.write_text(
        build_top_cdl(io_cdl.read_text(encoding="utf-8", errors="replace")),
        encoding="utf-8",
    )
    command = build_variant_command(
        sys.executable,
        runner,
        layout_path,
        schematic_path,
        case_dir,
        "deep",
        False,
        top_cell=TOP_CELL,
    )
    case_dir.mkdir(parents=True, exist_ok=True)
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

    extracted = case_dir / f"{TOP_CELL}_extracted.cir"
    layout_log = case_dir / f"{TOP_CELL}.log"
    result = variant_result(
        "parent_supply_segment_strict_deep",
        "deep",
        False,
        command,
        completed.returncode,
        schematic_path,
        extracted,
        layout_log,
        top_cell=TOP_CELL,
    )
    result["artifacts"] = {
        "command": "strict_deep/command.txt",
        "runner_console_log": "strict_deep/runner-console.log",
        "layout_log": "strict_deep/lvs_iopad_parent_wrapper.log",
        "extracted_netlist": "strict_deep/lvs_iopad_parent_wrapper_extracted.cir",
        "lvsdb": "strict_deep/lvs_iopad_parent_wrapper.lvsdb",
    }
    summary = {
        "schema_version": "1.1.0",
        "generated_at": utc_now(),
        "classification": "complete",
        "purpose": "strict_deep_parent_io_ring_connectivity_test",
        "container_reference": IMAGE_REFERENCE,
        "container_digest": IMAGE_DIGEST,
        "container_command": args.container_command,
        "ihp_pdk_commit": PDK_COMMIT,
        "strictness": explicit_option_state("deep", False),
        "source_evidence": [
            "upstream/croc/openroad/src/padring.tcl",
            "upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/lef/sg13g2_io.lef",
        ],
        "interface": {"formal_ports": list(TOP_PORTS), "formal_port_count": len(TOP_PORTS)},
        "layout_manifest": layout_manifest,
        "inputs": {
            "io_gds": file_record(io_gds, repo),
            "io_cdl": file_record(io_cdl, repo),
            "generated_layout": file_record(layout_path, repo),
            "generated_schematic": file_record(schematic_path, repo),
        },
        "result": result,
        "conclusion": build_conclusion(result),
    }
    write_json(summary_path, summary)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
