#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Actual diode-electrode parent metal paths and public guard derivations."""
from __future__ import annotations
import argparse
from collections import deque
import json
from pathlib import Path
import re
import time
import klayout.db as kdb
from probe_io_ring_pg import LAYERS, conductor, raw_region, sha, bounds
from probe_io_ring_pg_vias import VIA_STACK, UnionFind, polygon_id, positive_overlap_polygons, derive_topvia1, validate_geometry_failures

TARGETS = {"sg13g2_DCNDiode": "cathode", "sg13g2_DCPDiode": "anode"}


def all_labels(layout, cell, specs):
    rows = []
    def walk(here, trans, depth=0):
        assert depth <= 12
        for number, purpose in specs:
            index = layout.find_layer(number, purpose)
            if index is None:
                continue
            for shape in here.shapes(index).each():
                if shape.is_text():
                    text = shape.text
                    point = trans * text.trans.disp
                    rows.append({"text": text.string, "layer": [number, purpose], "point_dbu": [point.x, point.y], "source_cell": here.name})
        for inst in here.each_inst():
            for local in inst.cell_inst.each_trans():
                walk(inst.cell, trans * local, depth+1)
    walk(cell, kdb.Trans())
    return rows


def point_component(polygons, point):
    probe = kdb.Region(kdb.Box(point[0], point[1], point[0]+1, point[1]+1))
    hits = [cid for cid, polygon in polygons.items() if not (kdb.Region(polygon)&probe).is_empty()]
    assert len(hits) == 1, (point, hits)
    return hits[0]


def metal_graph(layout, cell, points):
    dbu = layout.dbu
    metals = {layer: conductor(layout, cell, layer) for layer in LAYERS}
    polygons = {layer: {polygon_id(p): p for p in r.each_merged()} for layer, r in metals.items()}
    vias = {}
    for name, number, _, _ in VIA_STACK:
        raw = raw_region(layout, cell, number, 0).merged()
        vias[name] = derive_topvia1(raw, raw_region(layout, cell, 129, 0), raw_region(layout, cell, 36, 0)) if name == 'TopVia1' else raw
    starts = {name: 'Metal1:'+point_component(polygons['Metal1'], point) for name, point in points.items()}
    queue = deque(sorted(set(starts.values())))
    queued = set(queue)
    union = UnionFind()
    edges = {}
    adjacency = {}
    while queue:
        node = queue.popleft()
        union.find(node)
        layer, cid = node.split(':')
        region = kdb.Region(polygons[layer][cid])
        for via, _, lo, hi in VIA_STACK:
            if layer not in (lo, hi):
                continue
            other_layer = hi if layer == lo else lo
            cuts = positive_overlap_polygons(vias[via], region)
            if cuts.is_empty():
                continue
            for target in positive_overlap_polygons(metals[other_layer], cuts).each_merged():
                other = other_layer+':'+polygon_id(target)
                key = tuple(sorted((node, other)))
                if key not in edges:
                    bridges = positive_overlap_polygons(cuts, kdb.Region(target))
                    witness = next(bridges.each_merged())
                    edges[key] = {'nodes': list(key), 'via': via, 'via_polygons': bridges.count(),
                                  'witness_bbox_dbu': bounds(witness.bbox()), 'witness_bbox_um': [v*dbu for v in bounds(witness.bbox())]}
                union.union(node, other)
                adjacency.setdefault(node, set()).add(other)
                adjacency.setdefault(other, set()).add(node)
                if other not in queued:
                    queue.append(other)
                    queued.add(other)
    nodes = {}
    for node in queued:
        layer, cid = node.split(':')
        polygon = polygons[layer][cid]
        nodes[node] = {'layer': layer, 'bbox_dbu': bounds(polygon.bbox()), 'area_um2': polygon.area()*dbu*dbu, 'root': union.find(node)}
    direct_labels = []
    for layer, number in LAYERS.items():
        index = layout.find_layer(number, 25)
        if index is None:
            continue
        for shape in cell.shapes(index).each():
            if not shape.is_text():
                continue
            text = shape.text
            point = [text.trans.disp.x, text.trans.disp.y]
            try:
                cid = point_component(polygons[layer], point)
            except AssertionError:
                continue
            node = layer+':'+cid
            if node in nodes:
                direct_labels.append({'text': text.string, 'layer': layer, 'point_dbu': point, 'node': node, 'root': union.find(node)})
    def path(a, b):
        begin, end = starts[a], starts[b]
        if union.find(begin) != union.find(end):
            return None
        todo = deque([begin])
        previous = {begin: None}
        while todo and end not in previous:
            cur = todo.popleft()
            for nxt in sorted(adjacency.get(cur, ())):
                if nxt not in previous:
                    previous[nxt] = cur
                    todo.append(nxt)
        assert end in previous
        chain = []
        cur = end
        while cur is not None:
            chain.append(cur)
            cur = previous[cur]
        chain.reverse()
        return {'node_sequence': chain, 'layer_sequence': [nodes[n]['layer'] for n in chain],
                'via_edges': [edges[tuple(sorted((a, b)))] for a, b in zip(chain, chain[1:])]}
    graph = {'seed_nodes': starts, 'seed_roots': {k: union.find(v) for k, v in starts.items()}, 'nodes': nodes,
             'edges': list(edges.values()), 'direct_cell_labels_on_reachable_graph': direct_labels}
    return graph, path, metals


