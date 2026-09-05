#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_RUN = "pin3d-openroad-pa-ab-20260901-003"
DEFAULT_RUN_ID = "pin3d-hbt-capacity-contract-20260903-001"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def axis_capacity(span_um: float, cut_um: float, pitch_um: float) -> int:
    if cut_um <= 0.0 or pitch_um <= 0.0:
        raise ValueError("cut and pitch must be positive")
    if span_um + 1e-12 < cut_um:
        return 0
    return math.floor(((span_um - cut_um) / pitch_um) + 1e-12) + 1


def grid_capacity(
    width_um: float,
    height_um: float,
    cut_width_um: float,
    cut_height_um: float,
    spacing_um: float,
) -> dict[str, Any]:
    if spacing_um < 0.0:
        raise ValueError("spacing must be non-negative")
    pitch_x = cut_width_um + spacing_um
    pitch_y = cut_height_um + spacing_um
    sites_x = axis_capacity(width_um, cut_width_um, pitch_x)
    sites_y = axis_capacity(height_um, cut_height_um, pitch_y)
    return {
        "width_um": width_um,
        "height_um": height_um,
        "pitch_x_um": pitch_x,
        "pitch_y_um": pitch_y,
        "sites_x": sites_x,
        "sites_y": sites_y,
        "total_sites": sites_x * sites_y,
    }


def required_core_plan(
    demand: int,
    utilization: float,
    aspect_ratio: float,
    cut_width_um: float,
    cut_height_um: float,
    spacing_um: float,
) -> dict[str, Any]:
    if demand < 0:
        raise ValueError("demand must be non-negative")
    if not 0.0 < utilization <= 1.0:
        raise ValueError("utilization must be in (0,1]")
    if aspect_ratio <= 0.0:
        raise ValueError("aspect ratio must be positive")
    pitch_x = cut_width_um + spacing_um
    pitch_y = cut_height_um + spacing_um
    if demand == 0:
        return {
            "demand": 0,
            "utilization": utilization,
            "required_sites": 0,
            "width_um": 0.0,
            "height_um": 0.0,
            "area_um2": 0.0,
            "pitch_x_um": pitch_x,
            "pitch_y_um": pitch_y,
            "sites_x": 0,
            "sites_y": 0,
            "total_sites": 0,
        }

    required_sites = math.ceil((demand / utilization) - 1e-12)
    area_bound = demand * pitch_x * pitch_y / utilization
    width_from_area = math.sqrt(area_bound / aspect_ratio)
    best: dict[str, Any] | None = None
    for sites_x in range(1, required_sites + 1):
        sites_y = math.ceil(required_sites / sites_x)
        minimum_width = cut_width_um + (sites_x - 1) * pitch_x
        minimum_height = cut_height_um + (sites_y - 1) * pitch_y
        width = max(width_from_area, minimum_width, minimum_height / aspect_ratio)
        height = width * aspect_ratio
        capacity = grid_capacity(width, height, cut_width_um, cut_height_um, spacing_um)
        if capacity["total_sites"] < required_sites:
            continue
        candidate = {
            **capacity,
            "demand": demand,
            "utilization": utilization,
            "required_sites": required_sites,
            "area_um2": width * height,
        }
        if best is None or candidate["area_um2"] < best["area_um2"]:
            best = candidate
    if best is None:
        raise ValueError("no discrete HBT grid satisfies the contract")
    return best


def parse_capacity_utilization(text: str) -> float:
    match = re.search(r"HBT_MAX_CORE_UTILIZATION\s*\?=\s*([0-9.]+)", text)
    if not match:
        raise ValueError("missing HBT_MAX_CORE_UTILIZATION in platform config")
    value = float(match.group(1))
    if not 0.0 < value <= 1.0:
        raise ValueError("invalid HBT_MAX_CORE_UTILIZATION")
    return value


