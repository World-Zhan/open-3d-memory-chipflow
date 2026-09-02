#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ID = "pin3d-openroad-pa-ab-20260901-003"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def all_ints(pattern: str, text: str) -> list[int]:
    return [int(value) for value in re.findall(pattern, text, flags=re.MULTILINE)]


def last_int(pattern: str, text: str) -> int | None:
    values = all_ints(pattern, text)
    return values[-1] if values else None


def parse_drc_report(text: str) -> tuple[int, dict[str, int], dict[str, int]]:
    by_type: Counter[str] = Counter()
    by_layer: Counter[str] = Counter()
    for line in text.splitlines():
        if line.startswith("violation type:"):
            by_type[line.split(":", 1)[1].strip()] += 1
        match = re.search(r" on Layer (\S+)\s*$", line)
        if match:
            by_layer[match.group(1)] += 1
    return sum(by_type.values()), dict(sorted(by_type.items())), dict(sorted(by_layer.items()))


def parse_cross_tier(text: str) -> dict[str, int | None]:
    matches = re.findall(
        r"cross-tier snapshot route after(?: mode=\S+)? "
        r"all=(\d+) UB=(\d+) UIO=(\d+) BIO=(\d+) UBIO=(\d+) UNK=(\d+)",
        text,
    )
    if not matches:
        return {"all": None, "UB": None, "UIO": None, "BIO": None, "UBIO": None, "UNK": None}
    values = [int(value) for value in matches[-1]]
    return dict(zip(("all", "UB", "UIO", "BIO", "UBIO", "UNK"), values, strict=True))


