#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Conservative, machine-readable acceptance checks for Croc stages."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


TIMING_COUNTS = {
    "setup_violations": "setup violation count",
    "hold_violations": "hold violation count",
    "max_slew_violations": "max slew violation count",
    "max_capacitance_violations": "max cap violation count",
    "max_fanout_violations": "max fanout violation count",
}


def final_timing(report: Path) -> dict:
    """Read explicit final-report metrics; missing or malformed data stays unknown.

    If a report contains several corner results, retain the worst observed
    value. These aggregate metrics do not establish corner/mode coverage.
    """
    values = {key: None for key in ("wns_ns", "tns_ns", *TIMING_COUNTS)}
    if not report.is_file():
        return values
    text = report.read_text(encoding="utf-8", errors="replace")
    for key, label in TIMING_COUNTS.items():
        tokens = re.findall(r"^[ \t]*" + re.escape(label) + r"\b[ \t]*([^\r\n]*)$", text, re.MULTILINE | re.IGNORECASE)
        if tokens and all(re.fullmatch(r"[0-9]+", item.strip()) for item in tokens):
            values[key] = max(int(item) for item in tokens)
    for key, label in (("wns_ns", "wns"), ("tns_ns", "tns")):
        tokens = re.findall(
            r"^[ \t]*" + label + r"(?:[ \t]+(?:max|min))?\b[ \t]*([^\r\n]*)$",
            text, re.MULTILINE | re.IGNORECASE,
        )
        tokens += re.findall(
            r"\breport_" + label + r"[^\n]*\n-+\s*\n\s*(\S+)\s*(?:\n|$)",
            text, re.IGNORECASE,
        )
        # A named metric line under a heading was already collected above.
        tokens = [item for item in tokens if item.lower() != label]
        try:
            numbers = [float(item) for item in tokens]
        except ValueError:
            numbers = []
        if numbers and all(math.isfinite(value) for value in numbers):
            values[key] = min(numbers)
    return values


def timing_checks(timing: dict) -> dict[str, bool]:
    """Shared stage/signoff gates: every required metric must be present."""
    checks = {}
    for key in ("wns_ns", "tns_ns"):
        value = timing.get(key)
        checks[key + "_nonnegative"] = (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0
        )
    for key in TIMING_COUNTS:
        value = timing.get(key)
        checks[key + "_zero"] = type(value) is int and value == 0
    return checks


def write_evidence(stage: str, payload: dict) -> None:
    run_dir = Path(os.environ["FLOW_RUN_DIR"])
    suffix = os.environ.get("FLOW_ATTEMPT_SUFFIX", "")
    target = run_dir / "stage_evidence" / f"croc-{stage}{suffix}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["rtl", "netlist-sim", "pnr", "gds"])
    args = parser.parse_args()
    run_dir = Path(os.environ["FLOW_RUN_DIR"])
    stage_name = os.environ.get("FLOW_STAGE_INSTANCE", os.environ["FLOW_STAGE"])
    log_path = run_dir / "logs" / f"{stage_name}.log"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    failures: list[str] = []
    evidence: dict = {
        "flow": "croc",
        "pdk": "sg13g2",
        "stage": args.stage,
        "checks": {},
        "failures": failures,
    }

    if args.stage == "rtl":
        hello = "Hello World from Croc!" in log
        evidence["checks"]["uart_signature"] = hello
        if not hello:
            failures.append("missing exact UART signature: Hello World from Croc!")
        binary = ROOT / "upstream/croc/sw/bin/helloworld.hex"
        evidence["checks"]["software_hex"] = binary.is_file() and binary.stat().st_size > 0
        if not evidence["checks"]["software_hex"]:
            failures.append("helloworld.hex is missing or empty")

    elif args.stage == "netlist-sim":
        netlist = ROOT / "upstream/croc/yosys/out/croc_yosys.v"
        evidence["checks"]["netlist_exists"] = netlist.is_file() and netlist.stat().st_size > 0
        evidence["checks"]["uart_signature"] = "Hello World from Croc!" in log
        bad_patterns = {
            "unresolved_reference": r"unresolved reference|module .* not found",
            "inferred_latch": r"inferred latch|latch inferred",
            "unsupported_sram_blackbox": r"tc_sram_blackbox",
        }
        for name, pattern in bad_patterns.items():
            hit = bool(re.search(pattern, log, re.IGNORECASE))
            evidence["checks"][name] = not hit
            if hit:
                failures.append(name)
        if not evidence["checks"]["netlist_exists"]:
            failures.append("synthesized netlist is missing")
        if not evidence["checks"]["uart_signature"]:
            failures.append("gate-level simulation lacks the exact UART signature")

    elif args.stage == "pnr":
        required = [
            ROOT / "upstream/croc/openroad/out/croc.def",
            ROOT / "upstream/croc/openroad/out/croc.odb",
            ROOT / "upstream/croc/openroad/out/croc.v",
            ROOT / "upstream/croc/openroad/out/croc_lvs.v",
            ROOT / "upstream/croc/openroad/out/croc.sdc",
            ROOT / "upstream/croc/openroad/reports/05_croc.final.rpt",
        ]
        missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file() or path.stat().st_size == 0]
        evidence["checks"]["required_outputs"] = not missing
        evidence["missing"] = missing
        failures.extend(f"missing {item}" for item in missing)
        error_hits = re.findall(r"(?:\[ERROR[^\]]*\]|unrouted\s+nets?\s*[:=]\s*[1-9]\d*)", log, re.IGNORECASE)
        evidence["checks"]["no_openroad_error"] = not error_hits
        if error_hits:
            failures.append("OpenROAD log contains errors or nonzero unrouted nets")
        acceptance_report = ROOT / "upstream/croc/openroad/reports/open3d_acceptance.rpt"
        acceptance = acceptance_report.read_text(encoding="utf-8", errors="replace") if acceptance_report.is_file() else ""
        routed = "design_is_routed=1" in acceptance
        pdn = "power_grid_VDD=1" in acceptance and "power_grid_VSS=1" in acceptance
        evidence["checks"]["unrouted_nets"] = 0 if routed else None
        evidence["checks"]["pdn_connected"] = pdn
        if not routed:
            failures.append("design_is_routed did not prove zero unrouted nets")
        if not pdn:
            failures.append("VDD/VSS power-grid connectivity was not proven")
        timing = final_timing(required[-1])
        evidence["timing"] = timing
        metric_checks = timing_checks(timing)
        evidence["checks"].update(metric_checks)
        for name, passed in metric_checks.items():
            if not passed:
                failures.append(f"final timing/electrical check failed or missing: {name}")

    elif args.stage == "gds":
        names = ["croc.gds.gz", "croc.sealed.gds.gz", "croc.metfilled.gds.gz", "croc.filled.gds.gz"]
        outputs = {name: ROOT / "upstream/croc/klayout/out" / name for name in names}
        evidence["outputs"] = {
            name: {"exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0}
            for name, path in outputs.items()
        }
        for name, item in evidence["outputs"].items():
            if not item["exists"] or item["bytes"] == 0:
                failures.append(f"missing or empty finalization output: {name}")

    evidence["status"] = "passed" if not failures else "failed"
    write_evidence(args.stage, evidence)
    if failures:
        for failure in failures:
            print(f"[ACCEPTANCE][FAIL] {failure}", file=sys.stderr)
        return 1
    print(f"[ACCEPTANCE][PASS] Croc {args.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
