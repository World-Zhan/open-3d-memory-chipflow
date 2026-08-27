#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Aggregate immutable run manifests into Markdown, JSON and image indexes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def find_summary(run_dir: Path) -> tuple[Path | None, dict | None]:
    candidates = [
        run_dir / "signoff/signoff_summary.json",
        run_dir / "pin3d_signoff_summary.json",
    ]
    for path in candidates:
        data = read_json(path)
        if data is not None:
            return path, data
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runs_root = (ROOT / args.runs).resolve() if not args.runs.is_absolute() else args.runs.resolve()
    output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    records = []
    images = []
    for manifest_path in sorted(runs_root.glob("*/manifest.json")):
        manifest = read_json(manifest_path)
        if manifest is None:
            continue
        run_dir = manifest_path.parent
        summary_path, summary = find_summary(run_dir)
        record = {
            "run_id": manifest.get("run_id", run_dir.name),
            "created_at": manifest.get("created_at"),
            "stages": manifest.get("stages", []),
            "summary_path": str(summary_path.relative_to(ROOT)) if summary_path else None,
            "classification": summary.get("classification") if summary else None,
            "signoff_summary": summary,
        }
        records.append(record)
        for image in sorted(run_dir.rglob("*.png")):
            images.append({"run_id": record["run_id"], "path": str(image.relative_to(ROOT))})

    aggregate = {
        "schema_version": "1.0.0",
        "run_count": len(records),
        "runs": records,
        "image_count": len(images),
        "images": images,
    }
    (output / "runs_summary.json").write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# 芯片流程运行汇总",
        "",
        "本页只汇总实际存在的 manifest。`classification` 为空表示尚未产生签核汇总；它不等于通过。",
        "",
        "| Run ID | 阶段 | 状态 | 分类 | 关键指标 |",
        "|---|---|---|---|---|",
    ]
    for record in records:
        stages = ", ".join(f"{item.get('name')}={item.get('status')}" for item in record["stages"]) or "—"
        classification = record["classification"] or "not_reported"
        summary = record["signoff_summary"] or {}
        timing = summary.get("timing", {})
        signoff = summary.get("signoff", {})
        three_d = summary.get("three_d", {})
        metrics = []
        for label, value in (
            ("WNS(ns)", timing.get("wns_ns")),
            ("TNS(ns)", timing.get("tns_ns")),
            ("DRC", signoff.get("drc_unwaived")),
            ("LVS", signoff.get("lvs_exact_match")),
            ("HBT", three_d.get("hbt_count")),
            ("cross-tier", three_d.get("cross_tier_nets")),
            ("Tmax(C)", three_d.get("max_temperature_c")),
        ):
            if value is not None:
                metrics.append(f"{label}={value}")
        lines.append(f"| `{record['run_id']}` | {stages} | {'passed' if all(s.get('status') == 'passed' for s in record['stages']) else 'incomplete/failed'} | `{classification}` | {', '.join(metrics) or '—'} |")
    if not records:
        lines.append("| — | — | 没有实际运行 | `not_run` | — |")

    lines.extend(
        [
            "",
            "## 用词边界",
            "",
            "- `public_rule_signoff` 仅由 Croc/IHP 严格验收器生成。",
            "- `research_only` 永远不能解释为可制造或 foundry signoff。",
            "- IHP Open PDK 仍为 preview；公开规则清零也不替代 foundry/MPW 审核。",
            "",
        ]
    )
    (output / "runs_summary.md").write_text("\n".join(lines), encoding="utf-8")

    image_lines = ["# 关键版图截图索引", ""]
    if images:
        for item in images:
            image_lines.append(f"- `{item['run_id']}`: [{item['path']}](../../{item['path']})")
    else:
        image_lines.append("尚无已归档 PNG；这不是版图通过的证据。")
    image_lines.append("")
    (output / "layout_images.md").write_text("\n".join(image_lines), encoding="utf-8")
    print(f"[REPORT] {len(records)} runs, {len(images)} images -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
