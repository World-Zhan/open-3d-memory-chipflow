#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict-deep LVS diagnosis for the two diode leaves used by SG13G2 IO pads.

The runner exports one official GDS leaf and one exact official CDL subcircuit
per case.  It preserves strict ports, tap extraction, simplification and every
guard/substrate device.  It never enables implicit nets, top-port ignores,
waivers, layout-netlist bypasses, or any full-chip flow.
"""

from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any

from analyze_small_lvsdb import (
    DEFAULT_MAX_BYTES,
    analyze as analyze_lvsdb,
    enforce_size_limit,
    sha256_file,
)
from run_lvs_iopad_diagnostic import (
    parse_subckt_statements,
    statements_referencing,
)
from run_lvs_pin_boundary_ab import (
    IMAGE_DIGEST,
    IMAGE_REFERENCE,
    PDK_COMMIT,
    build_variant_command,
    explicit_option_state,
    extract_subckt_block,
    file_record,
    validate_strict_command,
    variant_result,
)


LEAF_CASES = (
    {
        "cell": "sg13g2_DCNDiode",
        "split_net": "cathode",
        "device_class": "dantenna",
    },
    {
        "cell": "sg13g2_DCPDiode",
        "split_net": "anode",
        "device_class": "dpantenna",
    },
)
FORBIDDEN_OR_UNUSED_OPTIONS = (
    "--ignore_top_ports_mismatch",
    "--implicit_nets",
    "--no_simplify",
    "--disable_tap_extraction",
    "--layout_netlist",
)
ABSTRACT_OPTION_NAMES = {
    "--abstract",
    "--blackbox",
    "--cheat",
    "--flatten",
    "--flatten-cell",
    "--selective-flatten",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def matching_lines(text: str, pattern: str) -> list[dict[str, Any]]:
    expression = re.compile(pattern, re.IGNORECASE)
    return [
        {"line": number, "text": line.strip()}
        for number, line in enumerate(text.splitlines(), start=1)
        if expression.search(line)
    ]


def scan_public_support(
    runner_text: str,
    readme_text: str,
    tap_extraction_text: str,
    tap_derivations_text: str,
    main_runset_text: str,
    regression_paths: list[str],
) -> dict[str, Any]:
    """Classify only documented/public mechanisms; do not infer a workaround."""
    public_text = runner_text + "\n" + readme_text
    documented_options = sorted(set(re.findall(r"--[a-zA-Z0-9_-]+", public_text)))
    abstract_candidates = sorted(ABSTRACT_OPTION_NAMES.intersection(documented_options))
    io_leaf_names = {case["cell"].lower() for case in LEAF_CASES}
    regression_matches = sorted(
        path for path in regression_paths if any(name in path.lower() for name in io_leaf_names)
    )
    tap_cheat_lines = matching_lines(tap_extraction_text, r"cheat\(\"\*\"\)")
    tap_rehierarchy_lines = matching_lines(
        tap_derivations_text, r"re-hierarchisation|cheats"
    )
    sram_cheat_lines = matching_lines(main_runset_text, r"cheat\(SRAM_SHAREDSD_CELLS\)")
    return {
        "documented_user_options": documented_options,
        "documented_run_modes": ["flat", "deep"],
        "documented_io_leaf_abstract_or_selective_flatten_options": abstract_candidates,
        "supported_io_leaf_abstract_or_selective_flatten_found": bool(
            abstract_candidates
        ),
        "official_dcn_dcp_regression_fixture_paths": regression_matches,
        "official_dcn_dcp_regression_fixture_found": bool(regression_matches),
        "internal_tap_cheat": {
            "present": bool(tap_cheat_lines),
            "scope": "automatic deck-internal cell-local ntap1/ptap1 extraction in deep mode",
            "user_selectable_io_leaf_abstraction": False,
            "evidence": tap_cheat_lines,
            "rehierarchisation_evidence": tap_rehierarchy_lines,
        },
        "sram_specific_cheat": {
            "present": bool(sram_cheat_lines),
            "relevant_to_io_leaf_cases": False,
            "evidence": sram_cheat_lines,
        },
        "documented_but_disallowed_or_unused": {
            "--disable_tap_extraction": "would remove required tap devices; not used",
            "--layout_netlist": "would bypass layout extraction; not used",
            "--implicit_nets": "forbidden for this strict diagnostic; not used",
            "--ignore_top_ports_mismatch": "forbidden; not used",
            "--no_simplify": "strict diagnostic keeps simplify enabled; not used",
        },
        "conclusion": (
            "public runner supports flat/deep hierarchy only; no documented IO-leaf "
            "abstract, blackbox, cheat option, or selective-flatten control was found"
        ),
    }


def collect_public_support(repo: Path) -> dict[str, Any]:
    lvs = repo / "upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/lvs"
    sources = {
        "runner": lvs / "run_lvs.py",
        "readme": lvs / "README.md",
        "tap_extraction": lvs / "rule_decks/tap_extraction.lvs",
        "tap_derivations": lvs / "rule_decks/tap_derivations.lvs",
        "main_runset": lvs / "sg13g2.lvs",
    }
    testing = lvs / "testing"
    regression_paths = [
        str(path.relative_to(repo))
        for path in testing.rglob("*")
        if path.is_file()
    ]
    result = scan_public_support(
        sources["runner"].read_text(encoding="utf-8", errors="replace"),
        sources["readme"].read_text(encoding="utf-8", errors="replace"),
        sources["tap_extraction"].read_text(encoding="utf-8", errors="replace"),
        sources["tap_derivations"].read_text(encoding="utf-8", errors="replace"),
        sources["main_runset"].read_text(encoding="utf-8", errors="replace"),
        regression_paths,
    )
    result["sources"] = {
        name: file_record(path, repo) for name, path in sources.items()
    }
    return result


def build_minimal_cdl(library_text: str, cell_name: str) -> str:
    block = extract_subckt_block(library_text, cell_name)
    return (
        "* Exact official sg13g2_io leaf extracted for strict-deep LVS\n"
        f"* Top cell: {cell_name}\n"
        f"{block}"
    )


def export_minimal_gds(
    source_gds: Path, cell_name: str, output_gds: Path
) -> dict[str, Any]:
    import klayout.db as kdb

    layout = kdb.Layout()
    layout.read(str(source_gds))
    cell = layout.cell(cell_name)
    if cell is None:
        raise ValueError(f"GDS cell {cell_name} not found")
    labels: list[dict[str, Any]] = []
    shape_counts: collections.Counter[str] = collections.Counter()
    for layer_index in layout.layer_indices():
        info = layout.get_info(layer_index)
        shapes = cell.shapes(layer_index)
        count = shapes.size()
        if count:
            shape_counts[f"{info.layer}/{info.datatype}"] += count
        for shape in shapes.each():
            if shape.is_text():
                text = shape.text
                labels.append(
                    {
                        "text": text.string,
                        "layer": info.layer,
                        "datatype": info.datatype,
                        "x_dbu": text.trans.disp.x,
                        "y_dbu": text.trans.disp.y,
                    }
                )
    options = kdb.SaveLayoutOptions()
    options.select_this_cell(cell.cell_index())
    output_gds.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(output_gds), options)
    return {
        "source_cell": cell_name,
        "source_cell_index": cell.cell_index(),
        "source_layout_dbu": layout.dbu,
        "bbox_dbu": [cell.bbox().left, cell.bbox().bottom, cell.bbox().right, cell.bbox().top],
        "direct_shape_counts_by_layer_datatype": dict(sorted(shape_counts.items())),
        "direct_text_labels": labels,
        "export_selection": "SaveLayoutOptions.select_this_cell; leaf only, no wrapper",
    }


def build_gds_input_identity(
    source_gds_record: dict[str, Any],
    generated_gds_record: dict[str, Any],
    layout_manifest: dict[str, Any],
    cell_name: str,
) -> dict[str, Any]:
    """Separate stable source identity from run-specific GDSII file bytes."""
    return {
        "identity_semantics": (
            "stable identity is the pinned official source GDS SHA-256, PDK commit, "
            "source cell name, and recorded geometry facts; it is not the generated "
            "GDS raw SHA-256"
        ),
        "stable_source_cell_identity": {
            "ihp_pdk_commit": PDK_COMMIT,
            "official_source_gds_sha256": source_gds_record["sha256"],
            "official_source_gds_bytes": source_gds_record["bytes"],
            "source_cell": cell_name,
            "source_layout_dbu": layout_manifest["source_layout_dbu"],
            "source_cell_bbox_dbu": layout_manifest["bbox_dbu"],
            "direct_shape_counts_by_layer_datatype": layout_manifest[
                "direct_shape_counts_by_layer_datatype"
            ],
            "direct_text_label_count": len(layout_manifest["direct_text_labels"]),
            "export_selection": layout_manifest["export_selection"],
        },
        "run_specific_generated_file": {
            "path": generated_gds_record["path"],
            "bytes": generated_gds_record["bytes"],
            "raw_sha256": generated_gds_record["sha256"],
            "raw_sha256_scope": (
                "run-specific byte identity; GDSII BGNLIB/BGNSTR timestamps may change "
                "across equivalent exports"
            ),
            "bitwise_deterministic_across_exports": False,
        },
        "semantic_geometry_digest_claimed": False,
    }


def build_leaf_detail(
    cell_name: str,
    split_net: str,
    device_class: str,
    schematic: Path,
    extracted: Path,
    layout_manifest: dict[str, Any],
) -> dict[str, Any]:
    schematic_statements = parse_subckt_statements(schematic, cell_name)
    extracted_statements = parse_subckt_statements(extracted, cell_name)
    split_name = f"{split_net}$1"
    schematic_device_statements = [
        statement
        for statement in schematic_statements
        if device_class.lower() in statement.lower()
    ]
    extracted_device_statements = [
        statement
        for statement in extracted_statements
        if device_class.lower() in statement.lower()
    ]
    label_counts = collections.Counter(
        item["text"] for item in layout_manifest["direct_text_labels"]
    )
    return {
        "cell": cell_name,
        "expected_single_schematic_net": split_net,
        "observed_split_net": split_name,
        "schematic_references": statements_referencing(
            schematic_statements, split_net
        ),
        "extracted_base_net_references": statements_referencing(
            extracted_statements, split_net
        ),
        "extracted_split_net_references": statements_referencing(
            extracted_statements, split_name
        ),
        "schematic_device_statements": schematic_device_statements,
        "extracted_device_statements": extracted_device_statements,
        "gds_direct_text_count_for_split_net": label_counts.get(split_net, 0),
        "gds_direct_text_labels": layout_manifest["direct_text_labels"],
        "split_net_reproduced": bool(
            statements_referencing(extracted_statements, split_name)
        ),
        "interpretation": (
            f"official {cell_name} CDL expects one {split_net} net; strict-deep "
            f"extraction exposes {split_net} and {split_name} components"
        ),
    }


def xref_report(path: Path, sample_limit: int = 100) -> dict[str, Any]:
    size = enforce_size_limit(path, DEFAULT_MAX_BYTES)
    return {
        "schema_version": "1.1.0",
        "generated_at": utc_now(),
        "analysis_mode": "bounded_klayout_layout_vs_schematic_cross_reference",
        "source_lvsdb": str(path),
        "source_bytes": size,
        "source_sha256": sha256_file(path),
        "configured_max_bytes": DEFAULT_MAX_BYTES,
        "sample_limit_per_object_kind_per_circuit": sample_limit,
        "full_chip_lvsdb_loading_forbidden": True,
        **analyze_lvsdb(path, sample_limit),
    }


def build_conclusion(cases: list[dict[str, Any]], support: dict[str, Any]) -> dict[str, Any]:
    split_cells = sorted(
        case["cell"] for case in cases if case["detail"]["split_net_reproduced"]
    )
    strict_pass_cells = sorted(
        case["cell"] for case in cases if case["result"].get("status") == "PASS"
    )
    strict_fail_cells = sorted(
        case["cell"] for case in cases if case["result"].get("status") == "FAIL"
    )
    return {
        "strict_lvs_pass_cells": strict_pass_cells,
        "strict_lvs_fail_cells": strict_fail_cells,
        "official_leaf_network_split_reproduced_cells": split_cells,
        "both_target_splits_reproduced": len(split_cells) == len(LEAF_CASES),
        "public_io_leaf_abstract_or_selective_flatten_supported": support[
            "supported_io_leaf_abstract_or_selective_flatten_found"
        ],
        "root_cause_state": (
            "official_io_leaf_gds_cdl_network_split_reproduced_"
            "intent_or_deck_resolution_not_identified"
        ),
        "root_cause_fully_identified": False,
        "full_chip_135057_port_mismatch_attributed_to_io_only": False,
        "full_chip_attempt_3_authorized": False,
        "next_gate": (
            "determine whether the official leaf geometry expects parent-metal closure "
            "or requires an upstream PDK/deck fix; no documented abstraction bypass exists"
        ),
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
        summary["conclusion"] = build_conclusion(
            summary["cases"], summary["public_pdk_deck_support_audit"]
        )
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)
        print(summary_path)
        return 0

    pdk = repo / "upstream/ihp-open-pdk/ihp-sg13g2"
    source_gds = pdk / "libs.ref/sg13g2_io/gds/sg13g2_io.gds"
    source_cdl = pdk / "libs.ref/sg13g2_io/cdl/sg13g2_io.cdl"
    runner = pdk / "libs.tech/klayout/tech/lvs/run_lvs.py"
    library_text = source_cdl.read_text(encoding="utf-8", errors="replace")
    source_gds_record = file_record(source_gds, repo)
    source_cdl_record = file_record(source_cdl, repo)
    support = collect_public_support(repo)
    summary: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "classification": "in_progress",
        "purpose": "strict_deep_official_io_diode_leaf_network_split_diagnosis",
        "container_reference": IMAGE_REFERENCE,
        "container_digest": IMAGE_DIGEST,
        "container_command": args.container_command,
        "script_invocation": shlex.join([sys.executable, *sys.argv]),
        "ihp_pdk_commit": PDK_COMMIT,
        "strictness": {
            **explicit_option_state("deep", False),
            "tap_extraction_enabled": True,
            "layout_netlist_bypass": False,
            "waivers": [],
            "forbidden_or_unused_options": list(FORBIDDEN_OR_UNUSED_OPTIONS),
        },
        "official_inputs": {
            "io_gds": source_gds_record,
            "io_cdl": source_cdl_record,
            "runner": file_record(runner, repo),
        },
        "public_pdk_deck_support_audit": support,
        "cases": [],
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(summary_path, summary)

    for specification in LEAF_CASES:
        cell_name = specification["cell"]
        case_dir = run_dir / cell_name
        inputs_dir = case_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        layout_path = inputs_dir / f"{cell_name}.gds"
        schematic_path = inputs_dir / f"{cell_name}.cdl"
        layout_manifest = export_minimal_gds(source_gds, cell_name, layout_path)
        schematic_path.write_text(
            build_minimal_cdl(library_text, cell_name), encoding="utf-8"
        )
        generated_layout_record = file_record(layout_path, repo)
        command = build_variant_command(
            sys.executable,
            runner,
            layout_path,
            schematic_path,
            case_dir,
            "deep",
            False,
            top_cell=cell_name,
        )
        validate_strict_command(command)
        (case_dir / "command.txt").write_text(
            shlex.join(command) + "\n", encoding="utf-8"
        )
        with (case_dir / "runner-console.log").open(
            "w", encoding="utf-8"
        ) as log_stream:
            completed = subprocess.run(
                command,
                cwd=repo,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        extracted = case_dir / f"{cell_name}_extracted.cir"
        layout_log = case_dir / f"{cell_name}.log"
        lvsdb = case_dir / f"{cell_name}.lvsdb"
        result = variant_result(
            cell_name,
            "deep",
            False,
            command,
            completed.returncode,
            schematic_path,
            extracted,
            layout_log,
            top_cell=cell_name,
        )
        result["requested_options"].update(
            {
                "tap_extraction_enabled": True,
                "layout_netlist_bypass": False,
                "waivers": [],
            }
        )
        xref = xref_report(lvsdb)
        xref_path = case_dir / "lvsdb_cross_reference.json"
        write_json(xref_path, xref)
        detail = build_leaf_detail(
            cell_name,
            specification["split_net"],
            specification["device_class"],
            schematic_path,
            extracted,
            layout_manifest,
        )
        case = {
            "cell": cell_name,
            "split_net": specification["split_net"],
            "device_class": specification["device_class"],
            "inputs": {
                "generated_layout": {
                    **generated_layout_record,
                    "sha256_scope": (
                        "run-specific byte identity; GDSII BGNLIB/BGNSTR timestamps "
                        "may change across equivalent exports"
                    ),
                    "bitwise_deterministic_across_exports": False,
                },
                "generated_schematic": file_record(schematic_path, repo),
            },
            "gds_input_identity": build_gds_input_identity(
                source_gds_record,
                generated_layout_record,
                layout_manifest,
                cell_name,
            ),
            "layout_manifest": layout_manifest,
            "result": result,
            "detail": detail,
            "cross_reference": {
                "path": str(xref_path.relative_to(run_dir)),
                "source_bytes": xref["source_bytes"],
                "source_sha256": xref["source_sha256"],
                "summary": xref["summary"],
            },
            "artifacts": {
                "command": str((case_dir / "command.txt").relative_to(run_dir)),
                "runner_console_log": str(
                    (case_dir / "runner-console.log").relative_to(run_dir)
                ),
                "layout_log": str(layout_log.relative_to(run_dir)),
                "extracted_netlist": str(extracted.relative_to(run_dir)),
                "lvsdb": str(lvsdb.relative_to(run_dir)),
                "lvsdb_cross_reference": str(xref_path.relative_to(run_dir)),
            },
        }
        summary["cases"].append(case)
        summary["generated_at"] = utc_now()
        write_json(summary_path, summary)

    summary["classification"] = "complete_root_cause_not_fully_identified"
    summary["conclusion"] = build_conclusion(summary["cases"], support)
    summary["generated_at"] = utc_now()
    write_json(summary_path, summary)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
