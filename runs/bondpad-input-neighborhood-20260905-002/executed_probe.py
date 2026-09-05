#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read one archived input-pad neighborhood; no layout writes or whole-chip merging."""
from pathlib import Path
import hashlib
import json
import re
import klayout.db as k

ROOT = Path('/work')
OUTPUT = Path('/output/geometry.json')
ARCHIVE = ROOT / 'runs/croc-sg13g2-baseline-20260827-001'
DEF = ARCHIVE / 'artifacts/pnr/upstream/croc/openroad/out/croc.def'
GDS = ARCHIVE / 'artifacts/gds.attempt-4/upstream/croc/klayout/out/croc.filled.gds.gz'
LEF = ROOT / 'upstream/croc/technology/lef/sg13g2_io.lef'
IO_NAME = 'pad_jtag_tdi_i'
PAD_NAME = 'IO_BOND_pad_jtag_tdi_i'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bbox(box, dbu):
    return [round(v * dbu, 6) for v in (box.left, box.bottom, box.right, box.top)]


def min_distance(first, second, dbu):
    """Bracket Euclidean separation with the native engine to one DBU."""
    if first.is_empty() or second.is_empty():
        return {'status': 'missing_geometry', 'lower_um': None, 'upper_um': None}
    if not (first & second).is_empty():
        return {'status': 'overlap', 'lower_um': 0, 'upper_um': 0}
    low, high = 0, round(100 / dbu)
    if first.separation_check(second, high).is_empty():
        return {'status': 'beyond_100um_search', 'lower_um': 100, 'upper_um': None}
    while high - low > 1:
        mid = (low + high) // 2
        if first.separation_check(second, mid).is_empty():
            low = mid
        else:
            high = mid
    markers = first.separation_check(second, high)
    return {'status': 'measured_to_one_dbu', 'lower_um': round(low * dbu, 6),
            'upper_um': round(high * dbu, 6), 'nearest_edge_pairs_dbu': [str(pair) for pair in markers.each()][:8]}


text = DEF.read_text()
components_text = re.search(r'^COMPONENTS\s+\d+\s*;(.*?)^END COMPONENTS', text, re.M | re.S)[1]
components = {}
all_inputs = []
for record in components_text.split(';'):
    match = re.match(r'\s*-\s+(\S+)\s+(\S+)', record)
    position = re.search(r'\+\s+(?:FIXED|PLACED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)', record)
    if not match or not position:
        continue
    value = {'instance': match[1], 'master': match[2], 'placement_dbu': [int(position[1]), int(position[2])], 'orientation': position[3]}
    if match[1] in (IO_NAME, PAD_NAME):
        components[match[1]] = value
    if match[2] == 'sg13g2_IOPadIn':
        all_inputs.append(value)
assert len(all_inputs) == 9 and all(value['placement_dbu'][0] == 70000 and value['orientation'] == 'FW' for value in all_inputs)

interfaces = []
for section in ('NETS', 'SPECIALNETS'):
    body = re.search(r'^' + section + r'\s+\d+\s*;(.*?)^END ' + section, text, re.M | re.S)[1]
    for record in body.split(';'):
        if IO_NAME not in record and PAD_NAME not in record:
            continue
        pins = re.findall(r'\(\s*(' + IO_NAME + '|' + PAD_NAME + r')\s+(\S+)\s*\)', record)
        if pins:
            interfaces.append({'section': section, 'net': re.match(r'\s*-\s+(\S+)', record)[1], 'local_connections': pins})
lef_macro = re.search(r'^MACRO sg13g2_IOPadIn\s*$(.*?)^END sg13g2_IOPadIn\s*$', LEF.read_text(), re.M | re.S)[1]
pad_pin = re.search(r'^\s*PIN pad\s*$(.*?)^\s*END pad\s*$', lef_macro, re.M | re.S)[1]
assert len(re.findall(r'RECT 5\.000 0\.000 75\.000 3\.000', pad_pin)) == 6

layout = k.Layout()
layout.read(str(GDS))
dbu = layout.dbu
sealed = layout.top_cell()
chip = layout.cell('croc_chip')
chip_instances = [inst for inst in sealed.each_inst() if inst.cell.name == 'croc_chip']
assert len(chip_instances) == 1
chip_trans = chip_instances[0].cplx_trans
assert not chip_trans.is_mirror() and chip_trans.angle == 0 and chip_trans.mag == 1
dx, dy = chip_trans.disp.x, chip_trans.disp.y
expected_io_box = k.Box(70000, 518000, 250000, 598000)
io_instances = [inst for inst in chip.each_inst() if inst.cell.name == 'sg13g2_IOPadIn'
                and inst.cplx_trans.disp == k.Vector(70000, 518000)]
