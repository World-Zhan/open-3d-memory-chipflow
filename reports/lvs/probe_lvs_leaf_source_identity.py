#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only DCN/DCP cell-tree equality and IOPadIn child placement probe."""
import importlib.util
import json
from pathlib import Path
import klayout.db as k

root = Path('/work')
helper = root / 'reports/bondpad/compare_input_io_cell.py'
spec = importlib.util.spec_from_file_location('cell_compare', helper)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
layouts, sources = {}, {}
for name, (relative, expected) in m.SOURCES.items():
    path = root / relative
    assert m.sha(path) == expected
    layout = k.Layout(); layout.read(str(path))
    assert layout.dbu == 0.001
    layouts[name] = layout
    sources[name] = {'path': relative, 'sha256': expected}
targets = []
for target in ('sg13g2_DCNDiode', 'sg13g2_DCPDiode'):
    cells = {name: layout.cell(target) for name, layout in layouts.items()}
    assert all(cells.values())
    layers = []
    pairs = sorted({(layout.get_info(idx).layer, layout.get_info(idx).datatype) for layout in layouts.values() for idx in layout.layer_indexes()})
    for layer, dtype in pairs:
        records = {name: m.layer_evidence(cells[name], layout.find_layer(layer, dtype), layout.dbu) for name, layout in layouts.items()}
        if not any(record[1]['expanded_shapes'] for record in records.values()):
            continue
        xor = (records['croc'][0] ^ records['pinned_pdk'][0]).merged()
        layers.append({'layer': layer, 'datatype': dtype, 'geometry_equal': xor.is_empty(),
                       'xor_area_um2': xor.area()*1e-6,
                       'labels_equal': records['croc'][1]['labels'] == records['pinned_pdk'][1]['labels'],
                       'source_evidence': {name: record[1] for name, record in records.items()}})
    targets.append({'cell': target, 'geometry_equal': all(r['geometry_equal'] for r in layers),
                    'labels_equal': all(r['labels_equal'] for r in layers), 'layers': layers,
                    'bboxes_dbu': {name: m.box_values(cell.bbox()) for name, cell in cells.items()}})
parent_children = {}
changed_bbox = k.Box(40310, 140170, 53650, 166895)
for name, layout in layouts.items():
    parent = layout.cell('sg13g2_IOPadIn')
    parent_children[name] = [{'cell': inst.cell.name, 'transform': str(inst.cplx_trans),
                              'bbox_dbu': m.box_values(inst.bbox()),
                              'intersects_previous_13_layer_delta_bbox': inst.bbox().overlaps(changed_bbox)}
                             for inst in parent.each_inst()]
result = {'schema_version': '1.0.0', 'classification': 'read_only_two_leaf_source_identity_not_lvs',
          'sources': sources, 'helper_sha256': m.sha(helper), 'targets': targets,
          'parent_direct_children': parent_children,
          'previous_parent_geometry_delta_bbox_um': [40.310, 140.170, 53.650, 166.895],
          'layout_modified': False, 'lvs_performed': False}
with Path('/output/leaf_source_identity.json').open('x') as f:
    json.dump(result, f, indent=2, sort_keys=True); f.write('\n')
print(json.dumps({'targets': [{key: item[key] for key in ('cell', 'geometry_equal', 'labels_equal')} for item in targets], 'parent_direct_children': parent_children}, indent=2))
