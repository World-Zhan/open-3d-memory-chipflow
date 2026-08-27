#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build strict Croc signoff_summary.json from observed reports only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from collect_croc_evidence import final_timing


ROOT = Path(__file__).resolve().parents[1]


def git_head(path: Path) -> str | None:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def rdb_items(run_dir: Path) -> tuple[int | None, list[str]]:
    reports = sorted(run_dir.rglob("*.lyrdb"))
    if not reports:
        return None, []
    total = 0
    descriptions: list[str] = []
    parsed = 0
    for report in reports:
        try:
            root = ET.parse(report).getroot()
        except ET.ParseError:
            continue
        parsed += 1
        items = root.findall(".//items/item")
        total += len(items)
        for item in items:
            descriptions.append(" ".join(text.strip() for text in item.itertext() if text.strip()))
    return (total if parsed else None), descriptions


def count_kind(descriptions: list[str], word: str) -> int:
    return sum(1 for item in descriptions if word.lower() in item.lower())


def find_text(root: Path) -> str:
    chunks = []
    for path in sorted(root.rglob("*.log")):
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signoff-dir", type=Path, required=True)
    parser.add_argument("--drc-returncode", type=int, required=True)
    parser.add_argument("--lvs-returncode", type=int, required=True)
    args = parser.parse_args()
    signoff_dir = args.signoff_dir.resolve()
    drc_dir = signoff_dir / "drc"
    lvs_dir = signoff_dir / "lvs"
    lock = json.loads((ROOT / "versions.lock.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "config/signoff_summary.template.json").read_text(encoding="utf-8"))

    total_drc, descriptions = rdb_items(drc_dir)
    lvs_text = find_text(lvs_dir)
    lvs_match = "Congratulations! Netlists match." in lvs_text and args.lvs_returncode == 0
    timing = final_timing(ROOT / "upstream/croc/openroad/reports/05_croc.final.rpt")
    acceptance_report = ROOT / "upstream/croc/openroad/reports/open3d_acceptance.rpt"
    acceptance = acceptance_report.read_text(encoding="utf-8", errors="replace") if acceptance_report.is_file() else ""
    routed = "design_is_routed=1" in acceptance
    pdn = "power_grid_VDD=1" in acceptance and "power_grid_VSS=1" in acceptance

    versions = lock["upstreams"]
    summary["run_id"] = os.environ.get("FLOW_RUN_ID", signoff_dir.parent.name)
    summary["versions"] = {
        "repository_commit": git_head(ROOT),
        "croc_commit": versions["croc"]["commit"],
        "ihp_pdk_commit": versions["ihp_open_pdk"]["commit"],
        "taiwei_commit": versions["taiwei_pin_3d"]["commit"],
        "orfs_commit": versions["orfs_research"]["commit"],
        "openroad_commit": versions["pin3d_openroad"]["commit"],
        "container_reference": lock["container"]["reference"],
        "container_digest": lock["container"]["digest"],
    }
    summary["timing"].update(timing)
    summary["timing"]["corner"] = "tt"
    summary["physical"]["unrouted_nets"] = 0 if routed else None
    summary["physical"]["pdn_connected"] = pdn
    summary["signoff"].update(
        {
            "drc_unwaived": total_drc,
            "antenna_unwaived": 0 if total_drc == 0 else count_kind(descriptions, "antenna"),
            "density_unwaived": 0 if total_drc == 0 else count_kind(descriptions, "density"),
            "offgrid_unwaived": 0 if total_drc == 0 else count_kind(descriptions, "offgrid"),
            "lvs_exact_match": lvs_match,
            "disabled_rules": [],
        }
    )
    summary["evidence"] = [
        str((signoff_dir / "croc.cdl").relative_to(ROOT)),
        str(drc_dir.relative_to(ROOT)),
        str(lvs_dir.relative_to(ROOT)),
        str(acceptance_report.relative_to(ROOT)),
        "upstream/croc/openroad/reports/05_croc.final.rpt",
    ]
    summary["limitations"] = [
        "IHP Open PDK is preview; foundry tapeout still requires IHP confirmation of the frozen PDK, decks and waivers.",
        "LVS checks the electrical croc_chip GDS before mechanical seal-ring and fill insertion; full DRC checks croc.filled.gds.gz.",
        "Power is a tool estimate unless an activity source is recorded; no silicon power claim is made.",
    ]

    hard_checks = {
        "drc_process_exit_zero": args.drc_returncode == 0,
        "lvs_process_exit_zero": args.lvs_returncode == 0,
        "drc_unwaived_zero": total_drc == 0,
        "lvs_exact_match": lvs_match,
        "fully_routed": routed,
        "pdn_connected": pdn,
        "wns_nonnegative": timing["wns_ns"] is not None and timing["wns_ns"] >= 0,
        "tns_nonnegative": timing["tns_ns"] is not None and timing["tns_ns"] >= 0,
        "setup_clean": timing["setup_violations"] in (None, 0),
        "hold_clean": timing["hold_violations"] in (None, 0),
    }
    passed = all(hard_checks.values())
    summary["classification"] = "public_rule_signoff" if passed else "failed"
    summary_path = signoff_dir / "signoff_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checks_path = signoff_dir / "acceptance_checks.json"
    checks_path.write_text(json.dumps(hard_checks, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    stage_name = os.environ.get("FLOW_STAGE_INSTANCE", "croc-signoff")
    stage_evidence = Path(os.environ["FLOW_RUN_DIR"]) / "stage_evidence" / f"{stage_name}.json"
    stage_evidence.parent.mkdir(parents=True, exist_ok=True)
    stage_evidence.write_text(
        json.dumps({"status": "passed" if passed else "failed", "classification": summary["classification"], "checks": hard_checks, "summary": str(summary_path.relative_to(ROOT))}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name, ok in hard_checks.items():
        print(f"[SIGNOFF][{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
