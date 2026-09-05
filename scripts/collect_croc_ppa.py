#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Collect qualified PPA from immutable Croc archives; never run EDA or grant signoff."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from collect_croc_evidence import final_timing, timing_checks

ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def number(token):
    try:
        value = float(token)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def scalar(text, label, suffix=""):
    tokens = re.findall(r"^\s*" + re.escape(label) + r"\s*([^\s]+)" + suffix + r"\s*$", text, re.M)
    values = [number(token) for token in tokens]
    return values[0] if values and None not in values and len(set(values)) == 1 else None


def parse_area(text):
    result = {key: scalar(text, label, r"\s+um2") for key, label in {
        "die_area_um2": "Die Area:", "core_area_um2": "Core Area:",
        "instance_area_um2": "Total Area:", "active_area_um2": "Total Active Area:",
    }.items()}
    result["core_utilization"] = scalar(text, "Core Utilization:")
    result["stdcell_utilization"] = scalar(text, "Std Cell Utilization:")
    result["hierarchy_um2"] = {}
    for label in ("<top>", "i_croc_soc", "i_core_wrap", "i_core.register_file_i"):
        rows = re.findall(r"^\s*" + re.escape(label) + r"\s+([^\n]+)$", text, re.M)
        if len(rows) == 1:
            values = [number(token) for token in rows[0].split()[:5]]
            if len(values) == 5 and None not in values:
                result["hierarchy_um2"][label] = dict(zip(("total", "stdcell", "macro", "cover", "pad"), values))
    return result


def parse_power(text):
    results = []
    for heading, body in re.findall(r"^([^\n]*report_power\s+\S+)\n-+\n(.*?)(?=^=+\s*$|\Z)", text, re.M | re.S):
        if not re.search(r"Power\s+\(Watts\)", body):
            continue
        groups = {}
        for line in body.splitlines():
            match = re.fullmatch(r"(Sequential|Combinational|Clock|Macro|Pad|Total)\s+(.+?)\s+\d+(?:\.\d+)?%", line.strip())
            if match:
                values = [number(token) for token in match[2].split()]
                if len(values) == 4 and None not in values:
                    groups[match[1].lower()] = dict(zip(("internal", "switching", "leakage", "total"), [round(v * 1000, 12) for v in values]))
        results.append({"corner": heading.split()[-1], "units": "mW", "groups": groups})
    return results


def parse_def(text):
    units = re.search(r"^UNITS DISTANCE MICRONS ([0-9]+)\s*;", text, re.M)
    die = re.search(r"^DIEAREA\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;", text, re.M)
    result = {"dbu_per_um": None, "die_width_um": None, "die_height_um": None, "die_area_um2": None,
              "sram_macro_count": None, "sram_bytes": None, "sram_cells": []}
    if units and int(units[1]) > 0 and die:
        scale = int(units[1])
        x1, y1, x2, y2 = map(int, die.groups())
        if x2 > x1 and y2 > y1:
            width, height = (x2 - x1) / scale, (y2 - y1) / scale
            result.update(dbu_per_um=scale, die_width_um=width, die_height_um=height, die_area_um2=width * height)
    components = re.search(r"^COMPONENTS\s+[0-9]+\s*;(.*?)^END COMPONENTS", text, re.M | re.S)
    if components:
        matches = re.findall(r"^\s*-\s+\S+\s+(RM_IHPSG13_1P_([0-9]+)x([0-9]+)_\S+)\s", components[1], re.M)
        if matches:
            result["sram_macro_count"] = len(matches)
            result["sram_cells"] = sorted(set(m[0] for m in matches))
            result["sram_bytes"] = sum(int(m[1]) * int(m[2]) for m in matches) // 8
    return result


