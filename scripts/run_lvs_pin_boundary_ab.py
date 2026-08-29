#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a strict, minimal IO-pad plus standard-cell LVS pin-boundary A/B.

The script intentionally keeps strict port comparison and simplification enabled.
It never passes ignore_top_ports_mismatch, implicit_nets, or no_simplify.
Large LVS databases are left for KLayout; summaries stream only SPICE headers/logs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

from analyze_croc_lvs import compare_top_ports, parse_log_options, parse_subckt_ports


TOP_CELL = "lvs_pin_boundary_ab"
IMAGE_REFERENCE = "hpretl/iic-osic-tools:2025.12"
IMAGE_DIGEST = "sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521"
PDK_COMMIT = "331c00484213b13414777eec1336ef5c29b969bd"
FORBIDDEN_OPTIONS = {
    "--ignore_top_ports_mismatch",
    "--implicit_nets",
    "--no_simplify",
}
VARIANTS = (
    ("deep_top_pins_off", "deep", False),
    ("flat_top_pins_off", "flat", False),
    ("deep_top_pins_on", "deep", True),
    ("flat_top_pins_on", "flat", True),
)
PORT_GROUPS = (
    {
        "cell": "sg13g2_IOPadIn",
        "instance": "XIO",
        "offset_dbu": (0, 0),
        "ports": (
            ("pad", "IO_PAD"),
            ("p2c", "IO_P2C"),
            ("vdd", "IO_VDD"),
            ("vss", "IO_VSS"),
            ("iovdd", "IO_IOVDD"),
            ("iovss", "IO_IOVSS"),
        ),
    },
    {
        "cell": "sg13g2_inv_1",
        "instance": "XINV",
        "offset_dbu": (100_000, 0),
        "ports": (
            ("Y", "INV_Y"),
            ("A", "INV_A"),
            ("VDD", "INV_VDD"),
            ("VSS", "INV_VSS"),
        ),
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, root: Path) -> dict[str, Any]:
    stat = path.stat()
    try:
        display_path = str(path.relative_to(root))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def extract_subckt_block(text: str, name: str) -> str:
    """Return one complete .SUBCKT block without loading any LVS database."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) >= 2 and fields[0].lower() == ".subckt" and fields[1].lower() == name.lower():
            start = index
            break
    if start is None:
        raise ValueError(f".SUBCKT {name} not found")
    for end in range(start + 1, len(lines)):
        if lines[end].strip().lower().startswith(".ends"):
            return "\n".join(lines[start : end + 1]) + "\n"
    raise ValueError(f".ENDS for {name} not found")


def expected_top_ports() -> list[str]:
    return [top_name for group in PORT_GROUPS for _, top_name in group["ports"]]


def build_top_cdl(io_cdl: str, inverter_block: str) -> str:
    ports = expected_top_ports()
    lines = [
        "* Generated strict LVS pin-boundary A/B schematic",
        f".SUBCKT {TOP_CELL} {' '.join(ports)}",
    ]
    for group in PORT_GROUPS:
        nodes = " ".join(top_name for _, top_name in group["ports"])
        lines.append(f"{group['instance']} {nodes} / {group['cell']}")
    lines.extend([".ENDS", "", io_cdl.rstrip(), "", inverter_block.rstrip(), ""])
    return "\n".join(lines)


def _first_direct_text(layout: Any, cell: Any, pin_name: str) -> tuple[int, Any]:
    for layer_index in layout.layer_indices():
        info = layout.get_info(layer_index)
        if info.datatype != 25:
            continue
        for shape in cell.shapes(layer_index).each():
            if shape.is_text() and shape.text.string.lower() == pin_name.lower():
                return layer_index, shape.text.trans.disp
    raise ValueError(f"direct datatype-25 label {pin_name!r} not found in {cell.name}")


def generate_layout(io_gds: Path, stdcell_gds: Path, output: Path) -> list[dict[str, Any]]:
    """Build a hierarchical top and add exactly ten renamed parent labels."""
    import klayout.db as kdb

    layout = kdb.Layout()
    layout.read(str(io_gds))
    layout.read(str(stdcell_gds))
    top = layout.create_cell(TOP_CELL)
    if top is None:
        raise RuntimeError(f"failed to create {TOP_CELL}")

    label_manifest: list[dict[str, Any]] = []
    for group in PORT_GROUPS:
        child = layout.cell(group["cell"])
        if child is None:
            raise ValueError(f"GDS cell {group['cell']} not found")
        dx, dy = group["offset_dbu"]
        top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(dx, dy)))
        for child_pin, top_pin in group["ports"]:
            layer_index, point = _first_direct_text(layout, child, child_pin)
            info = layout.get_info(layer_index)
            parent_point = kdb.Point(point.x + dx, point.y + dy)
            top.shapes(layer_index).insert(kdb.Text(top_pin, kdb.Trans(parent_point)))
            label_manifest.append(
                {
                    "child_cell": group["cell"],
                    "child_pin": child_pin,
                    "top_pin": top_pin,
                    "layer": info.layer,
                    "datatype": info.datatype,
                    "x_dbu": parent_point.x,
                    "y_dbu": parent_point.y,
                }
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(output))
    return label_manifest


def build_variant_command(
    python: str,
    runner: Path,
    layout: Path,
    schematic: Path,
    run_dir: Path,
    run_mode: str,
    top_lvl_pins: bool,
    top_cell: str = TOP_CELL,
) -> list[str]:
    command = [
        python,
        str(runner),
        f"--layout={layout}",
        f"--netlist={schematic}",
        f"--run_dir={run_dir}",
        f"--topcell={top_cell}",
        f"--run_mode={run_mode}",
    ]
    if top_lvl_pins:
        command.append("--top_lvl_pins")
    validate_strict_command(command)
    return command


def validate_strict_command(command: list[str]) -> None:
    for token in command:
        option = token.split("=", 1)[0]
        if option in FORBIDDEN_OPTIONS:
            raise ValueError(f"forbidden LVS option: {option}")


def explicit_option_state(run_mode: str, top_lvl_pins: bool) -> dict[str, Any]:
    return {
        "run_mode": run_mode,
        "top_level_pins_option": top_lvl_pins,
        "strict_port_mode": True,
        "flag_missing_ports": True,
        "ignore_top_ports_mismatch": False,
        "implicit_nets": None,
        "simplify_enabled": True,
        "disabled_or_weakened_checks": [],
    }


def variant_result(
    name: str,
    run_mode: str,
    top_lvl_pins: bool,
    command: list[str],
    returncode: int,
    schematic: Path,
    extracted: Path,
    layout_log: Path,
    top_cell: str = TOP_CELL,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "command": shlex.join(command),
        "runner_returncode": returncode,
        "requested_options": explicit_option_state(run_mode, top_lvl_pins),
    }
    if not extracted.is_file() or not layout_log.is_file():
        result.update(
            {
                "status": "ERROR",
                "boundary_classification": "missing_outputs",
                "missing_outputs": [str(path) for path in (extracted, layout_log) if not path.is_file()],
            }
        )
        return result

    schematic_header = parse_subckt_ports(schematic, top_cell)
    extracted_header = parse_subckt_ports(extracted, top_cell)
    comparison = compare_top_ports(schematic_header["ports"], extracted_header["ports"])
    logged = parse_log_options(layout_log)
    exact_set = set(schematic_header["ports"]) == set(extracted_header["ports"])
    exact_boundary = exact_set and schematic_header["port_count"] == extracted_header["port_count"]
    if logged["netlists_match"]:
        status = "PASS"
    elif logged["netlists_mismatch"]:
        status = "FAIL"
    else:
        status = "UNKNOWN"
    result.update(
        {
            "status": status,
            "boundary_classification": "exact_expected_top_port_set" if exact_boundary else "top_port_leakage_or_loss",
            "schematic_formal_ports": schematic_header["port_count"],
            "extracted_formal_ports": extracted_header["port_count"],
            "exact_shared_ports": comparison["exact_shared_count"],
            "formal_port_count_delta": comparison["formal_port_count_delta"],
            "extracted_port_set_exact": exact_boundary,
            "schematic_port_order": schematic_header["ports"],
            "extracted_port_order": extracted_header["ports"],
            "port_analysis": comparison,
            "observed_log_options": logged,
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--container-command", default=None)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    run_dir = args.run_dir.resolve()
    pdk = repo / "upstream/ihp-open-pdk/ihp-sg13g2"
    io_gds = pdk / "libs.ref/sg13g2_io/gds/sg13g2_io.gds"
    io_cdl_path = pdk / "libs.ref/sg13g2_io/cdl/sg13g2_io.cdl"
    std_gds = pdk / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
    std_cdl_path = pdk / "libs.ref/sg13g2_stdcell/cdl/sg13g2_stdcell.cdl"
    runner = pdk / "libs.tech/klayout/tech/lvs/run_lvs.py"
    inputs_dir = run_dir / "inputs"
    layout_path = inputs_dir / f"{TOP_CELL}.gds"
    schematic_path = inputs_dir / f"{TOP_CELL}.cdl"
    summary_path = run_dir / "summary.json"

    run_dir.mkdir(parents=True, exist_ok=True)
    label_manifest = generate_layout(io_gds, std_gds, layout_path)
    io_cdl = io_cdl_path.read_text(encoding="utf-8", errors="replace")
    inverter_block = extract_subckt_block(
        std_cdl_path.read_text(encoding="utf-8", errors="replace"), "sg13g2_inv_1"
    )
    schematic_path.write_text(build_top_cdl(io_cdl, inverter_block), encoding="utf-8")

    manifest = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "purpose": "strict_lvs_pin_extraction_boundary_ab",
        "top_cell": TOP_CELL,
        "expected_top_ports": expected_top_ports(),
        "expected_top_port_count": len(expected_top_ports()),
        "container_reference": IMAGE_REFERENCE,
        "container_digest": IMAGE_DIGEST,
        "ihp_pdk_commit": PDK_COMMIT,
        "container_command": args.container_command,
        "script_invocation": shlex.join([sys.executable, *sys.argv]),
        "strictness": explicit_option_state("per_variant", False),
        "selected_parent_labels": label_manifest,
        "inputs": {
            "io_gds": file_record(io_gds, repo),
            "io_cdl": file_record(io_cdl_path, repo),
            "stdcell_gds": file_record(std_gds, repo),
            "stdcell_cdl": file_record(std_cdl_path, repo),
            "generated_layout": file_record(layout_path, repo),
            "generated_schematic": file_record(schematic_path, repo),
        },
        "variants": [],
    }
    write_json(run_dir / "input_manifest.json", manifest)

    summary: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "classification": "in_progress",
        "analysis_mode": "streaming_spice_headers_and_logs_no_lvsdb_load",
        "top_cell": TOP_CELL,
        "expected_top_port_count": len(expected_top_ports()),
        "strictness": explicit_option_state("per_variant", False),
        "variants": [],
    }
    write_json(summary_path, summary)

    for name, run_mode, top_lvl_pins in VARIANTS:
        variant_dir = run_dir / "variants" / name
        variant_dir.mkdir(parents=True, exist_ok=True)
        command = build_variant_command(
            sys.executable,
            runner,
            layout_path,
            schematic_path,
            variant_dir,
            run_mode,
            top_lvl_pins,
        )
        (variant_dir / "command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
        with (variant_dir / "runner-console.log").open("w", encoding="utf-8") as log_stream:
            completed = subprocess.run(
                command,
                cwd=repo,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        extracted = variant_dir / f"{TOP_CELL}_extracted.cir"
        layout_log = variant_dir / f"{TOP_CELL}.log"
        result = variant_result(
            name,
            run_mode,
            top_lvl_pins,
            command,
            completed.returncode,
            schematic_path,
            extracted,
            layout_log,
        )
        result["artifacts"] = {
            "command": str((variant_dir / "command.txt").relative_to(run_dir)),
            "runner_console_log": str((variant_dir / "runner-console.log").relative_to(run_dir)),
            "layout_log": str(layout_log.relative_to(run_dir)) if layout_log.exists() else None,
            "extracted_netlist": str(extracted.relative_to(run_dir)) if extracted.exists() else None,
            "lvsdb": str((variant_dir / f"{TOP_CELL}.lvsdb").relative_to(run_dir))
            if (variant_dir / f"{TOP_CELL}.lvsdb").exists()
            else None,
        }
        summary["variants"].append(result)
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)

    exact_off = {
        result["name"]: result.get("extracted_port_set_exact")
        for result in summary["variants"]
        if result["name"].endswith("top_pins_off")
    }
    summary["classification"] = "complete"
    summary["conclusion"] = {
        "deep_top_pins_off_exact": exact_off.get("deep_top_pins_off"),
        "flat_top_pins_off_exact": exact_off.get("flat_top_pins_off"),
        "deep_prevents_flat_label_leakage": exact_off.get("deep_top_pins_off") is True
        and exact_off.get("flat_top_pins_off") is False,
        "full_chip_attempt_3_authorized": False,
    }
    summary["generated_at"] = utc_now()
    write_json(summary_path, summary)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
