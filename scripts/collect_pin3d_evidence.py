#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Collect and enforce research-only Pin3D acceptance criteria."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PIN3D = ROOT / "upstream/taiwei-pin-3d"
VARIANT = "openroad"
REL = Path("asap7_3D/gcd")
LOG_DIR = PIN3D / "logs" / REL / VARIANT
REPORT_DIR = PIN3D / "reports" / REL / VARIANT
RESULT_DIR = PIN3D / "results" / REL / VARIANT


def metric_value(payload: dict, key: str) -> int | float | None:
    item = payload.get(key)
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def git_head(path: Path) -> str | None:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def instance_counts(def_path: Path) -> tuple[int, int]:
    upper = 0
    bottom = 0
    if not def_path.is_file():
        return upper, bottom
    in_components = False
    for line in def_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("COMPONENTS "):
            in_components = True
            continue
        if line.startswith("END COMPONENTS"):
            break
        if not in_components:
            continue
        match = re.match(r"\s*-\s+\S+\s+(\S+)", line)
        if not match:
            continue
        master = match.group(1).lower()
        if "upper" in master:
            upper += 1
        elif "bottom" in master:
            bottom += 1
    return upper, bottom


def mixed_fanout_count() -> int | None:
    candidates = list(LOG_DIR.glob("*.mixed_fanout.after.nets"))
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        match = re.search(r"^Total Mixed-Fanout Nets:\s+(\d+)", path.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if match:
            return int(match.group(1))
    return None


def max_temperature_c() -> float | None:
    thermal = RESULT_DIR / "hotspot_outputs"
    if not thermal.is_dir():
        return None
    candidates: list[float] = []
    for path in thermal.rglob("*"):
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"(?i)(?:max(?:imum)?[_ ]?(?:temp(?:erature)?)?\s*[:=]\s*)([-+]?\d+(?:\.\d+)?)\s*([CK]?)", text):
            value = float(match.group(1))
            unit = match.group(2).upper()
            if unit == "K" or (not unit and value > 200):
                value -= 273.15
            if -50 <= value <= 250:
                candidates.append(value)
    return max(candidates) if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["smoke", "full"], required=True)
    parser.add_argument("--tool-returncode", type=int, required=True)
    args = parser.parse_args()
    run_dir = Path(os.environ["FLOW_RUN_DIR"])
    output_metrics = run_dir / "pin3d_openroad_metrics.json"

    extractor = PIN3D / "util/extract_eval_metrics.py"
    proc = subprocess.run(
        [
            sys.executable, str(extractor),
            "--openroad-log-dir", str(LOG_DIR),
            "--openroad-report-dir", str(REPORT_DIR),
            "--openroad-result-dir", str(RESULT_DIR),
            "--openroad-output", str(output_metrics),
            "--repo-root", str(PIN3D),
        ],
        cwd=PIN3D,
        check=False,
    )
    metrics = json.loads(output_metrics.read_text(encoding="utf-8")) if output_metrics.is_file() else {}
    hbt = metric_value(metrics, "finish__route__hb_via__count__phys")
    cross_tier = metric_value(metrics, "finish__route__cross_tier_nets__all")
    wns = metric_value(metrics, "finish__timing__setup__ws")
    tns = metric_value(metrics, "finish__timing__setup__tns")
    drc = metric_value(metrics, "finish__route__drc_errors")
    core_area = metric_value(metrics, "finish__design__core__area")
    stdcell_area = metric_value(metrics, "finish__design__instance__area__stdcell")
    macro_area = metric_value(metrics, "finish__design__instance__area__macro")
    power = metric_value(metrics, "finish__power__total")

    required_outputs = [
        RESULT_DIR / "6_final.odb",
        RESULT_DIR / "6_final.def",
        RESULT_DIR / "6_final.v",
        RESULT_DIR / "6_final.sdc",
        RESULT_DIR / "6_final.spef",
        LOG_DIR / "final_summary.txt",
        LOG_DIR / "cross_tier_nets.list",
        LOG_DIR / "2_6_floorplan_pdn_bottom.log",
        LOG_DIR / "2_6_floorplan_pdn_upper.log",
    ]
    missing = [str(path.relative_to(PIN3D)) for path in required_outputs if not path.is_file() or path.stat().st_size == 0]
    upper_instances, bottom_instances = instance_counts(RESULT_DIR / "6_final.def")
    bottom_pdn = LOG_DIR / "2_6_floorplan_pdn_bottom.log"
    upper_pdn = LOG_DIR / "2_6_floorplan_pdn_upper.log"
    pdn_ok = all(path.is_file() and "ErrorPDN" not in path.read_text(encoding="utf-8", errors="replace") for path in (bottom_pdn, upper_pdn))
    mixed = mixed_fanout_count()
    temperature = max_temperature_c()

    checks = {
        "launcher_exit_zero": args.tool_returncode == 0,
        "metric_extractor_exit_zero": proc.returncode == 0,
        "required_outputs_present": not missing,
        "bottom_tier_has_instances": bottom_instances > 0,
        "upper_tier_has_instances": upper_instances > 0,
        "both_tier_pdn_stages_passed": pdn_ok,
        "hbt_count_nonzero": hbt is not None and hbt > 0,
        "cross_tier_nets_nonzero": cross_tier is not None and cross_tier > 0,
        "mixed_fanout_metric_present": mixed is not None,
        "timing_metrics_present": wns is not None and tns is not None,
        "route_drc_zero": drc == 0,
        "spef_present": (RESULT_DIR / "6_final.spef").is_file(),
    }
    if args.mode == "full":
        checks["hotspot_temperature_present"] = temperature is not None
    passed = all(checks.values())

    lock = json.loads((ROOT / "versions.lock.json").read_text(encoding="utf-8"))
    version = lock["upstreams"]
    utilization = None
    if core_area not in (None, 0) and stdcell_area is not None and macro_area is not None:
        utilization = (stdcell_area + macro_area) / core_area
    summary = json.loads((ROOT / "config/signoff_summary.template.json").read_text(encoding="utf-8"))
    summary.update(
        {
            "run_id": os.environ["FLOW_RUN_ID"],
            "classification": "research_only",
            "versions": {
                "repository_commit": git_head(ROOT),
                "croc_commit": version["croc"]["commit"],
                "ihp_pdk_commit": version["ihp_open_pdk"]["commit"],
                "taiwei_commit": version["taiwei_pin_3d"]["commit"],
                "orfs_commit": version["orfs_research"]["commit"],
                "openroad_commit": version["pin3d_openroad"]["commit"],
                "container_reference": lock["container"]["reference"],
                "container_digest": lock["container"]["digest"],
            },
            "limitations": [
                "research_only: ASAP7 is a predictive research PDK and this result cannot be sent to a foundry.",
                "The F2F HBT stack is a physical-design abstraction, not a released hybrid-bonding process deck.",
                "Tier utilization remains null unless the upstream flow emits an independently attributable tier-area report.",
            ],
            "evidence": [
                str(output_metrics.relative_to(ROOT)),
                str((LOG_DIR / "final_summary.txt").relative_to(ROOT)),
                str((RESULT_DIR / "6_final.odb").relative_to(ROOT)),
                str((RESULT_DIR / "6_final.def").relative_to(ROOT)),
                str((RESULT_DIR / "6_final.spef").relative_to(ROOT)),
            ],
        }
    )
    summary["timing"].update({"corner": "ASAP7 research corner", "wns_ns": wns, "tns_ns": tns})
    summary["physical"].update(
        {
            "core_area_um2": core_area,
            "cell_area_um2": None if stdcell_area is None or macro_area is None else stdcell_area + macro_area,
            "utilization": utilization,
            "unrouted_nets": 0 if args.tool_returncode == 0 and drc == 0 else None,
            "pdn_connected": pdn_ok,
        }
    )
    summary["signoff"].update({"drc_unwaived": int(drc) if isinstance(drc, (int, float)) else None, "disabled_rules": []})
    summary["three_d"].update(
        {
            "bottom_instances": bottom_instances,
            "upper_instances": upper_instances,
            "cross_tier_nets": int(cross_tier) if isinstance(cross_tier, (int, float)) else None,
            "mixed_fanout_nets": mixed,
            "hbt_count": int(hbt) if isinstance(hbt, (int, float)) else None,
            "max_temperature_c": temperature,
        }
    )
    summary["power"].update({"estimated_mw": power, "activity_source": "upstream default activity assumptions" if power is not None else None})

    summary_path = run_dir / "pin3d_signoff_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stage_name = os.environ.get("FLOW_STAGE_INSTANCE", os.environ["FLOW_STAGE"])
    stage_evidence = run_dir / "stage_evidence" / f"{stage_name}.json"
    stage_evidence.parent.mkdir(parents=True, exist_ok=True)
    stage_evidence.write_text(
        json.dumps(
            {
                "status": "passed" if passed else "failed",
                "classification": "research_only",
                "mode": args.mode,
                "checks": checks,
                "missing": missing,
                "metrics": {"hbt_count": hbt, "cross_tier_nets": cross_tier, "mixed_fanout_nets": mixed, "wns_ns": wns, "tns_ns": tns, "drc": drc, "max_temperature_c": temperature},
                "summary": str(summary_path.relative_to(ROOT)),
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    for name, ok in checks.items():
        print(f"[PIN3D][{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