def parse_clocks(text):
    clocks = {}
    for line in text.splitlines():
        if not line.lstrip().startswith("create_clock "):
            continue
        name = re.search(r"-name\s+(?:\{([^{}]+)\}|(\S+))", line)
        period = re.search(r"-period\s+(\S+)", line)
        value = number(period[1]) if period else None
        if name and value is not None and value > 0:
            clocks[name[1] or name[2]] = {"period_ns": value, "constraint_frequency_mhz": 1000 / value}
    return clocks


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def delta(current, previous):
    """Raw area deltas are allowed only for matching technology, design and SRAM.

    Power cannot be called an improvement without qualified activity/PVT/parasitics.
    A constraint change cannot be called a achieved-frequency improvement.
    """
    if previous is None:
        return {"status": "initial_baseline", "previous_report": None, "metrics": {}}
    context = current["comparison_context"]
    compatible = (context == previous.get("comparison_context")
                  and all(context.get(key) is not None for key in ("design", "technology", "pdk_commit", "sram_bytes", "area_scope")))
    metrics = {}
    for key in ("die_area_um2", "core_area_um2", "active_area_um2", "instance_area_um2"):
        before, after = previous.get("area", {}).get(key), current["area"].get(key)
        valid = compatible and type(before) in (float, int) and type(after) in (float, int) and all(math.isfinite(v) and v >= 0 for v in (before, after))
        metrics[key] = {"before": before, "after": after, "delta": after - before if valid else None,
                        "percent": (after / before - 1) * 100 if valid and before > 0 else None,
                        "comparable": valid}
    current_hash = current["sources"]["final_report"]["sha256"]
    same = current_hash is not None and current_hash == previous.get("sources", {}).get("final_report", {}).get("sha256")
    status = "physical_report_unavailable" if current_hash is None else ("same_physical_report_reused" if same else "new_analysis_report")
    return {"status": status,
            "previous_report": previous.get("report_id"), "metrics": metrics,
            "power_delta_mw": None, "achieved_frequency_delta_mhz": None,
            "limitations": ["Power activity/PVT/parasitics and achieved frequency are unqualified; no improvement claim.",
                            "An area reduction is descriptive until function and signoff regressions pass."]}


def collect(source_run, report_id, signoff_path=None, previous=None):
    source_run = source_run.resolve()
    pnr = source_run / "artifacts/pnr/upstream/croc/openroad"
    paths = {"final_report": pnr / "reports/05_croc.final.rpt", "def": pnr / "out/croc.def",
             "sdc": pnr / "out/croc.sdc", "finishing_log": pnr / "logs/05_finishing.log",
             "manifest": source_run / "manifest.json"}
    if signoff_path:
        paths["signoff_summary"] = signoff_path.resolve()
    texts = {key: path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "" for key, path in paths.items()}
    manifest = json.loads(texts["manifest"]) if texts["manifest"] else {}
    locked = manifest.get("locked_versions", {})
    versions = locked.get("upstreams", {})
    timing = final_timing(paths["final_report"])
    checks = timing_checks(timing)
    area, geometry = parse_area(texts["final_report"]), parse_def(texts["def"])
    signoff = json.loads(texts["signoff_summary"]) if texts.get("signoff_summary") else {}
    if signoff and signoff.get("run_id") != source_run.name:
        raise ValueError("signoff summary must belong to source run")
    power = parse_power(texts["final_report"])
    tt = [row for row in power if row["corner"] == "tt"]
    total = tt[0]["groups"].get("total", {}).get("total") if len(tt) == 1 else None
    observed_version = texts["finishing_log"].splitlines()[0] if texts["finishing_log"] else None
    payload = {
        "schema_version": "1.0.0", "report_id": report_id, "source_run_id": source_run.name,
        "status": "unqualified_ppa_baseline", "eda_rerun_performed_by_collector": False,
        "comparison_context": {"design": "croc_chip", "technology": locked.get("policy", {}).get("croc_pdk"),
                               "pdk_commit": versions.get("ihp_open_pdk", {}).get("commit"),
                               "sram_bytes": geometry["sram_bytes"], "area_scope": "whole_die_and_physical_core_separately"},
        "sources": {key: {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                          "sha256": sha(path) if path.is_file() else None,
                          "available": path.is_file()} for key, path in paths.items()},
        "versions": {"croc_commit": versions.get("croc", {}).get("commit"), "openroad_observed_log": observed_version,
                     "container": locked.get("container", {}).get("digest")},
        "area": area, "def_geometry": geometry,
        "area_crosscheck": {"report_matches_def_die": area["die_area_um2"] is not None and geometry["die_area_um2"] is not None and abs(area["die_area_um2"] - geometry["die_area_um2"]) < 0.001},
        "performance": {"clocks": parse_clocks(texts["sdc"]), "timing": timing,
                        "time_unit": "ns", "time_unit_basis": "Croc SG13G2 flow convention; collector does not infer units from SDC",
                        "achieved_frequency_mhz": None, "coremark_per_mhz": None,
                        "parasitics": "not_qualified_by_collector", "complete_corner_mode_coverage": None},
        "power": {"estimated_tt_total_mw": total, "reports": power, "method": "OpenSTA report_power tool estimate",
                  "activity_source": None, "activity_coverage": None, "workload": None, "voltage_v": None,
                  "temperature_c": None, "signoff_qualified": False, "measured_silicon_mw": None},
        "acceptance": {"electrical_passed": all(checks.values()), "electrical_checks": checks,
                       "signoff": signoff.get("signoff", {}), "public_rule_signoff_proven_by_collector": False,
                       "tapeout_ready": False},
        "limitations": ["Archived reports are estimates from an electrically and physically unclosed design; no tapeout acceptance.",
                        "1000/clock_period is a requested clock constraint, never measured or signoff-guaranteed Fmax.",
                        "No workload VCD/SAIF, activity coverage, extracted-RC qualification, full MMMC, IR/EM or DFT qualification is established here.",
                        "Instance area includes pad/cover cells; active area, physical core area and die area are different scopes.",
                        "SRAM bytes are inferred from physical macro names, not a functional memory test."]}
    payload["delta"] = delta(payload, previous)
    return payload