def analyze(
    *,
    run_id: str,
    manifest_path: Path,
    log_path: Path,
    drc_report_path: Path,
    openroad_path: Path,
    patch_path: Path,
    cts_paths: list[Path],
    route_paths: list[Path],
    hbt_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    drc_text = drc_report_path.read_text(encoding="utf-8", errors="replace")
    stage = manifest["stages"][-1]

    drc_total, drc_by_type, drc_by_layer = parse_drc_report(drc_text)
    pin_no_ap = all_ints(r"^#stdCellPinNoAp\s*=\s*(\d+)\s*$", log_text)
    pin_count = all_ints(r"^#stdCellPinCnt\s*=\s*(\d+)\s*$", log_text)
    route_iterations = all_ints(r"Number of violations = (\d+)\.", log_text)
    antenna_net = last_int(r"Found (\d+) net violations\.", log_text)
    antenna_pin = last_int(r"Found (\d+) pin violations\.", log_text)
    no_pin_access_present = "-no_pin_access" in log_text
    drt_0073_count = log_text.count("DRT-0073")
    outputs_present = all(path.is_file() and path.stat().st_size > 0 for path in route_paths)
    command_exit_zero = stage.get("exit_code") == 0 and stage.get("status") == "passed"
    detail_route_completed = "[INFO DRT-0198] Complete detail routing." in log_text
    unrouted_error_count = log_text.count("Design has unrouted nets.")
    route_drc_zero = drc_total == 0

    checks = {
        "command_exit_zero": command_exit_zero,
        "strict_pin_access_enabled": not no_pin_access_present,
        "no_pin_access_option_present": no_pin_access_present,
        "original_drt_0073_errors_absent": drt_0073_count == 0,
        "all_pin_access_passes_have_zero_missing_ap": bool(pin_no_ap) and all(value == 0 for value in pin_no_ap),
        "detail_route_completed": detail_route_completed,
        "route_outputs_present": outputs_present,
        "unrouted_error_absent": unrouted_error_count == 0,
        "antenna_net_violations_zero": antenna_net == 0,
        "antenna_pin_violations_zero": antenna_pin == 0,
        "route_drc_zero": route_drc_zero,
    }
    acceptance_checks = (
        "command_exit_zero",
        "strict_pin_access_enabled",
        "original_drt_0073_errors_absent",
        "all_pin_access_passes_have_zero_missing_ap",
        "detail_route_completed",
        "route_outputs_present",
        "unrouted_error_absent",
        "antenna_net_violations_zero",
        "antenna_pin_violations_zero",
        "route_drc_zero",
    )
    status = "passed" if all(checks[name] for name in acceptance_checks) else "failed"

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "classification": "research_only",
        "track_status": "diagnostic_started_route_failed",
        "status": status,
        "source": {
            "manifest": str(manifest_path.relative_to(ROOT)),
            "log": str(log_path.relative_to(ROOT)),
            "drc_report": str(drc_report_path.relative_to(ROOT)),
            "openroad_commit": "305d3ba2ddfd00591924cc586ad408179f566afe",
            "openroad_binary_sha256": sha256(openroad_path),
            "patch": str(patch_path.relative_to(ROOT)),
            "patch_sha256": sha256(patch_path),
            "command": stage.get("command"),
        },
        "inputs": {str(path.relative_to(ROOT)): sha256(path) for path in cts_paths},
        "outputs": {str(path.relative_to(ROOT)): sha256(path) for path in route_paths},
        "checks": checks,
        "metrics": {
            "pin_access_pass_count": len(pin_no_ap),
            "std_cell_pin_no_ap_values": pin_no_ap,
            "std_cell_pin_count_values": pin_count,
            "drt_0073_count": drt_0073_count,
            "route_iteration_drc_counts": route_iterations,
            "final_route_drc": drc_total,
            "route_drc_by_type": drc_by_type,
            "route_drc_by_layer": drc_by_layer,
            "antenna_net_violations": antenna_net,
            "antenna_pin_violations": antenna_pin,
            "unrouted_error_count": unrouted_error_count,
            "cross_tier_route_after": parse_cross_tier(log_text),
            "hbt_count": (
                hbt_analysis.get("route_geometry", {}).get("hbt_via_count")
                if hbt_analysis is not None
                else None
            ),
            "upper_tier_instances": None,
            "bottom_tier_instances": None,
            "wns_ns": None,
            "tns_ns": None,
        },
        "conclusion": {
            "pin_access_patch_effective": checks["original_drt_0073_errors_absent"]
            and checks["all_pin_access_passes_have_zero_missing_ap"],
            "route_pass": status == "passed",
            "three_dimensional_closure": False,
            "full_smoke_gate_open": False,
            "reason": "pin access succeeds, but route DRC is nonzero and 3D closure metrics are zero or unavailable",
        },
        "forbidden_shortcuts": {
            "no_pin_access": False,
            "min_access_points_zero": False,
            "waiver": False,
            "rule_relaxation": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize the bounded Pin3D strict pin-access route A/B")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--output")
    args = parser.parse_args()

    run_dir = ROOT / "runs" / args.run_id
    output = Path(args.output) if args.output else run_dir / "summary.json"
    if not output.is_absolute():
        output = ROOT / output

    pin3d = ROOT / "upstream" / "taiwei-pin-3d"
    results = pin3d / "results" / "asap7_3D" / "gcd" / "openroad"
    reports = pin3d / "reports" / "asap7_3D" / "gcd" / "openroad"
    hbt_analysis_path = run_dir / "hbt_spacing_analysis.json"
    hbt_analysis = (
        json.loads(hbt_analysis_path.read_text(encoding="utf-8"))
        if hbt_analysis_path.is_file()
        else None
    )
    payload = analyze(
        run_id=args.run_id,
        manifest_path=run_dir / "manifest.json",
        log_path=run_dir / "logs" / "route-down-via-strict-pa.log",
        drc_report_path=reports / "5_route_drc.rpt",
        openroad_path=ROOT / "upstream" / "orfs-research" / "tools" / "install" / "OpenROAD" / "bin" / "openroad",
        patch_path=ROOT / "patches" / "openroad" / "0001-top-routing-layer-standard-cell-down-via.patch",
        cts_paths=[results / name for name in ("4_cts.odb", "4_cts.sdc", "4_cts.v", "4_cts.def")],
        route_paths=[results / name for name in ("5_1_grt.odb", "5_route.odb", "5_route.def", "5_route.v", "5_route.sdc")]
        + [reports / "5_route_drc.rpt"],
        hbt_analysis=hbt_analysis,
    )
    if hbt_analysis is not None:
        payload["source"]["hbt_spacing_analysis"] = str(hbt_analysis_path.relative_to(ROOT))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[write] {output}")
    print(f"[status] {payload['status']} final_route_drc={payload['metrics']['final_route_drc']}")
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