def analyze(
    *,
    run_id: str,
    spacing_analysis_path: Path,
    platform_config_path: Path,
    patch_path: Path,
    wrapper_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    spacing = json.loads(spacing_analysis_path.read_text(encoding="utf-8"))
    utilization = parse_capacity_utilization(platform_config_path.read_text(encoding="utf-8"))
    tech = spacing["tech_rule"]
    route = spacing["route_geometry"]
    partition = spacing["partition_contract"]
    cut_width = float(tech["cut_rect_width_um"])
    cut_height = float(tech["cut_rect_height_um"])
    minimum_spacing = float(tech["minimum_edge_spacing_um"])
    demand = int(partition["selected_cut"])
    observed_route_hbts = int(route["hbt_via_count"])

    current = grid_capacity(
        float(route["die_width_um"]),
        float(route["die_height_um"]),
        cut_width,
        cut_height,
        minimum_spacing,
    )
    current_usable = math.floor(utilization * current["total_sites"])
    planned = required_core_plan(
        demand,
        utilization,
        1.0,
        cut_width,
        cut_height,
        minimum_spacing,
    )

    checks = {
        "source_hbt_root_cause_proven": bool(
            spacing["conclusion"]["hb_cut_spacing_root_cause_proven"]
        ),
        "selected_partition_exceeds_current_usable_capacity": demand > current_usable,
        "planned_discrete_capacity_meets_reserved_sites": (
            planned["total_sites"] >= planned["required_sites"]
        ),
        "observed_route_hbt_count_fits_reserved_sites": (
            observed_route_hbts <= planned["required_sites"]
        ),
        "floorplan_stage_ab_executed": False,
        "route_drc_zero": False,
    }
    static_gate = all(
        checks[key]
        for key in (
            "source_hbt_root_cause_proven",
            "selected_partition_exceeds_current_usable_capacity",
            "planned_discrete_capacity_meets_reserved_sites",
            "observed_route_hbt_count_fits_reserved_sites",
        )
    )
    inputs = (spacing_analysis_path, platform_config_path, patch_path, wrapper_path)
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "classification": "research_only",
        "status": "static_contract_ready_stage_ab_not_run" if static_gate else "static_contract_failed",
        "source_run_id": spacing.get("run_id", DEFAULT_SOURCE_RUN),
        "source": {
            "files": [source_path(path, root) for path in inputs],
            "sha256": {source_path(path, root): sha256(path) for path in inputs},
            "pinned_taiwei_commit": "c85b79352eefc31a588da3ef873e4fd68a3df3f2",
            "cadence_reference": [
                "upstream/taiwei-pin-3d/scripts_cadence/innovus_3d_floorplan.tcl",
                "upstream/taiwei-pin-3d/scripts_cadence/innovus_hb_layer_obs.tcl",
            ],
        },
        "contract_inputs": {
            "tech_rule_source": "selected_TECH_LEF",
            "cut_width_um": cut_width,
            "cut_height_um": cut_height,
            "minimum_edge_spacing_um": minimum_spacing,
            "legal_pitch_x_um": cut_width + minimum_spacing,
            "legal_pitch_y_um": cut_height + minimum_spacing,
            "capacity_utilization": utilization,
            "partition_selected_cut_demand": demand,
            "observed_final_route_hbt_count": observed_route_hbts,
        },
        "current_floorplan": {
            **current,
            "usable_capacity_at_limit": current_usable,
            "partition_selected_feasible": bool(partition["selected_feasible"]),
        },
        "planned_floorplan": planned,
        "checks": checks,
        "gates": {
            "static_contract_gate_open": static_gate,
            "partition_pre_floorplan_ab_gate_open": static_gate,
            "full_route_gate_open": False,
            "full_smoke_gate_open": False,
        },
        "conclusion": {
            "direct_problem": (
                f"The {demand}-cut partition demand exceeds the current usable HBT capacity "
                f"of {current_usable} sites derived from the selected TECH_LEF."
            ),
            "planned_contract": (
                f"At utilization {utilization:.3f}, the partition reserves "
                f"{planned['required_sites']} sites on a {planned['sites_x']}x{planned['sites_y']} "
                f"grid and requires at least {planned['width_um']:.6f}x"
                f"{planned['height_um']:.6f} um before handoff."
            ),
            "scope": (
                "This is a static capacity-contract proof only. It does not prove that the router "
                "will place HBTs on the legal lattice, eliminate the 530 hb_layer markers, or "
                "resolve the remaining 112 route markers."
            ),
            "next_gate": (
                "Apply the patch temporarily and run only ord-tier-partition, ord-pre, and "
                "ord-3d-floorplan in a new flow variant; require a TECH_LEF-matched contract and "
                "capacity_validated=1 before any reroute."
            ),
        },
        "forbidden_shortcuts": [
            "reduce_1.568um_spacing",
            "disable_or_waive_route_drc",
            "no_pin_access",
            "full_route_before_floorplan_contract_ab",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static Pin3D HBT capacity-contract evidence.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--spacing-analysis",
        type=Path,
        default=ROOT / "runs" / DEFAULT_SOURCE_RUN / "hbt_spacing_analysis.json",
    )
    parser.add_argument(
        "--platform-config",
        type=Path,
        default=ROOT / "upstream" / "taiwei-pin-3d" / "platforms" / "asap7_3D" / "config.mk",
    )
    parser.add_argument(
        "--patch",
        type=Path,
        default=ROOT
        / "patches"
        / "taiwei-pin-3d"
        / "0001-tech-derived-hbt-capacity-contract.patch",
    )
    parser.add_argument(
        "--wrapper",
        type=Path,
        default=ROOT / "scripts" / "with_taiwei_hbt_contract_patch.sh",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "runs" / DEFAULT_RUN_ID / "summary.json",
    )
    parser.add_argument(
        "--stage-ab",
        type=Path,
        default=ROOT / "runs" / DEFAULT_RUN_ID / "stage_ab.json",
    )
    args = parser.parse_args()
    payload = analyze(
        run_id=args.run_id,
        spacing_analysis_path=args.spacing_analysis,
        platform_config_path=args.platform_config,
        patch_path=args.patch,
        wrapper_path=args.wrapper,
    )
    if args.stage_ab.is_file():
        stage_ab = json.loads(args.stage_ab.read_text(encoding="utf-8"))
        stage_passed = bool(
            stage_ab.get("gates", {}).get("partition_pre_floorplan_ab_gate_passed", False)
        )
        payload["status"] = stage_ab.get("status", payload["status"])
        payload["checks"]["floorplan_stage_ab_executed"] = True
        payload["checks"]["floorplan_stage_ab_passed"] = stage_passed
        payload["gates"]["partition_pre_floorplan_ab_gate_passed"] = stage_passed
        payload["gates"]["legal_hbt_lattice_placement_gate_passed"] = False
        payload["stage_ab_report"] = source_path(args.stage_ab, ROOT)
        payload["source"]["files"].append(source_path(args.stage_ab, ROOT))
        payload["source"]["sha256"][source_path(args.stage_ab, ROOT)] = sha256(args.stage_ab)
        payload["conclusion"]["next_gate"] = stage_ab["conclusion"]["next_gate"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["gates"], sort_keys=True))
    return 0 if payload["gates"]["static_contract_gate_open"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
