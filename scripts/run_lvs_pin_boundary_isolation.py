#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Isolate strict deep-LVS behavior of one inverter and one IO pad cell."""

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

from run_lvs_pin_boundary_ab import (
    IMAGE_DIGEST,
    IMAGE_REFERENCE,
    PDK_COMMIT,
    build_variant_command,
    explicit_option_state,
    variant_result,
)


CASES = (
    {
        "name": "inverter_only",
        "top_cell": "sg13g2_inv_1",
        "layout": "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds",
        "schematic": "libs.ref/sg13g2_stdcell/cdl/sg13g2_stdcell.cdl",
    },
    {
        "name": "io_pad_only",
        "top_cell": "sg13g2_IOPadIn",
        "layout": "libs.ref/sg13g2_io/gds/sg13g2_io.gds",
        "schematic": "libs.ref/sg13g2_io/cdl/sg13g2_io.cdl",
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
    return {
        "path": str(path.relative_to(root)),
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_conclusion(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {result["name"]: result for result in results}
    inverter = by_name.get("inverter_only", {})
    io_pad = by_name.get("io_pad_only", {})
    io_extra = sorted(
        set(io_pad.get("extracted_port_order", []))
        - set(io_pad.get("schematic_port_order", []))
    )
    io_missing = sorted(
        set(io_pad.get("schematic_port_order", []))
        - set(io_pad.get("extracted_port_order", []))
    )
    scope_narrowed = (
        inverter.get("status") == "PASS"
        and io_pad.get("status") == "FAIL"
        and len(io_extra) == 1
        and not io_missing
    )
    return {
        "inverter_strict_lvs_pass": inverter.get("status") == "PASS",
        "io_pad_strict_lvs_pass": io_pad.get("status") == "PASS",
        "io_pad_extra_extracted_formal_ports": io_extra,
        "io_pad_missing_schematic_formal_ports": io_missing,
        "scope_narrowed_to_io_pad_hierarchy": scope_narrowed,
        "remaining_mismatch_isolated_to_io_substrate_boundary": scope_narrowed
        and io_extra == ["$1"],
        "substrate_only_hypothesis_confirmed": scope_narrowed and io_extra == ["$1"],
        "observed_split_io_net": io_extra[0] if scope_narrowed else None,
        "root_cause_fully_identified": False,
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
    pdk = repo / "upstream/ihp-open-pdk/ihp-sg13g2"
    runner = pdk / "libs.tech/klayout/tech/lvs/run_lvs.py"
    summary_path = run_dir / "summary.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.summarize_existing:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["classification"] = "complete"
        summary["conclusion"] = build_conclusion(summary["cases"])
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)
        print(summary_path)
        return 0

    summary: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "classification": "in_progress",
        "purpose": "strict_deep_lvs_io_substrate_isolation",
        "analysis_mode": "streaming_spice_headers_and_logs_no_lvsdb_load",
        "container_reference": IMAGE_REFERENCE,
        "container_digest": IMAGE_DIGEST,
        "ihp_pdk_commit": PDK_COMMIT,
        "strictness": explicit_option_state("deep", False),
        "cases": [],
    }
    write_json(summary_path, summary)

    for case in CASES:
        case_dir = run_dir / case["name"]
        case_dir.mkdir(parents=True, exist_ok=True)
        layout = pdk / case["layout"]
        schematic = pdk / case["schematic"]
        command = build_variant_command(
            sys.executable,
            runner,
            layout,
            schematic,
            case_dir,
            "deep",
            False,
            top_cell=case["top_cell"],
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
        layout_stem = layout.name.split(".")[0]
        extracted = case_dir / f"{layout_stem}_extracted.cir"
        layout_log = case_dir / f"{layout_stem}.log"
        result = variant_result(
            case["name"],
            "deep",
            False,
            command,
            completed.returncode,
            schematic,
            extracted,
            layout_log,
            top_cell=case["top_cell"],
        )
        result["top_cell"] = case["top_cell"]
        result["inputs"] = {
            "layout": file_record(layout, repo),
            "schematic": file_record(schematic, repo),
        }
        result["artifacts"] = {
            "command": str((case_dir / "command.txt").relative_to(run_dir)),
            "runner_console_log": str((case_dir / "runner-console.log").relative_to(run_dir)),
            "layout_log": str(layout_log.relative_to(run_dir)) if layout_log.exists() else None,
            "extracted_netlist": str(extracted.relative_to(run_dir)) if extracted.exists() else None,
            "lvsdb": str((case_dir / f"{layout_stem}.lvsdb").relative_to(run_dir))
            if (case_dir / f"{layout_stem}.lvsdb").exists()
            else None,
        }
        summary["cases"].append(result)
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)

    summary["classification"] = "complete"
    summary["conclusion"] = build_conclusion(summary["cases"])
    summary["generated_at"] = utc_now()
    write_json(summary_path, summary)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
