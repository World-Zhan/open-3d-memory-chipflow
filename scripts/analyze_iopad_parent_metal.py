#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit whether official SG13G2 IO parent M1 closes diode leaf access regions.

This is a bounded, read-only geometry analysis.  It does not run LVS, alter the
PDK/deck, flatten cells, hide substrate/tap devices, or authorize a full-chip
retry.  KLayout's Python module is required and is supplied by the pinned
iic-osic-tools container used by the project.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import sys
from typing import Any, Iterable

from analyze_small_lvsdb import sha256_file
from run_lvs_iopad_diagnostic import parse_subckt_statements
from run_lvs_pin_boundary_ab import IMAGE_DIGEST, IMAGE_REFERENCE, PDK_COMMIT


PARENT_CELL = "sg13g2_IOPadIn"
TARGETS = (
    {
        "leaf_cell": "sg13g2_DCNDiode",
        "split_net": "cathode",
        "parent_net": "pad",
    },
    {
        "leaf_cell": "sg13g2_DCPDiode",
        "split_net": "anode",
        "parent_net": "pad",
    },
)
M1_CONDUCTOR_LAYERS = ((8, 0), (8, 22))
M1_TEXT_LAYER = (8, 25)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_record(path: Path, repo: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(repo)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def shape_polygon(shape: Any, kdb: Any) -> Any | None:
    if shape.is_box():
        return kdb.Polygon(shape.box)
    if shape.is_polygon():
        return shape.polygon
    if shape.is_path():
        return shape.path.polygon()
    return None


def direct_region(layout: Any, cell: Any, layer_specs: Iterable[tuple[int, int]], kdb: Any) -> Any:
    region = kdb.Region()
    for layer, datatype in layer_specs:
        layer_index = layout.find_layer(layer, datatype)
        if layer_index is None:
            continue
        for shape in cell.shapes(layer_index).each():
            polygon = shape_polygon(shape, kdb)
            if polygon is not None:
                region.insert(polygon)
    return region.merged()


def region_components(region: Any) -> list[Any]:
    return list(region.each_merged())


def polygon_contains_point(polygon: Any, point: Any, kdb: Any) -> bool:
    if not polygon.bbox().contains(point):
        return False
    probe = kdb.Region(kdb.Box(point.x, point.y, point.x + 1, point.y + 1))
    return not (kdb.Region(polygon) & probe).is_empty()


def component_for_point(components: list[Any], point: Any, kdb: Any) -> int | None:
    for index, polygon in enumerate(components):
        if polygon_contains_point(polygon, point, kdb):
            return index
    return None


def intersects(left: Any, right: Any, kdb: Any) -> bool:
    return not (kdb.Region(left) & kdb.Region(right)).is_empty()


def shared_parent_components(touch_sets: list[list[int]]) -> list[int]:
    if not touch_sets:
        return []
    shared = set(touch_sets[0])
    for values in touch_sets[1:]:
        shared.intersection_update(values)
    return sorted(shared)


def labels_on_component(
    layout: Any, cell: Any, component: Any, layer_spec: tuple[int, int], kdb: Any
) -> list[dict[str, Any]]:
    layer_index = layout.find_layer(*layer_spec)
    if layer_index is None:
        return []
    labels = []
    for shape in cell.shapes(layer_index).each():
        if not shape.is_text():
            continue
        text = shape.text
        point = text.trans.disp
        if polygon_contains_point(component, point, kdb):
            labels.append(
                {"text": text.string, "x_dbu": point.x, "y_dbu": point.y}
            )
    return labels


def matching_parent_statement(cdl: Path, parent_cell: str, leaf_cell: str) -> str:
    statements = parse_subckt_statements(cdl, parent_cell)
    matches = [line for line in statements if leaf_cell.lower() in line.lower()]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {leaf_cell} statement in {parent_cell}, got {matches}"
        )
    return matches[0]


def find_direct_leaf_instance(parent: Any, leaf_name: str) -> Any:
    matches = [inst for inst in parent.each_inst() if inst.cell.name == leaf_name]
    if len(matches) != 1:
        raise ValueError(
            f"expected one direct {leaf_name} instance in {parent.name}, got {len(matches)}"
        )
    return matches[0]