assert len(io_instances) == 1
assert io_instances[0].cplx_trans.is_mirror() and io_instances[0].cplx_trans.angle == 90
pad_box = k.Box(0, 523000, 70000, 593000)
pad_instances = [inst for inst in chip.each_inst() if inst.cell.name == 'bondpad_70x70' and inst.bbox() == pad_box]
assert len(pad_instances) == 1

# Normalize the real left-edge instance to a canonical bottom-edge fixture:
# u = y_sealed-(518um+dy), v = x_sealed-(70um+dx).
normal = k.Trans(k.Trans.M45, -518000 - dy, -70000 - dx)
roi = k.Box(-30000 + dx, 488000 + dy, 280000 + dx, 628000 + dy)
regions = {}
for name, pair in {'Activ': (1, 0), 'EdgeSeal': (39, 0), 'Passiv': (9, 0), 'dfpad': (41, 0),
                   'Metal3': (30, 0), 'Metal4': (50, 0)}.items():
    index = layout.find_layer(*pair)
    raw = k.Region(sealed.begin_shapes_rec_touching(index, roi))
    regions[name] = (raw & k.Region(roi)).transformed(normal).merged()
pad_local = k.Box(5000, -70000, 75000, 0)
opening = regions['Passiv'] & regions['dfpad'] & k.Region(pad_local)
assert opening.count() == 1
active = regions['Activ'] - regions['EdgeSeal']
edge_active = regions['Activ'] & regions['EdgeSeal']
io_local = k.Region(io_instances[0].cell.begin_shapes_rec(layout.find_layer(1, 0))).merged()
exit_strip = k.Region(k.Box(5000, 0, 75000, 7000))
samples = {}
for name in ('Activ', 'EdgeSeal', 'Passiv', 'dfpad'):
    samples[name] = {'bbox_local_um': bbox(regions[name].bbox(), dbu), 'polygon_count_in_roi': regions[name].count()}
samples['Activ']['closest_inward_polygon_bboxes_um'] = sorted([bbox(poly.bbox(), dbu) for poly in active.each()], key=lambda b: b[1])[:12]
distances = {'opening_to_active': min_distance(opening, active, dbu),
             'opening_to_edge_seal_active': min_distance(opening, edge_active, dbu),
             'opening_to_edge_seal_drawing': min_distance(opening, regions['EdgeSeal'], dbu)}
result = {'schema_version': '1.0.0', 'classification': 'read_only_neighborhood_geometry_not_signoff',
          'requested_bottom_input_instance_exists': False, 'actual_pure_input_instances': all_inputs,
          'selected': components, 'interfaces': interfaces, 'dbu_um': dbu,
          'gds_chip_transform_into_sealed': str(chip_trans), 'gds_input_transform_in_chip': str(io_instances[0].cplx_trans),
          'gds_pad_transform_in_chip': str(pad_instances[0].cplx_trans),
          'selected_io_bbox_def_um': bbox(expected_io_box, dbu),
          'selected_io_bbox_gds_um': bbox(io_instances[0].bbox(), dbu),
          'gds_io_geometry_exceeds_lef_each_side_um': 0.62,
          'selected_pad_bbox_def_um': bbox(pad_box, dbu),
          'canonical_bottom_frame': {'formula_um': f'u=y_sealed-{518+dy*dbu}; v=x_sealed-{70+dx*dbu}',
                                     'io_bbox_um': [0, 0, 80, 180], 'bondpad_bbox_um': [5, -70, 75, 0],
                                     'opening_bbox_um': bbox(opening.bbox(), dbu), 'lef_pad_pin_rect_um': [5, 0, 75, 3],
                                     'is_existing_bottom_instance': False},
          'regions': samples, 'distance_brackets_um': distances,
          'exit_strip': {'bbox_local_um': [5, 0, 75, 7], 'required_length_um': 7,
                         'Metal3_present_area_um2': (regions['Metal3'] & exit_strip).area()*dbu**2,
                         'Metal3_missing_bbox_um': bbox((exit_strip-regions['Metal3']).bbox(), dbu),
                         'Metal4_present_area_um2': (regions['Metal4'] & exit_strip).area()*dbu**2,
                         'Metal4_missing_bbox_um': bbox((exit_strip-regions['Metal4']).bbox(), dbu)},
          'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in (DEF, GDS, LEF)},
          'scope': 'No layout changed; clipped real neighborhood only; source GDS chip/seal transforms verified against DEF.'}
with OUTPUT.open('x') as stream:
    json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write('\n')
print(json.dumps({'distance_brackets_um': distances, 'local': result['canonical_bottom_frame'], 'regions': samples, 'exit_strip':result['exit_strip']}, indent=2), flush=True)
