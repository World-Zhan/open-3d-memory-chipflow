#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only IO-ring PG pin/metal connectivity; no vias, devices, LVS or DRC."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import time
import klayout.db as kdb

LAYERS = {"Metal1": 8, "Metal2": 10, "Metal3": 30, "Metal4": 50,
          "Metal5": 67, "TopMetal1": 126, "TopMetal2": 134}
SUPPLIES = {"iovdd": "VDDIO", "iovss": "VSSIO", "vdd": "VDD", "vss": "VSS"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_region(layout, cell, number, purpose):
    index = layout.find_layer(number, purpose)
    return kdb.Region() if index is None else kdb.Region(cell.begin_shapes_rec(index))


def conductor(layout, cell, layer):
    number = LAYERS[layer]
    region = raw_region(layout, cell, number, 0) + raw_region(layout, cell, number, 22)
    region -= raw_region(layout, cell, number, 24)
    region -= raw_region(layout, cell, number, 29)
    if number in (126, 134):
        region -= raw_region(layout, cell, 27, 0)
    return region.merged()


def lef_macros(path):
    result = {}
    text = path.read_text()
    for match in re.finditer(r"^MACRO\s+(\S+)\s*$", text, re.M):
        name = match.group(1)
        end = re.search(r"^END\s+" + re.escape(name) + r"\s*$", text[match.end():], re.M)
        if end is None:
            raise ValueError("missing macro end: " + name)
        body = text[match.end():match.end()+end.start()]
        size = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", body)
        pins = {}
        for pin in SUPPLIES:
            part = re.search(r"^\s*PIN\s+" + pin + r"\s*$(.*?)^\s*END\s+" + pin + r"\s*$", body, re.M | re.S)
            if part is None:
                continue
            layer = None
            entries = {}
            for line in part.group(1).splitlines():
                tokens = line.strip().split()
                if tokens and tokens[0] == "LAYER":
                    layer = tokens[1]
                    if layer not in LAYERS:
                        raise ValueError("unhandled PG pin layer: " + layer)
                elif tokens and tokens[0] == "RECT":
                    entries.setdefault(layer, []).append([float(x) for x in tokens[1:5]])
                elif tokens and tokens[0] in ("POLYGON", "PATH", "VIA"):
                    raise ValueError("unhandled PG pin geometry: " + line)
            pins[pin] = entries
        result[name] = {"size": [float(size[1]), float(size[2])], "pins": pins}
    return result


def rect_region(rectangles, dbu):
    region = kdb.Region()
    for rectangle in rectangles:
        region.insert(kdb.Box(*[round(v / dbu) for v in rectangle]))
    return region.merged()


def bounds(box):
    return [box.left, box.bottom, box.right, box.top]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("/work"))
    parser.add_argument("--output", type=Path, default=Path("/output/pg_geometry.json"))
    args = parser.parse_args()
    started = time.monotonic()
    root = args.repo
    floor = root / "runs/croc-io-ring-floorplan-20260905-001"
    physical = root / "runs/croc-io-ring-physical-20260905-002"
    lef = root / "upstream/croc/technology/lef/sg13g2_io.lef"
    source_paths = [physical / "io_ring.gds", physical / "io_ring.def", floor / "instances.tsv", floor / "terminals.tsv", lef]
    deck = root / "upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks"
    source_paths += [deck / "layers_definitions.lvs", deck / "general_derivations.lvs"]
    sources = {str(p.relative_to(root)): sha(p) for p in source_paths}
    macros = lef_macros(lef)
    layout = kdb.Layout()
    layout.read(str(physical / "io_ring.gds"))
    top = layout.cell("io_ring")
    if top is None:
        raise ValueError("missing io_ring GDS top")
    dbu = layout.dbu
    rows = list(csv.DictReader((floor / "instances.tsv").open(), delimiter="\t"))
    expected = [r for r in rows if r["master"] != "bondpad70_m2_ring"]
    targets = {r["master"] for r in expected}
    assert sum(r["master"] == "sg13g2_Corner" for r in expected) == 4
    assert sum(r["master"].startswith("sg13g2_Filler") for r in expected) == 60
    assert sum(r["master"].startswith("sg13g2_IOPad") for r in expected) == 64
    actual = {}

    def walk(cell, transform, depth=0):
        if depth > 8:
            raise ValueError("unexpected hierarchy depth")
        for inst in cell.each_inst():
            for local in inst.cell_inst.each_trans():
                full = transform * local
                if inst.cell.name in targets:
                    size = macros[inst.cell.name]["size"]
                    box = kdb.Box(0, 0, round(size[0]/dbu), round(size[1]/dbu)).transformed(full)
                    key = (inst.cell.name, *[round(v*dbu*1000) for v in bounds(box)])
                    if key in actual:
                        raise ValueError("duplicate actual PG macro placement")
                    actual[key] = (inst.cell, full)
                elif inst.cell.name != "bondpad70_m2_ring":
                    walk(inst.cell, full, depth+1)

    walk(top, kdb.Trans())
    if len(actual) != 128 or len(expected) != 128:
        raise ValueError(f"expected 128 PG macros; actual={len(actual)}, DEF={len(expected)}")
    placements = {}
    for row in expected:
        key = (row["master"], *[int(row[k]) for k in ("xmin", "ymin", "xmax", "ymax")])
        cell, trans = actual[key]
        placements[row["name"]] = (row, cell, trans)
    terminals = list(csv.DictReader((floor / "terminals.tsv").open(), delimiter="\t"))
    pg_terms = [t for t in terminals if t["pin"] in SUPPLIES]
    assert len(pg_terms) == 512
    assert all(t["net"] == SUPPLIES[t["pin"]] and t["instance"] in placements for t in pg_terms)
    local_pins = {}
    for master in targets:
        assert set(macros[master]["pins"]) == set(SUPPLIES)
        local_pins[master] = {pin: {layer: rect_region(rects, dbu) for layer, rects in entries.items()}
                              for pin, entries in macros[master]["pins"].items()}
    records = []
    component_records = {}
    layer_stats = {}
    corner_contacts = []
    corners = [p for p in placements.values() if p[0]["master"] == "sg13g2_Corner"]
    adjacency = []
    for crow, _, _ in corners:
        c = [int(crow[k]) for k in ("xmin", "ymin", "xmax", "ymax")]
        neighbors = []
        for row, _, _ in placements.values():
            if row["name"] == crow["name"]:
                continue
            b = [int(row[k]) for k in ("xmin", "ymin", "xmax", "ymax")]
            vertical = (c[2] == b[0] or c[0] == b[2]) and min(c[3], b[3]) > max(c[1], b[1])
            horizontal = (c[3] == b[1] or c[1] == b[3]) and min(c[2], b[2]) > max(c[0], b[0])
            if vertical or horizontal:
                neighbors.append(row["name"])
        adjacency.append({"corner": crow["name"], "orientation": crow["orientation"], "neighbors": sorted(neighbors), "two_LEF_abutments": len(neighbors) == 2})

    for layer in LAYERS:
        whole = conductor(layout, top, layer)
        print(f"{layer}: {whole.count()} conductor components", flush=True)
        local_metal = {master: conductor(layout, layout.cell(master), layer) for master in targets}
        used_components = {}
        placed_port_metal = {}
        for name, (row, cell, trans) in placements.items():
            master = row["master"]
            for pin, entries in local_pins[master].items():
                if layer not in entries:
                    continue
                local_port = entries[layer]
                actual_port = local_port & local_metal[master]
                port = local_port.transformed(trans)
                placed_port_metal[(name, pin)] = actual_port.transformed(trans)
                hits = []
                for polygon in whole.interacting(port).each_merged():
                    intersection = kdb.Region(polygon) & port
                    if intersection.area() == 0:
                        continue
                    cid = hashlib.sha256(str(polygon).encode()).hexdigest()[:20]
                    hits.append(cid)
                    if cid not in used_components:
                        used_components[cid] = {"bbox_dbu": bounds(polygon.bbox()), "area_um2": polygon.area()*dbu*dbu, "supplies": set(), "instances": {s: set() for s in SUPPLIES.values()}}
                    used_components[cid]["supplies"].add(SUPPLIES[pin])
                    used_components[cid]["instances"][SUPPLIES[pin]].add(name)
                records.append({"instance": name, "pin": pin, "net": SUPPLIES[pin], "layer": layer,
                                "lef_rectangles": len(macros[master]["pins"][pin][layer]),
                                "lef_area_um2": local_port.area()*dbu*dbu,
                                "uncovered_in_own_macro_um2": (local_port-actual_port).area()*dbu*dbu,
                                "component_ids": sorted(hits)})
        for edge in adjacency:
            for neighbor in edge["neighbors"]:
                for pin, net in SUPPLIES.items():
                    left = placed_port_metal.get((edge["corner"], pin))
                    right = placed_port_metal.get((neighbor, pin))
                    if left is None and right is None:
                        continue
                    if left is None or right is None:
                        corner_contacts.append({"corner": edge["corner"], "neighbor": neighbor, "net": net, "layer": layer, "status": "pin_layer_not_present_on_both"})
                        continue
                    shared = left.edges() & right.edges()
                    length = sum(e.length() for e in shared.each()) * dbu
                    overlap = (left & right).area()*dbu*dbu
                    corner_contacts.append({"corner": edge["corner"], "neighbor": neighbor, "net": net, "layer": layer, "shared_boundary_um": length, "overlap_um2": overlap,
                                            "status": "physical_contact_observed" if length > 0 or overlap > 0 else "physical_contact_not_observed"})
        for cid, data in used_components.items():
            data["supplies"] = sorted(data["supplies"])
            data["instance_counts"] = {net: len(names) for net, names in data.pop("instances").items() if names}
        component_records[layer] = used_components
        layer_stats[layer] = {"conductor_components_total": whole.count(), "PG_touched_components": len(used_components)}
    summaries = {}
    for net in SUPPLIES.values():
        net_records = [r for r in records if r["net"] == net]
        layers = {}
        for layer in LAYERS:
            subset = [r for r in net_records if r["layer"] == layer]
            layers[layer] = {"pin_instances_present": len(subset), "pin_regions_without_metal": sum(not r["component_ids"] for r in subset),
                             "pin_regions_with_uncovered_LEF_area": sum(r["uncovered_in_own_macro_um2"] > 0 for r in subset),
                             "distinct_components": len({c for r in subset for c in r["component_ids"]}),
                             "all_128_instance_witness_components": [cid for cid, c in component_records[layer].items() if c["instance_counts"].get(net) == 128]}
        summaries[net] = {"logical_pin_instances": 128, "all_pin_layers_examined": True, "layers": layers,
                          "full_PG_electrical_closure": "not_proven_without_interlayer_and_internal_network_checks"}
    shorts = [{"layer": layer, "component": cid, "supplies": c["supplies"]} for layer, comps in component_records.items() for cid, c in comps.items() if len(c["supplies"]) > 1]
    output = {"classification": "io_ring_read_only_PG_geometry_not_electrical_signoff", "source_sha256": sources,
              "source_hashes_unchanged": sources == {str(p.relative_to(root)): sha(p) for p in source_paths},
              "klayout_version": kdb.__version__, "dbu_um": dbu, "elapsed_seconds": time.monotonic()-started,
              "logical_PG_terminals": 512, "actual_placed_macros_matched": 128, "instance_classes": {"IO": 64, "filler": 60, "corner": 4},
              "method": "Recursive actual GDS (drawing OR filler) minus slit and resistor marker, additionally minus inductor marker on top metals. Positive area pins map to actual same-layer connected polygons. Same names never merge polygons. Corner contact uses exact common boundary or positive area of actual pin metal.",
              "scope_exclusions": ["No via connectivity", "No device or well/substrate extraction", "No signal-net tracing", "No LVS or DRC", "No IR/EM", "No bondpad-to-PG supply path proof", "No core"],
              "layer_stats": layer_stats, "supplies": summaries, "same_layer_cross_supply_components": shorts,
              "corner_LEF_adjacencies": adjacency, "corner_GDS_contacts": corner_contacts,
              "pin_layer_mapping": records, "physical_components": component_records}
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"elapsed_seconds": output["elapsed_seconds"], "actual_macros": 128, "pin_layer_mappings": len(records), "cross_supply_components": len(shorts), "corner_contacts": len(corner_contacts)}), flush=True)


if __name__ == "__main__":
    main()