def region_record(region, dbu):
    return {'components': region.count(), 'area_um2': region.area()*dbu*dbu,
            'bbox_dbu': None if region.is_empty() else bounds(region.bbox())}


def guard_derivation(layout, cell, guard_points, layer_defs):
    dbu = layout.dbu
    def raw(name):
        return raw_region(layout, cell, *layer_defs[name]).merged()
    active = raw('activ_drw') + raw('activ_filler')
    poly = raw('gatpoly_drw') + raw('gatpoly_filler')
    nwell = raw('nwell_drw')
    psd = raw('psd_drw')
    nactive = (active - (psd + raw('nsd_block'))).merged()
    labels = all_labels(layout, cell, [(63, 0), (8, 25), (31, 25)])
    well_probes = kdb.Region()
    for label in labels:
        if label['layer'] == [63, 0] and label['text'].lower() == 'well':
            x, y = label['point_dbu']
            well_probes.insert(kdb.Box(x, y, x+1, y+1))
    ntap1_mk = nwell.interacting(well_probes)
    recog = raw('recog_diode')
    ntap_base = (nactive & nwell).merged()
    ntap = (ntap_base-ntap1_mk-recog-poly).merged()
    extent = kdb.Region(cell.bbox())
    digisub = raw('digisub_drw')
    digigap = digisub - digisub.sized(-round(0.001/dbu))
    pwell = (extent-raw('pwell_block')-nwell-digigap).merged()
    taps_exclude = poly.dup()
    for name in ('nsd_drw', 'trans_drw', 'emwind_drw', 'emwihv_drw', 'salblock_drw', 'polyres_drw', 'extblock_drw', 'res_drw', 'activ_mask', 'recog_diode', 'ind_drw', 'ind_pin'):
        taps_exclude += raw(name)
    ntap1_exc = pwell+psd+taps_exclude
    ntap1_tie = ((nactive&ntap1_mk)-ntap1_exc).merged()
    m1 = conductor(layout, cell, 'Metal1')
    m1polys = {polygon_id(p): p for p in m1.each_merged()}
    guard_m1 = kdb.Region()
    for point in guard_points:
        guard_m1.insert(m1polys[point_component(m1polys, point)])
    guard_m1.merge()
    contacts = positive_overlap_polygons(raw('cont_drw'), guard_m1)
    connected_taps = positive_overlap_polygons(ntap, contacts)
    valid_contacts = positive_overlap_polygons(contacts, connected_taps)
    guard_well = positive_overlap_polygons(nwell, connected_taps)
    raw_taps = positive_overlap_polygons(ntap_base, contacts)
    record = {'cell': cell.name, 'guard_label_points_dbu': guard_points, 'raw_text_labels': labels,
              'region_derivation': 'nactiv=(activ_drw+activ_filler)-(psd+nsd_block); ntap=nactiv&nwell-ntap1_mk-recog_diode-gatpoly; ntap1 marker requires actual well text 63/0.',
              'regions': {name: region_record(region, dbu) for name, region in
                          [('nwell', nwell), ('ntap_base', ntap_base), ('ntap1_marker', ntap1_mk), ('recog_diode', recog),
                           ('ntap', ntap), ('ntap1_tie', ntap1_tie), ('guard_m1', guard_m1), ('guard_M1_contacts', contacts),
                           ('guard_raw_nactive_nwell_taps', raw_taps), ('guard_public_ntap', connected_taps),
                           ('guard_contact_to_ntap', valid_contacts), ('guard_connected_nwell', guard_well)]},
              'guard_M1_contact_ntap_nwell_path_observed': not valid_contacts.is_empty() and not guard_well.is_empty(),
              'ntap_base_removed_by_recog_diode_um2': (ntap_base&recog).area()*dbu*dbu,
              'ntap_base_removed_by_ntap1_marker_um2': (ntap_base&ntap1_mk).area()*dbu*dbu,
              'guard_contact_witnesses_bbox_dbu': [bounds(p.bbox()) for p in list(valid_contacts.each_merged())[:4]],
              'scope': 'Static geometry of public ntap/ntap1 derivations; no device extraction or simplification-stage diagnosis.'}
    return record


