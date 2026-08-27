#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate repository JSON contracts without requiring a network download."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


HEX32 = re.compile(r"^0x[0-9A-Fa-f]{8}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_traffic(data: dict) -> None:
    required = {
        "schema_version", "interface", "data_width_bits", "mode", "read_ratio",
        "address", "length_transactions", "stride_bytes", "response_latency_cycles",
        "max_outstanding", "seed",
    }
    require(set(data) == required, "traffic_spec keys do not match schema")
    require(data["schema_version"] == "1.0.0", "unsupported traffic schema")
    require(data["interface"] == "OBI-1.6", "interface must be OBI-1.6")
    require(data["data_width_bits"] == 32, "data width must be 32")
    require(data["mode"] in {"read", "write", "mixed"}, "invalid mode")
    ratio = data["read_ratio"]
    require(isinstance(ratio, (int, float)) and 0 <= ratio <= 1, "invalid read_ratio")
    if data["mode"] == "read":
        require(ratio == 1, "read mode requires read_ratio=1")
    elif data["mode"] == "write":
        require(ratio == 0, "write mode requires read_ratio=0")
    else:
        require(0 < ratio < 1, "mixed mode requires 0<read_ratio<1")
    address = data["address"]
    require(set(address) == {"base", "size_bytes", "alignment_bytes"}, "invalid address keys")
    require(bool(HEX32.fullmatch(address["base"])), "base must be an 8-digit hex address")
    require(int(address["base"], 16) == 0x20001000, "v1 base address is fixed at 0x20001000")
    require(address["size_bytes"] == 4096, "v1 control window is 4 KiB")
    require(address["alignment_bytes"] == 4, "v1 alignment is 4 bytes")
    require(isinstance(data["length_transactions"], int) and data["length_transactions"] > 0, "length must be positive")
    require(isinstance(data["stride_bytes"], int) and data["stride_bytes"] >= 4 and data["stride_bytes"] % 4 == 0, "stride must be a positive word multiple")
    require(isinstance(data["response_latency_cycles"], int) and data["response_latency_cycles"] >= 0, "latency must be non-negative")
    require(isinstance(data["max_outstanding"], int) and data["max_outstanding"] > 0, "max_outstanding must be positive")
    require(isinstance(data["seed"], int) and 0 <= data["seed"] <= 0xFFFFFFFF, "seed must be uint32")


def nullable(value: object, kind: type) -> bool:
    return value is None or (isinstance(value, kind) and not isinstance(value, bool))


def validate_signoff(data: dict) -> None:
    expected = {"schema_version", "run_id", "classification", "versions", "timing", "physical", "signoff", "three_d", "power", "limitations", "evidence"}
    require(set(data) == expected, "signoff_summary top-level keys do not match schema")
    require(data["schema_version"] == "1.0.0", "unsupported signoff schema")
    require(data["classification"] in {"not_run", "failed", "research_only", "public_rule_candidate", "public_rule_signoff"}, "invalid classification")
    versions = data["versions"]
    for key in ("repository_commit", "croc_commit", "ihp_pdk_commit", "taiwei_commit", "orfs_commit", "openroad_commit"):
        value = versions[key]
        require(value is None or bool(COMMIT.fullmatch(value)), f"invalid commit: {key}")
    digest_value = versions["container_digest"]
    require(digest_value is None or bool(DIGEST.fullmatch(digest_value)), "invalid container digest")
    require(isinstance(data["limitations"], list) and all(isinstance(x, str) for x in data["limitations"]), "limitations must be strings")
    require(isinstance(data["evidence"], list) and all(isinstance(x, str) for x in data["evidence"]), "evidence must be strings")
    disabled = data["signoff"]["disabled_rules"]
    require(isinstance(disabled, list) and all(isinstance(x, str) for x in disabled), "disabled_rules must be strings")
    if data["classification"] == "public_rule_signoff":
        signoff = data["signoff"]
        require(all(versions[key] is not None for key in ("repository_commit", "croc_commit", "ihp_pdk_commit")), "public_rule_signoff requires pinned repository/Croc/PDK commits")
        require(digest_value is not None, "public_rule_signoff requires an immutable container digest")
        require(disabled == [], "public_rule_signoff cannot disable rules")
        for key in ("drc_unwaived", "antenna_unwaived", "density_unwaived", "offgrid_unwaived"):
            require(signoff[key] == 0, f"public_rule_signoff requires {key}=0")
        require(signoff["lvs_exact_match"] is True, "public_rule_signoff requires exact LVS")
        require(data["physical"]["unrouted_nets"] == 0, "public_rule_signoff requires zero unrouted nets")
        require(data["physical"]["pdn_connected"] is True, "public_rule_signoff requires connected VDD/VSS PDN")
        require(data["timing"]["wns_ns"] is not None and data["timing"]["wns_ns"] >= 0, "public_rule_signoff requires non-negative WNS")
        require(data["timing"]["tns_ns"] is not None and data["timing"]["tns_ns"] >= 0, "public_rule_signoff requires non-negative TNS")
        for key in ("setup_violations", "hold_violations"):
            require(data["timing"][key] in (None, 0), f"public_rule_signoff requires {key}=0 when reported")
        require(bool(data["evidence"]), "public_rule_signoff requires evidence paths")
    if data["classification"] == "research_only":
        require(any("research" in item.lower() for item in data["limitations"]), "research_only must state its limitation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("schema", type=Path)
    parser.add_argument("document", type=Path)
    args = parser.parse_args()
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    data = json.loads(args.document.read_text(encoding="utf-8"))
    title = schema.get("title", "")
    if "traffic" in title.lower():
        validate_traffic(data)
    elif "signoff" in title.lower():
        validate_signoff(data)
    else:
        raise SystemExit(f"unsupported schema: {title}")
    print(f"[PASS] {args.document} conforms to {args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
