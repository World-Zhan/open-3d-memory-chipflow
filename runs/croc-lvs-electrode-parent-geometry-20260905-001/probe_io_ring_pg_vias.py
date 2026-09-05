#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Trace only PG-seeded actual metal/via components; no device extraction/LVS."""
from __future__ import annotations
import argparse
from collections import Counter, deque
import csv
import hashlib
import json
from pathlib import Path
import re
import time
import klayout.db as kdb
from probe_io_ring_pg import LAYERS, SUPPLIES, conductor, raw_region, sha, bounds, rect_region

VIA_STACK = [("Via1", 19, "Metal1", "Metal2"), ("Via2", 29, "Metal2", "Metal3"),
             ("Via3", 49, "Metal3", "Metal4"), ("Via4", 66, "Metal4", "Metal5"),
             ("TopVia1", 125, "Metal5", "TopMetal1"), ("TopVia2", 133, "TopMetal1", "TopMetal2")]


def polygon_id(polygon):
    return hashlib.sha256(str(polygon).encode()).hexdigest()[:20]


def positive_overlap_polygons(candidates, region):
    """Retain whole conductor/cut polygons only if they overlap by positive area."""
    result = kdb.Region()
    for polygon in candidates.interacting(region).each_merged():
        if (kdb.Region(polygon) & region).area() > 0:
            result.insert(polygon)
    return result


def derive_topvia1(raw, vmim, mim):
    return (raw - ((vmim + raw) & mim)).merged()


def validate_geometry_failures():
    """Known geometry cases prevent virtual ties and cut-set false bridges."""
    box = lambda *v: kdb.Region(kdb.Box(*v))
    checks = []
    lower = box(0, 0, 10, 10)
    upper = box(0, 0, 10, 10)
    cuts = box(2, 2, 4, 4)
    selected = positive_overlap_polygons(cuts, lower)
    assert positive_overlap_polygons(upper, selected).count() == 1
    checks.append("same_actual_cut_joins_two_overlapping_metals")
    disconnected_upper = box(20, 0, 30, 10)
    disjoint_cuts = cuts + box(22, 2, 24, 4)
    selected = positive_overlap_polygons(disjoint_cuts, lower)
    assert positive_overlap_polygons(disconnected_upper, selected).is_empty()
    checks.append("two_different_cuts_cannot_create_a_cross_layer_bridge")
    touching_cut = box(10, 2, 12, 4)
    assert positive_overlap_polygons(touching_cut, lower).is_empty()
    checks.append("edge_only_cut_contact_is_not_positive_area_connection")
    eligible = derive_topvia1(disjoint_cuts, kdb.Region(), box(0, 0, 10, 10))
    assert eligible.count() == 1 and (eligible & cuts).is_empty()
    checks.append("MIM_TopVia1_removed_while_unrelated_TopVia1_remains")
    graph = UnionFind()
    assert graph.find("VDD-pin-a") != graph.find("VDD-pin-b")
    checks.append("identical_expected_supply_names_do_not_union_disconnected_nodes")
    graph.union("VDD-pin-a", "VSS-pin-a")
    assert graph.find("VDD-pin-a") == graph.find("VSS-pin-a")
    assert graph.find("VDD-pin-b") != graph.find("VDD-pin-a")
    checks.append("actual_cross_supply_edge_is_detectable_without_hiding_disconnected_pin")
    return {"classification": "synthetic_geometry_failure_cases_not_chip_validation", "cases_passed": len(checks), "cases": checks}