def cdl_statement(text, cell):
    match = re.search(r'^\.SUBCKT\s+'+re.escape(cell)+r'\s+.*?^\.ENDS', text, re.M|re.S|re.I)
    assert match
    return match.group(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path('/work'))
    parser.add_argument('--output', type=Path, default=Path('/output/electrode_guard_geometry.json'))
    args = parser.parse_args()
    started = time.monotonic()
    root = args.repo
    pdk = root/'upstream/ihp-open-pdk/ihp-sg13g2'
    deck = pdk/'libs.tech/klayout/tech/lvs'
    gdss = {'croc_actual': root/'upstream/croc/technology/gds/sg13g2_io.gds',
            'official_pinned': pdk/'libs.ref/sg13g2_io/gds/sg13g2_io.gds'}
    cdl = pdk/'libs.ref/sg13g2_io/cdl/sg13g2_io.cdl'
    source_paths = [*gdss.values(), cdl, root/'reports/bondpad/probe_io_ring_pg.py', root/'reports/bondpad/probe_io_ring_pg_vias.py', deck/'sg13g2.lvs']
    source_paths += [deck/'rule_decks'/f for f in ('layers_definitions.lvs', 'general_derivations.lvs', 'general_connections.lvs', 'tap_derivations.lvs', 'tap_connections.lvs', 'tap_extraction.lvs', 'diode_derivations.lvs', 'diode_connections.lvs', 'cap_derivations.lvs')]
    hashes = {str(p.relative_to(root)): sha(p) for p in source_paths}
    layer_text = (deck/'rule_decks/layers_definitions.lvs').read_text()
    layer_defs = {name: (int(layer), int(purpose)) for name, layer, purpose in re.findall(r'(\w+)\s*=\s*get_polygons\((\d+),\s*(\d+)\)', layer_text)}
    cdl_text = cdl.read_text()
    records = {}
    for version, gds in gdss.items():
        layout = kdb.Layout()
        layout.read(str(gds))
        parent = layout.cell('sg13g2_IOPadIn')
        assert parent is not None
        parent_points, targets, leaf_graphs = {}, {}, {}
        parent_guard_points = []
        for leaf_name, electrode in TARGETS.items():
            leaf = layout.cell(leaf_name)
            instances = [inst for inst in parent.each_inst() if inst.cell.name == leaf_name]
            assert len(instances) == 1 and not instances[0].is_regular_array()
            trans = instances[0].trans
            labels = all_labels(layout, leaf, [(8, 25)])
            access = [l for l in labels if l['text'] == electrode]
            assert len(access) == 2
            points = {}
            access_records = []
            for number, label in enumerate(access):
                key = leaf_name+':'+electrode+':'+str(number)
                local = label['point_dbu']
                point = trans*kdb.Point(*local)
                points[key] = local
                parent_points[key] = [point.x, point.y]
                access_records.append({'key': key, 'leaf_point_dbu': local, 'parent_point_dbu': [point.x, point.y],
                                       'parent_point_um': [point.x*layout.dbu, point.y*layout.dbu]})
            guards = [l['point_dbu'] for l in labels if l['text'] == 'guard']
            if leaf_name == 'sg13g2_DCNDiode':
                assert guards
                for number, local in enumerate(guards):
                    point = trans*kdb.Point(*local)
                    parent_points['DCN_guard:'+str(number)] = [point.x, point.y]
                    parent_guard_points.append([point.x, point.y])
                    points['DCN_guard:'+str(number)] = local
            leaf_graph, leaf_path, _ = metal_graph(layout, leaf, points)
            a, b = [r['key'] for r in access_records]
            targets[leaf_name] = {'electrode': electrode, 'transform': str(trans), 'labels': access_records,
                                  'leaf_metal_via_path': leaf_path(a, b),
                                  'leaf_electrodes_physically_joined': leaf_graph['seed_roots'][a] == leaf_graph['seed_roots'][b]}
            leaf_graphs[leaf_name] = leaf_graph
        parent_graph, parent_path, _ = metal_graph(layout, parent, parent_points)
        for leaf_name, target in targets.items():
            a, b = [r['key'] for r in target['labels']]
            target['parent_metal_via_path'] = parent_path(a, b)
            target['parent_electrodes_physically_joined'] = parent_graph['seed_roots'][a] == parent_graph['seed_roots'][b]
            target['parent_direct_net_labels_on_electrode_root'] = sorted({l['text'] for l in parent_graph['direct_cell_labels_on_reachable_graph'] if l['root'] == parent_graph['seed_roots'][a]})
        dcn = layout.cell('sg13g2_DCNDiode')
        dcn_labels = all_labels(layout, dcn, [(8,25)])
        local_guard = [l['point_dbu'] for l in dcn_labels if l['text'] == 'guard']
        guard_leaf = guard_derivation(layout, dcn, local_guard, layer_defs)
        guard_parent = guard_derivation(layout, parent, parent_guard_points, layer_defs)
        guard_parent['parent_direct_net_labels_on_guard_root'] = sorted({l['text'] for l in parent_graph['direct_cell_labels_on_reachable_graph'] if l['root'] == parent_graph['seed_roots']['DCN_guard:0']})
        records[version] = {'dbu_um': layout.dbu, 'targets': targets, 'DCN_guard_leaf': guard_leaf, 'DCN_guard_parent': guard_parent,
                            'parent_graph': parent_graph, 'leaf_graphs': leaf_graphs}
        print(json.dumps({'version': version, 'targets': {n: {'leaf_joined': t['leaf_electrodes_physically_joined'], 'parent_joined': t['parent_electrodes_physically_joined'], 'parent_labels': t['parent_direct_net_labels_on_electrode_root']} for n,t in targets.items()},
                          'guard_leaf_ntap_path': guard_leaf['guard_M1_contact_ntap_nwell_path_observed'], 'guard_parent_ntap_path': guard_parent['guard_M1_contact_ntap_nwell_path_observed'], 'guard_parent_labels': guard_parent['parent_direct_net_labels_on_guard_root']}), flush=True)
    output = {'classification': 'actual_IOPadIn_electrode_paths_and_public_guard_geometry_not_LVS', 'source_sha256': hashes,
              'source_hashes_unchanged': hashes == {str(p.relative_to(root)): sha(p) for p in source_paths}, 'klayout_version': kdb.__version__,
              'elapsed_seconds': time.monotonic()-started, 'geometry_failure_cases': validate_geometry_failures(), 'versions': records,
              'official_cdl': {c: cdl_statement(cdl_text, c) for c in ('sg13g2_DCNDiode', 'sg13g2_DCPDiode', 'sg13g2_IOPadIn')},
              'lvs_performed': False, 'PDK_modified': False, 'implicit_connections': False, 'full_chip_attempt_3': False,
              'limitations': ['Static guard derivation does not identify the exact netlist cleanup step losing guard.', 'Metal/via connectivity is not device correspondence or strict hierarchical LVS.', 'No fabricated parent metal, no relaxed strict ports, no disabled tap extraction.']}
    assert output['source_hashes_unchanged']
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'elapsed_seconds': output['elapsed_seconds'], 'output_bytes': args.output.stat().st_size}), flush=True)


if __name__ == '__main__':
    main()
