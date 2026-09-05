#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare only the recursively expanded sg13g2_IOPadIn cell, without layout writes."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import klayout.db as k

ROOT = Path('/work')
OUTPUT = Path('/output/comparison.json')
TARGET = 'sg13g2_IOPadIn'
SOURCES = {
    'croc': ('upstream/croc/technology/gds/sg13g2_io.gds',
             '8bb45016e5a99e48b1df1ea52c97d6813d96f6afeb905a72a956ddc2c018565f'),
    'pinned_pdk': ('upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/gds/sg13g2_io.gds',
                   '4281a855377b6a1ca46356e9391258dc14e8efc3b8051a65befc0fe9db3c7825'),
}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def box_values(box):
    if box.empty():
        return None
    return [box.left, box.bottom, box.right, box.top]


def hierarchy(layout, top):
    pending, seen = [top.cell_index()], set()
    while pending:
        index = pending.pop()
        if index in seen:
            continue
        seen.add(index)
        pending.extend(inst.cell_index for inst in layout.cell(index).each_inst())
    return sorted(layout.cell(index).name for index in seen)


def layer_evidence(cell, layer_index, dbu):
    if layer_index is None:
        return k.Region(), {'expanded_shapes': {}, 'labels': [], 'merged_polygons': 0,
                            'area_dbu2': 0, 'area_um2': 0.0, 'bbox_dbu': None}
    region = k.Region(cell.begin_shapes_rec(layer_index)).merged()
    counts, labels = Counter(), []
    iterator = cell.begin_shapes_rec(layer_index)
    while not iterator.at_end():
        shape = iterator.shape()
        if shape.is_text():
            counts['text'] += 1
            value = shape.text
            transform = iterator.trans() * k.ICplxTrans(value.trans)
            labels.append({
                'string': value.string,
                'position_dbu': [transform.disp.x, transform.disp.y],
                'angle_deg': transform.angle,
                'mirror': transform.is_mirror(),
                'magnification': transform.mag,
                'size_dbu': value.size * iterator.trans().mag,
                'font': value.font,
                'halign': str(value.halign),
                'valign': str(value.valign),
            })
        elif shape.is_box():
            counts['box'] += 1
        elif shape.is_path():
            counts['path'] += 1
        elif shape.is_polygon():
            counts['polygon'] += 1
        elif shape.is_edge():
            counts['edge'] += 1
        else:
            counts['other'] += 1
        iterator.next()
    labels.sort(key=lambda value: json.dumps(value, sort_keys=True))
    return region, {
        'expanded_shapes': dict(counts), 'labels': labels,
        'merged_polygons': region.count(), 'area_dbu2': region.area(),
        'area_um2': round(region.area() * dbu * dbu, 9),
        'bbox_dbu': box_values(region.bbox()),
    }


def main():
    started = time.monotonic()
    layouts, cells, sources, layer_maps = {}, {}, {}, {}
    for name, (relative, expected_hash) in SOURCES.items():
        path = ROOT / relative
        actual_hash = sha(path)
        assert actual_hash == expected_hash, (name, actual_hash)
        layout = k.Layout()
        layout.read(str(path))
        cell = layout.cell(TARGET)
        assert cell is not None, (name, TARGET)
        layouts[name], cells[name] = layout, cell
        layer_maps[name] = {(layout.get_info(index).layer, layout.get_info(index).datatype): index
                            for index in layout.layer_indexes()}
        sources[name] = {
            'path': relative, 'sha256': actual_hash, 'bytes': path.stat().st_size,
            'dbu_um': layout.dbu, 'target_bbox_dbu': box_values(cell.bbox()),
            'referenced_cell_names': hierarchy(layout, cell),
        }
        print('Loaded', name, 'target bbox', cell.bbox(), flush=True)
    assert layouts['croc'].dbu == layouts['pinned_pdk'].dbu, 'Different database units require explicit normalization'
    dbu = layouts['croc'].dbu
    layers = []
    for layer, datatype in sorted(set(layer_maps['croc']) | set(layer_maps['pinned_pdk'])):
        regions, evidence = {}, {}
        for name in SOURCES:
            regions[name], evidence[name] = layer_evidence(
                cells[name], layer_maps[name].get((layer, datatype)), dbu)
        if all(not record['expanded_shapes'] for record in evidence.values()):
            continue
        delta = (regions['croc'] ^ regions['pinned_pdk']).merged()
        layers.append({
            'layer': layer, 'datatype': datatype,
            'filled_geometry_equal': delta.is_empty(),
            'labels_equal': evidence['croc']['labels'] == evidence['pinned_pdk']['labels'],
            'xor': {'merged_polygons': delta.count(), 'area_dbu2': delta.area(),
                    'area_um2': round(delta.area() * dbu * dbu, 9),
                    'bbox_dbu': box_values(delta.bbox())},
            'sources': evidence,
        })
        print('Compared layer', layer, datatype, 'xor area', delta.area(), flush=True)
    geometry_equal = all(record['filled_geometry_equal'] for record in layers)
    labels_equal = all(record['labels_equal'] for record in layers)
    result = {
        'schema_version': 1, 'cell': TARGET, 'scope': 'recursively_expanded_single_cell_tree',
        'klayout_version': k.__version__, 'sources': sources, 'layers': layers,
        'summary': {
            'nonempty_layer_pairs': len(layers),
            'filled_geometry_equal': geometry_equal, 'transformed_labels_equal': labels_equal,
            'target_bbox_equal': sources['croc']['target_bbox_dbu'] == sources['pinned_pdk']['target_bbox_dbu'],
            'unequal_geometry_layers': [[r['layer'], r['datatype']] for r in layers if not r['filled_geometry_equal']],
            'unequal_label_layers': [[r['layer'], r['datatype']] for r in layers if not r['labels_equal']],
            'expanded_label_count': {name: sum(len(r['sources'][name]['labels']) for r in layers) for name in SOURCES},
        },
        'limits': [
            'Comparison is limited to sg13g2_IOPadIn and its recursively instantiated geometry and labels.',
            'Whole-library geometry, timestamps, properties and binary serialization differences were not compared.',
            'Equal geometry does not establish DRC, LVS or physical signoff.',
            'Cell hierarchy is expanded for geometry comparison; hierarchy structural identity is not required.',
        ],
        'elapsed_seconds': round(time.monotonic() - started, 3),
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result['summary'], sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