def bondpad_pins(path, dbu):
    text = path.read_text()
    part = re.search(r"^\s*PIN\s+pad\s*$(.*?)^\s*END\s+pad\s*$", text, re.M | re.S)
    assert part
    entries = {}
    layer = None
    for line in part.group(1).splitlines():
        tokens = line.strip().split()
        if tokens and tokens[0] == "LAYER":
            layer = tokens[1]
            assert layer in LAYERS
        elif tokens and tokens[0] == "RECT":
            entries.setdefault(layer, []).append([float(x) for x in tokens[1:5]])
        elif tokens and tokens[0] in ("POLYGON", "PATH", "VIA"):
            raise ValueError("Unhandled bondpad pin geometry")
    assert set(entries) == set(LAYERS) - {"Metal1"}
    return {layer: rect_region(rectangles, dbu) for layer, rectangles in entries.items()}


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, node):
        if node not in self.parent:
            self.parent[node] = node
        while node != self.parent[node]:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("/work"))
    parser.add_argument("--output", type=Path, default=Path("/output/pg_via_graph.json"))
    args = parser.parse_args()
    started = time.monotonic()
    validation = validate_geometry_failures()
    args.output.with_name("validation_cases.json").write_text(json.dumps(validation, indent=2, sort_keys=True)+"\n")
    root = args.repo
    physical = root / "runs/croc-io-ring-physical-20260905-002"
    old_path = root / "runs/croc-io-ring-pg-20260905-001/pg_geometry.json"
    helper_path = root / "reports/bondpad/probe_io_ring_pg.py"
    floor_instances = root / "runs/croc-io-ring-floorplan-20260905-001/instances.tsv"
    bond_lef = root / "runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.lef"
    deck = root / "upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks"
    sources = [old_path, helper_path, floor_instances, bond_lef, physical / "io_ring.gds", physical / "io_ring.def", physical / "lead_boxes.tsv"]
    sources += [deck / x for x in ("layers_definitions.lvs", "general_derivations.lvs", "general_connections.lvs", "cap_derivations.lvs")]
    hashes = {str(p.relative_to(root)): sha(p) for p in sources}
    old = json.loads(old_path.read_text())
    assert old["source_sha256"][str((physical/"io_ring.gds").relative_to(root))] == sha(physical/"io_ring.gds")
    assert old["source_hashes_unchanged"] and old["actual_placed_macros_matched"] == 128
    assert all(p["uncovered_in_own_macro_um2"] == 0 and p["component_ids"] for p in old["pin_layer_mapping"])
    assert sha(Path(__file__).with_name("probe_io_ring_pg.py")) == sha(helper_path)
    cap_text = (deck / "cap_derivations.lvs").read_text()
    assert "mim_via = vmim_drw.join(topvia1_drw).and(mim_drw)" in cap_text
    assert "topvia1_n_cap = topvia1_drw.not(mim_via)" in cap_text
    layout = kdb.Layout()
    layout.read(str(physical / "io_ring.gds"))
    top = layout.cell("io_ring")
    assert top is not None
    dbu = layout.dbu
    metals = {layer: conductor(layout, top, layer) for layer in LAYERS}
    polygons = {layer: {polygon_id(p): p for p in region.each_merged()} for layer, region in metals.items()}
    assert all(len(polygons[layer]) == metals[layer].count() for layer in LAYERS), "nonunique polygon hashes"
    vias = {}
    via_stats = {}
    for name, number, lower, upper in VIA_STACK:
        raw = raw_region(layout, top, number, 0).merged()
        valid = raw
        if name == "TopVia1":
            mim = raw_region(layout, top, 36, 0)
            vmim = raw_region(layout, top, 129, 0)
            valid = derive_topvia1(raw, vmim, mim)
        vias[name] = valid
        via_stats[name] = {"layer": [number, 0], "lower_metal": lower, "upper_metal": upper,
                           "raw_merged_polygons": raw.count(), "connection_eligible_polygons": valid.count(),
                           "excluded_area_um2": (raw-valid).area()*dbu*dbu}
    print(json.dumps({"phase": "derived_actual_layers", "metal_components": {l: r.count() for l, r in metals.items()}, "via_polygons": {v: r.count() for v, r in vias.items()}}), flush=True)
    # Node names are geometric layer + component IDs. Net labels never create graph edges.
    seeds = {net: set() for net in SUPPLIES.values()}
    pin_nodes = []
    for record in old["pin_layer_mapping"]:
        nodes = []
        for cid in record["component_ids"]:
            assert cid in polygons[record["layer"]]
            node = record["layer"] + ":" + cid
            nodes.append(node)
            seeds[record["net"]].add(node)
        pin_nodes.append({"instance": record["instance"], "pin": record["pin"], "net": record["net"], "layer": record["layer"], "nodes": nodes})
    # Supply bondpads are identified from the physical DEF and lead table, not from the earlier unconnected floorplan TSV.
    lead_rows = list(csv.DictReader((physical/"lead_boxes.tsv").open(), delimiter="\t"))
    supply_leads = [r for r in lead_rows if r["net"] in seeds]
    assert len(supply_leads) == 96
    pad_nets = {}
    for r in supply_leads:
        assert r["bond"] not in pad_nets or pad_nets[r["bond"]] == r["net"]
        pad_nets[r["bond"]] = r["net"]
    assert len(pad_nets) == 16 and Counter(pad_nets.values()) == {n: 4 for n in seeds}
    def_text = (physical/"io_ring.def").read_text()
    for pad, net in pad_nets.items():
        mappings = []
        for match in re.finditer(r"^\s*-\s+(\S+)\s+(.*?);", def_text, re.M | re.S):
            if re.search(r"\(\s*" + re.escape(pad) + r"\s+pad\s*\)", match.group(2)):
                mappings.append(match.group(1))
        assert mappings == [net], (pad, mappings, net)
        assert {r["layer"] for r in supply_leads if r["bond"] == pad} == set(LAYERS)-{"Metal1"}
    rows = list(csv.DictReader(floor_instances.open(), delimiter="\t"))
    expected_pads = {tuple(int(r[k]) for k in ("xmin", "ymin", "xmax", "ymax")): r["name"] for r in rows if r["name"] in pad_nets}
    actual_pads = {}

    def walk(cell, transform, depth=0):
        assert depth <= 8
        for inst in cell.each_inst():
            for local in inst.cell_inst.each_trans():
                full = transform * local
                if inst.cell.name == "bondpad70_m2_ring":
                    size = round(70/dbu)
                    box = kdb.Box(0, 0, size, size).transformed(full)
                    key = tuple(round(v*dbu*1000) for v in bounds(box))
                    if key in expected_pads:
                        pad = expected_pads[key]
                        assert pad not in actual_pads
                        actual_pads[pad] = (inst.cell, full)
                elif not inst.cell.name.startswith("sg13g2_"):
                    walk(inst.cell, full, depth+1)

    walk(top, kdb.Trans())
    assert set(actual_pads) == set(pad_nets)
    local_pins = bondpad_pins(bond_lef, dbu)
    bond_records = []
    for pad, (cell, transform) in sorted(actual_pads.items()):
        net = pad_nets[pad]
        for layer, local_pin in local_pins.items():
            own_metal = conductor(layout, cell, layer)
            assert (local_pin-own_metal).area() == 0, (pad, layer, "LEF coverage")
            pin = local_pin.transformed(transform)
            hits = positive_overlap_polygons(metals[layer], pin)
            nodes = [layer + ":" + polygon_id(p) for p in hits.each_merged()]
            assert nodes
            seeds[net].update(nodes)
            bond_records.append({"bondpad": pad, "expected_net": net, "layer": layer, "nodes": sorted(nodes),
                                 "own_macro_LEF_uncovered_um2": 0})
    queue = deque(sorted(set().union(*seeds.values())))
    queued = set(queue)
    visited = set()
    union = UnionFind()
    edges = {}
    for node in queued:
        union.find(node)
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        layer, cid = node.split(":")
        source_region = kdb.Region(polygons[layer][cid])
        for via, _, lower, upper in VIA_STACK:
            if layer not in (lower, upper):
                continue
            other_layer = upper if layer == lower else lower
            actual_cuts = positive_overlap_polygons(vias[via], source_region)
            if actual_cuts.is_empty():
                continue
            targets = positive_overlap_polygons(metals[other_layer], actual_cuts)
            for target in targets.each_merged():
                other = other_layer + ":" + polygon_id(target)
                key = tuple(sorted((node, other)))
                if key not in edges:
                    bridge_cuts = positive_overlap_polygons(actual_cuts, kdb.Region(target))
                    assert not bridge_cuts.is_empty()
                    witness = next(bridge_cuts.each_merged())
                    wregion = kdb.Region(witness)
                    edges[key] = {"nodes": list(key), "via": via, "via_connected_polygons": bridge_cuts.count(),
                                  "witness_bbox_dbu": bounds(witness.bbox()),
                                  "witness_polygon_dbu": str(witness),
                                  "witness_area_overlap_source_um2": (wregion & source_region).area()*dbu*dbu,
                                  "witness_area_overlap_target_um2": (wregion & kdb.Region(target)).area()*dbu*dbu}
                union.union(node, other)
                if other not in queued:
                    queued.add(other)
                    queue.append(other)
        if len(visited) % 200 == 0:
            print(json.dumps({"phase": "PG_reachable_only", "visited": len(visited), "queued": len(queued), "elapsed_seconds": time.monotonic()-started}), flush=True)
    roots = {node: union.find(node) for node in visited}
    seed_roots = {net: sorted({roots[node] for node in nodes}) for net, nodes in seeds.items()}
    root_nets = {}
    for net, net_roots in seed_roots.items():
        for rt in net_roots:
            root_nets.setdefault(rt, []).append(net)
    mixed = [{"component_root": rt, "expected_supplies": sorted(nets)} for rt, nets in sorted(root_nets.items()) if len(nets) > 1]
    for p in pin_nodes:
        p["roots"] = sorted({roots[n] for n in p["nodes"]})
    for p in bond_records:
        p["roots"] = sorted({roots[n] for n in p["nodes"]})
    summaries = {}
    for net in seeds:
        macro_entries = [r for r in pin_nodes if r["net"] == net]
        pad_entries = [r for r in bond_records if r["expected_net"] == net]
        ambiguous = [m for m in mixed if net in m["expected_supplies"]]
        closed = len(seed_roots[net]) == 1 and not ambiguous
        summaries[net] = {"PG_macro_instances": len({r["instance"] for r in macro_entries}),
                          "PG_pin_layer_regions": len(macro_entries), "supply_bondpads": len({r["bondpad"] for r in pad_entries}),
                          "supply_bondpad_layer_regions": len(pad_entries), "seed_metal_components": len(seeds[net]),
                          "connected_component_count": len(seed_roots[net]), "component_roots": seed_roots[net],
                          "all_128_macro_pin_regions_and_4_bondpads_connected": closed,
                          "mixed_with_other_supplies": bool(ambiguous),
                          "metal_via_connectivity_result": "PASS" if closed else "FAIL"}
        assert summaries[net]["PG_macro_instances"] == 128 and summaries[net]["supply_bondpads"] == 4
    node_records = {}
    for node in sorted(visited):
        layer, cid = node.split(":")
        polygon = polygons[layer][cid]
        node_records[node] = {"layer": layer, "bbox_dbu": bounds(polygon.bbox()), "area_um2": polygon.area()*dbu*dbu,
                              "root": roots[node], "seed_supply_labels": sorted(net for net, items in seeds.items() if node in items)}
    result = {"classification": "IO_ring_PG_seed_reachable_metal_via_graph_not_LVS_or_IR_EM",
              "source_sha256": hashes, "source_hashes_unchanged": hashes == {str(p.relative_to(root)): sha(p) for p in sources},
              "klayout_version": kdb.__version__, "dbu_um": dbu, "elapsed_seconds": time.monotonic()-started,
              "graph_scope": "Only actual metal components reachable from four PG pin seeds and their 16 physical supply bondpads; no other net seeds, labels never add edges.",
              "conductor_derivation": "drawing+filler minus slit/res marker; top metals also minus ind_drw",
              "via_derivation": "Via1/2/3/4/TopVia2 drawing; TopVia1 drawing minus ((vmim OR TopVia1) AND mim). Both endpoint metals must have positive area overlap with the same actual via polygon.",
              "via_statistics": via_stats, "same_layer_total_components": {l: r.count() for l, r in metals.items()},
              "PG_reachable_nodes": len(visited), "PG_reachable_edges": len(edges),
              "supplies": summaries, "cross_supply_connected_components": mixed,
              "overall_metal_via_connectivity_result": "PASS" if all(s["metal_via_connectivity_result"] == "PASS" for s in summaries.values()) else "FAIL",
              "pin_layer_nodes": pin_nodes, "supply_bondpad_layer_nodes": bond_records,
              "nodes": node_records, "edges": list(edges.values()),
              "limitations": ["No well/substrate/contact or device network extraction", "No full signal-net graph", "No LVS or DRC", "No IR/EM/resistance/voltage/drop analysis", "No bondwire/package connection", "No core PDN", "No new full-chip PPA"],
              "next_gate_if_connected": "Metal/via connectivity alone does not clear strict IO LVS, DRC, supply integrity or full-chip acceptance."}
    assert result["source_hashes_unchanged"]
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"elapsed_seconds": result["elapsed_seconds"], "PG_nodes": len(visited), "PG_edges": len(edges),
                      "result": result["overall_metal_via_connectivity_result"], "supply_component_counts": {n: s["connected_component_count"] for n, s in summaries.items()},
                      "mixed_components": len(mixed)}), flush=True)


if __name__ == "__main__":
    main()