def attach_probe(payload, probe_run, previous=None):
    """Attach an independently archived, non-layout-changing RCX probe.

    Validate the manifest's input and output hashes before reusing old DEF/DRC.
    A changed-layout experiment needs its own physical archive, not this adapter.
    """
    probe_run = probe_run.resolve()
    manifest_path = probe_run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not (manifest.get("status") == "completed" and manifest.get("returncode") == 0
            and manifest.get("layout_modified") is False and manifest.get("source_hashes_unchanged") is True):
        raise ValueError("probe must be completed with unchanged layout and source hashes")
    for suffix in ("out/croc.odb", "out/croc.sdc"):
        path = ROOT / "runs" / payload["source_run_id"] / "artifacts/pnr/upstream/croc/openroad" / suffix
        expected = manifest.get("source_sha256", {}).get(str(path.relative_to(ROOT)))
        if expected is None or not path.is_file() or sha(path) != expected:
            raise ValueError("probe source identity mismatch: " + suffix)
    required = ("probe_extracted_typ_rc.rpt", "tt_power.rpt", "ff_power.rpt", "tool.log", "croc.typ.spef")
    for name in required:
        path = probe_run / name
        expected = manifest.get("outputs_sha256", {}).get(name)
        if expected is None or not path.is_file() or sha(path) != expected:
            raise ValueError("probe output hash mismatch: " + name)
    report = probe_run / required[0]
    report_text = report.read_text()
    area = parse_area(report_text)
    if area != payload["area"]:
        raise ValueError("probe report area differs from archived layout")
    payload["sources"]["baseline_final_report"] = payload["sources"]["final_report"]
    for key, path in {"final_report": report, "probe_manifest": manifest_path,
                      "probe_tt_power": probe_run / "tt_power.rpt", "probe_ff_power": probe_run / "ff_power.rpt",
                      "probe_tool_log": probe_run / "tool.log", "probe_spef": probe_run / "croc.typ.spef"}.items():
        payload["sources"][key] = {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "available": True}
    timing = final_timing(report)
    payload["status"] = "unqualified_extracted_rc_ppa"
    payload["diagnostic_run_id"] = manifest["run_id"]
    payload["performance"]["timing"] = timing
    payload["performance"]["parasitics"] = manifest.get("parasitic_scope")
    payload["performance"]["complete_corner_mode_coverage"] = False
    payload["power"]["reports"] = []
    for corner in ("tt", "ff"):
        text = (probe_run / (corner + "_power.rpt")).read_text()
        payload["power"]["reports"] += parse_power("probe report_power " + corner + "\n----\n" + text)
    tt = [row for row in payload["power"]["reports"] if row["corner"] == "tt"]
    payload["power"]["estimated_tt_total_mw"] = tt[0]["groups"].get("total", {}).get("total") if len(tt) == 1 else None
    payload["power"]["activity_source"] = manifest.get("activity_source")
    payload["acceptance"]["electrical_checks"] = timing_checks(timing)
    payload["acceptance"]["electrical_passed"] = all(payload["acceptance"]["electrical_checks"].values())
    payload["versions"]["probe_tool_first_line"] = (probe_run / "tool.log").read_text().splitlines()[0]
    payload["delta"] = delta(payload, previous)
    payload["delta"]["layout_modified"] = False
    before = previous.get("power", {}).get("estimated_tt_total_mw") if previous else None
    after = payload["power"]["estimated_tt_total_mw"]
    payload["delta"]["raw_tt_estimate_change_mw"] = round(after - before, 12) if before is not None and after is not None else None
    payload["delta"]["raw_tt_estimate_change_interpretation"] = "Analysis/parasitic-model change on unchanged layout; not a design power improvement."
    payload["limitations"].append("This probe establishes single-model SPEF extraction/readback, not RC-corner qualification or full MMMC; inherited DRC/LVS remain failed.")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--signoff-summary", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--probe-run", type=Path, help="Completed non-layout-changing Croc RCX diagnostic archive")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous else None
    result = collect(args.source_run, args.report_id, args.signoff_summary, previous)
    if args.probe_run:
        result = attach_probe(result, args.probe_run, previous)
    content = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(content)
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