def analyze_target(layout: Any, parent: Any, cdl: Path, target: dict[str, str], kdb: Any) -> dict[str, Any]:
    leaf = layout.cell(target["leaf_cell"])
    if leaf is None:
        raise ValueError(f"missing GDS cell {target['leaf_cell']}")
    instance = find_direct_leaf_instance(parent, target["leaf_cell"])
    if instance.is_regular_array() or instance.is_complex():
        raise ValueError("bounded audit only accepts one simple direct leaf instance")

    leaf_components = region_components(
        direct_region(layout, leaf, M1_CONDUCTOR_LAYERS, kdb)
    )
    parent_components = region_components(
        direct_region(layout, parent, M1_CONDUCTOR_LAYERS, kdb)
    )
    text_layer = layout.find_layer(*M1_TEXT_LAYER)
    if text_layer is None:
        raise ValueError("M1 text layer 8/25 is absent")

    label_points = []
    for shape in leaf.shapes(text_layer).each():
        if shape.is_text() and shape.text.string == target["split_net"]:
            point = shape.text.trans.disp
            component_id = component_for_point(leaf_components, point, kdb)
            if component_id is None:
                raise ValueError(
                    f"{target['leaf_cell']} label {target['split_net']} is not on M1"
                )
            label_point = kdb.Point(point.x, point.y)
            transformed = instance.trans * label_point
            label_points.append(
                {
                    "leaf_x_dbu": point.x,
                    "leaf_y_dbu": point.y,
                    "parent_x_dbu": transformed.x,
                    "parent_y_dbu": transformed.y,
                    "leaf_component_id": component_id,
                }
            )

    target_component_ids = sorted(
        {item["leaf_component_id"] for item in label_points}
    )
    touch_sets: list[list[int]] = []
    component_records = []
    for component_id in target_component_ids:
        transformed_polygon = leaf_components[component_id].transformed(instance.trans)
        touching = [
            parent_id
            for parent_id, parent_polygon in enumerate(parent_components)
            if intersects(transformed_polygon, parent_polygon, kdb)
        ]
        touch_sets.append(touching)
        component_records.append(
            {
                "leaf_component_id": component_id,
                "leaf_bbox_dbu": list(leaf_components[component_id].bbox().to_s().replace("(", "").replace(")", "").replace(";", ",").split(",")),
                "touching_parent_component_ids": touching,
            }
        )

    shared = shared_parent_components(touch_sets)
    shared_records = [
        {
            "parent_component_id": parent_id,
            "bbox": parent_components[parent_id].bbox().to_s(),
            "direct_m1_labels": labels_on_component(
                layout, parent, parent_components[parent_id], M1_TEXT_LAYER, kdb
            ),
        }
        for parent_id in shared
    ]
    return {
        "parent_cell": parent.name,
        "leaf_cell": target["leaf_cell"],
        "split_net": target["split_net"],
        "expected_parent_net": target["parent_net"],
        "official_parent_cdl_statement": matching_parent_statement(
            cdl, parent.name, target["leaf_cell"]
        ),
        "instance_transform": str(instance.trans),
        "m1_conductor_layers": [list(item) for item in M1_CONDUCTOR_LAYERS],
        "m1_text_layer": list(M1_TEXT_LAYER),
        "split_label_count": len(label_points),
        "split_label_points": label_points,
        "distinct_leaf_access_component_count": len(target_component_ids),
        "leaf_access_components": component_records,
        "shared_parent_component_ids": shared,
        "shared_parent_components": shared_records,
        "official_parent_direct_m1_closure_observed": len(shared) > 0,
    }


def build_conclusion(targets: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [
        item["leaf_cell"]
        for item in targets
        if item["official_parent_direct_m1_closure_observed"]
    ]
    both = len(closed) == len(TARGETS)
    return {
        "official_parent_direct_m1_closure_cells": sorted(closed),
        "both_target_parent_closures_observed": both,
        "parent_metal_closure_lvs_ab_gate_open": both,
        "root_cause_fully_identified": False,
        "full_chip_attempt_3_authorized": False,
        "next_gate": (
            "run exactly one strict-deep parent-metal closure variant per leaf, using existing leaf LVS as A"
            if both
            else "package the official leaf GDS/CDL/deck mismatch as a reproducible upstream blocker"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container-command", default=None)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = args.output.resolve()

    import klayout.db as kdb

    pdk = repo / "upstream/ihp-open-pdk/ihp-sg13g2"
    gds = pdk / "libs.ref/sg13g2_io/gds/sg13g2_io.gds"
    cdl = pdk / "libs.ref/sg13g2_io/cdl/sg13g2_io.cdl"
    layer_deck = pdk / "libs.tech/klayout/tech/lvs/rule_decks/layers_definitions.lvs"
    layout = kdb.Layout()
    layout.read(str(gds))
    parent = layout.cell(PARENT_CELL)
    if parent is None:
        raise ValueError(f"missing GDS parent {PARENT_CELL}")
    targets = [analyze_target(layout, parent, cdl, item, kdb) for item in TARGETS]
    payload = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "classification": "complete_geometry_gate",
        "purpose": "official_iopad_parent_direct_m1_closure_evidence",
        "analysis_mode": "bounded_read_only_direct_parent_geometry",
        "container_reference": IMAGE_REFERENCE,
        "container_digest": IMAGE_DIGEST,
        "container_command": args.container_command,
        "script_invocation": shlex.join([sys.executable, *sys.argv]),
        "ihp_pdk_commit": PDK_COMMIT,
        "strictness_boundary": {
            "lvs_run_performed": False,
            "deck_modified": False,
            "flattening": False,
            "implicit_nets": False,
            "ignore_top_ports_mismatch": False,
            "waivers": [],
            "full_chip_attempt_3": False,
        },
        "official_inputs": {
            "io_gds": file_record(gds, repo),
            "io_cdl": file_record(cdl, repo),
            "layer_definitions": file_record(layer_deck, repo),
            "croc_pad_usage": file_record(repo / "upstream/croc/rtl/croc_chip.sv", repo),
            "croc_pad_ring": file_record(repo / "upstream/croc/openroad/src/padring.tcl", repo),
        },
        "targets": targets,
        "conclusion": build_conclusion(targets),
    }
    write_json(output, payload)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
