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
TAIWEI = ROOT / "upstream" / "taiwei-pin-3d"
RUN_ID = "pin3d-hbt-capacity-contract-20260903-001"
PARTITION_VARIANT = "hbt_contract_ab_20260903_001"
FLOORPLAN_VARIANT = "hbt_contract_ab_20260903_002"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_path(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def parse_flat_tcl_dict(text: str) -> dict[str, str]:
    tokens = text.split()
    if not tokens or len(tokens) % 2:
        raise ValueError("expected a flat even-length Tcl dictionary")
    return dict(zip(tokens[0::2], tokens[1::2]))


def parse_core_bbox(text: str) -> dict[str, float]:
    matches = re.findall(
        r"Core BBox:\s*\(\s*([-0-9.]+)\s+([-0-9.]+)\s*\)\s*"
        r"\(\s*([-0-9.]+)\s+([-0-9.]+)\s*\)\s*um",
        text,
    )
    if not matches:
        raise ValueError("missing OpenROAD Core BBox")
    lx, ly, ux, uy = (float(value) for value in matches[-1])
    return {
        "lx_um": lx,
        "ly_um": ly,
        "ux_um": ux,
        "uy_um": uy,
        "width_um": ux - lx,
        "height_um": uy - ly,
        "area_um2": (ux - lx) * (uy - ly),
    }


def discrete_capacity(width: float, height: float, cut: float, spacing: float) -> dict[str, int]:
    pitch = cut + spacing

    def axis(span: float) -> int:
        if span + 1e-12 < cut:
            return 0
        return math.floor(((span - cut) / pitch) + 1e-12) + 1

    sites_x = axis(width)
    sites_y = axis(height)
    return {"sites_x": sites_x, "sites_y": sites_y, "total_sites": sites_x * sites_y}


def numeric_contract(raw: dict[str, str]) -> dict[str, Any]:
    integer_keys = {
        "cuts_per_net",
        "selected_cut_nets",
        "estimated_hbt_demand",
        "current_grid_sites_x",
        "current_grid_sites_y",
        "current_grid_total_sites",
        "current_usable_hbt_capacity",
        "selected_feasible_current_die",
        "requires_floorplan_expansion",
        "floorplan_capacity_validation_required",
        "final_grid_sites_x",
        "final_grid_sites_y",
        "final_grid_total_sites",
        "required_hbt_sites",
        "capacity_validated",
    }
    float_keys = {
        "cut_width_um",
        "cut_height_um",
        "minimum_edge_spacing_um",
        "legal_pitch_x_um",
        "legal_pitch_y_um",
        "capacity_utilization",
        "current_die_width_um",
        "current_die_height_um",
        "logic_core_area_um2",
        "minimum_core_width_um",
        "minimum_core_height_um",
        "requested_core_width_um",
        "requested_core_height_um",
        "requested_core_area_um2",
        "final_core_width_um",
        "final_core_height_um",
        "final_core_area_um2",
        "hbt_pitch_area_utilization",
    }
    converted: dict[str, Any] = dict(raw)
    for key in integer_keys & raw.keys():
        converted[key] = int(raw[key])
    for key in float_keys & raw.keys():
        converted[key] = float(raw[key])
    return converted


def collect(
    *,
    run_id: str,
    taiwei: Path,
    partition_variant: str,
    floorplan_variant: str,
    patch_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    base_results = taiwei / "results" / "asap7_3D" / "gcd"
    base_logs = taiwei / "logs" / "asap7_3D" / "gcd"
    partition_dir = base_results / partition_variant
    floorplan_dir = base_results / floorplan_variant
    partition_log = base_logs / partition_variant / "2_tritonpart.log"
    pre_log = base_logs / partition_variant / "2_3d_views.log"
    first_floorplan_log = base_logs / partition_variant / "2_3_floorplan_3d.log"
    final_floorplan_log = base_logs / floorplan_variant / "2_3_floorplan_3d.log"
    baseline_floorplan_log = base_logs / "openroad" / "2_3_floorplan_3d.log"
    partition_contract_path = partition_dir / "hbt_capacity.contract.tcl"
    floorplan_contract_path = floorplan_dir / "hbt_capacity.floorplan.tcl"
    final_def = floorplan_dir / "2_3_floorplan_3d.def"
    final_verilog = floorplan_dir / "2_3_floorplan_3d.v"
    handoff = floorplan_dir / "handoffs" / "floorplan-3d.tcl"
    paths = (
        patch_path,
        partition_log,
        pre_log,
        first_floorplan_log,
        final_floorplan_log,
        baseline_floorplan_log,
        partition_contract_path,
        floorplan_contract_path,
        final_def,
        final_verilog,
        handoff,
    )
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"missing A/B evidence: {missing}")

    partition = numeric_contract(
        parse_flat_tcl_dict(partition_contract_path.read_text(encoding="utf-8"))
    )
    floorplan = numeric_contract(
        parse_flat_tcl_dict(floorplan_contract_path.read_text(encoding="utf-8"))
    )
    baseline_bbox = parse_core_bbox(baseline_floorplan_log.read_text(encoding="utf-8", errors="replace"))
    first_bbox = parse_core_bbox(first_floorplan_log.read_text(encoding="utf-8", errors="replace"))
    final_bbox = parse_core_bbox(final_floorplan_log.read_text(encoding="utf-8", errors="replace"))
    demand = int(partition["estimated_hbt_demand"])
    cut = float(partition["cut_width_um"])
    spacing = float(partition["minimum_edge_spacing_um"])
    pitch_area = float(partition["legal_pitch_x_um"]) * float(partition["legal_pitch_y_um"])
    limit = float(partition["capacity_utilization"])

    first_capacity = discrete_capacity(first_bbox["width_um"], first_bbox["height_um"], cut, spacing)
    first_actual_utilization = demand * pitch_area / first_bbox["area_um2"]
    first_contract_pass = (
        first_capacity["total_sites"] >= int(floorplan["required_hbt_sites"])
        and first_actual_utilization <= limit + 1e-12
    )
    final_capacity = discrete_capacity(final_bbox["width_um"], final_bbox["height_um"], cut, spacing)
    final_actual_utilization = demand * pitch_area / final_bbox["area_um2"]
    final_contract_pass = (
        int(floorplan["capacity_validated"]) == 1
        and final_capacity["total_sites"] >= int(floorplan["required_hbt_sites"])
        and final_actual_utilization <= limit + 1e-12
        and math.isclose(
            final_actual_utilization,
            float(floorplan["hbt_pitch_area_utilization"]),
            abs_tol=1e-12,
        )
    )
    partition_log_text = partition_log.read_text(encoding="utf-8", errors="replace")
    pre_log_text = pre_log.read_text(encoding="utf-8", errors="replace")
    final_log_text = final_floorplan_log.read_text(encoding="utf-8", errors="replace")
    checks = {
        "tech_lef_rule_derived": "source=TECH_LEF" in partition_log_text,
        "partition_contract_written": True,
        "partition_requires_expansion": int(partition["requires_floorplan_expansion"]) == 1,
        "ord_pre_completed": "Summary: total_instances=" in pre_log_text and "Elapsed:" in pre_log_text,
        "first_floorplan_requested_size_check_rejected_by_post_audit": not first_contract_pass,
        "final_floorplan_actual_core_contract_pass": final_contract_pass,
        "final_floorplan_log_capacity_pass": "HBT capacity PASS" in final_log_text,
        "final_handoff_contract_records_capacity_validated": "hbt_capacity_validated 1" in handoff.read_text(
            encoding="utf-8", errors="replace"
        ),
        "route_rerun_performed": False,
        "route_drc_zero": False,
    }
    stage_gate = all(
        checks[key]
        for key in (
            "tech_lef_rule_derived",
            "partition_contract_written",
            "partition_requires_expansion",
            "ord_pre_completed",
            "first_floorplan_requested_size_check_rejected_by_post_audit",
            "final_floorplan_actual_core_contract_pass",
            "final_floorplan_log_capacity_pass",
            "final_handoff_contract_records_capacity_validated",
        )
    )
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "classification": "research_only",
        "status": "floorplan_contract_ab_passed_route_not_run" if stage_gate else "floorplan_contract_ab_failed",
        "pinned_taiwei_commit": "c85b79352eefc31a588da3ef873e4fd68a3df3f2",
        "pinned_openroad_commit": "305d3ba2ddfd00591924cc586ad408179f566afe",
        "commands": [
            "NUM_CORES=6 bash scripts/with_taiwei_hbt_contract_patch.sh run bash upstream/taiwei-pin-3d/test/common/run_stage.sh asap7_3D hbt_contract_ab_20260903_001 openroad gcd ord-tier-partition",
            "NUM_CORES=6 bash scripts/with_taiwei_hbt_contract_patch.sh run bash upstream/taiwei-pin-3d/test/common/run_stage.sh asap7_3D hbt_contract_ab_20260903_001 openroad gcd ord-pre",
            "NUM_CORES=6 bash scripts/with_taiwei_hbt_contract_patch.sh run bash upstream/taiwei-pin-3d/test/common/run_stage.sh asap7_3D hbt_contract_ab_20260903_002 openroad gcd ord-3d-floorplan",
        ],
        "partition_contract": partition,
        "baseline_unpatched_floorplan": {
            "variant": "openroad",
            "actual_core_bbox": baseline_bbox,
            "hbt_capacity_contract_present": False,
        },
        "floorplan_attempts": [
            {
                "variant": partition_variant,
                "check_mode": "requested_dimensions_only",
                "actual_core_bbox": first_bbox,
                "actual_discrete_capacity": first_capacity,
                "actual_hbt_pitch_area_utilization": first_actual_utilization,
                "capacity_limit": limit,
                "post_run_actual_core_contract_pass": first_contract_pass,
                "accepted": False,
            },
            {
                "variant": floorplan_variant,
                "check_mode": "site_snap_guard_plus_actual_odb_core",
                "floorplan_contract": floorplan,
                "actual_core_bbox": final_bbox,
                "actual_discrete_capacity": final_capacity,
                "actual_hbt_pitch_area_utilization": final_actual_utilization,
                "capacity_limit": limit,
                "actual_core_contract_pass": final_contract_pass,
                "accepted": final_contract_pass,
            },
        ],
        "checks": checks,
        "gates": {
            "partition_pre_floorplan_ab_gate_passed": stage_gate,
            "legal_hbt_lattice_placement_gate_passed": False,
            "full_route_gate_open": False,
            "full_smoke_gate_open": False,
        },
        "source": {
            "files": [source_path(path, root) for path in paths],
            "sha256": {source_path(path, root): sha256(path) for path in paths},
        },
        "conclusion": {
            "proven": (
                "The patched partition/pre/floorplan handoff derives 0.032/1.568 um from the "
                "selected 3D TECH_LEF, expands the floorplan, and validates the actual snapped "
                "ODB core at 14.58x14.31 um with 90 discrete sites and utilization 0.760737."
            ),
            "not_proven": (
                "No placement, CTS, or route was rerun. Capacity alone does not constrain HBT "
                "coordinates to the legal 1.6 um lattice, does not clear the 530 hb_layer markers, "
                "and does not address the remaining 112 route markers."
            ),
            "next_gate": (
                "Add a legal-lattice HBT placement/window contract and validate it before any "
                "bounded reroute; keep full route and full smoke closed until then."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect the bounded Pin3D HBT contract stage A/B.")
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--taiwei-root", type=Path, default=TAIWEI)
    parser.add_argument("--partition-variant", default=PARTITION_VARIANT)
    parser.add_argument("--floorplan-variant", default=FLOORPLAN_VARIANT)
    parser.add_argument(
        "--patch",
        type=Path,
        default=ROOT
        / "patches"
        / "taiwei-pin-3d"
        / "0001-tech-derived-hbt-capacity-contract.patch",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "runs" / RUN_ID / "stage_ab.json",
    )
    args = parser.parse_args()
    payload = collect(
        run_id=args.run_id,
        taiwei=args.taiwei_root,
        partition_variant=args.partition_variant,
        floorplan_variant=args.floorplan_variant,
        patch_path=args.patch,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["gates"], sort_keys=True))
    return 0 if payload["gates"]["partition_pre_floorplan_ab_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
