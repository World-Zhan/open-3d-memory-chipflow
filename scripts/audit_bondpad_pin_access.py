#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit real router counters and independently compare loaded pin boxes to GDS."""
import argparse, csv, hashlib, io, json, re
from pathlib import Path

LAYERS = {'Metal2': (10,0), 'Metal3': (30,0), 'Metal4': (50,0),
          'Metal5': (67,0), 'TopMetal1': (126,0), 'TopMetal2': (134,0)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def access_counts(log, returncode):
    names = ['scanned instances', 'unique  instances', 'macroGenAp',
             'macroValidPlanarAp', 'macroValidViaAp', 'macroNoAp']
    counts = {}
    for name in names:
        matches = re.findall(r'^#' + re.escape(name) + r'\s*=\s*(\d+)\s*$', log, re.M)
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous pin-access count: ' + name)
        counts[name] = int(matches[0])
    errors = bool(re.search(r'\[ERROR\b|Traceback|Killed|std::bad_alloc', log))
    complete = '[INFO DRT-0166] Complete pin access.' in log and returncode == 0 and not errors
    counts['execution_complete'] = complete
    counts['aggregate_macro_access_check_passed'] = bool(complete and counts['scanned instances'] == 2
        and counts['unique  instances'] == 2 and counts['macroNoAp'] == 0 and counts['macroValidPlanarAp'] > 0)
    return counts


def pin_rectangles(text):
    reader = csv.DictReader(io.StringIO(text), delimiter='\t')
    if reader.fieldnames != ['layer','xmin_dbu','ymin_dbu','xmax_dbu','ymax_dbu']:
        raise ValueError('Unexpected OpenDB pin dump header')
    result = {layer: [] for layer in LAYERS}
    for row in reader:
        if row['layer'] not in result:
            raise ValueError('Unexpected pin metal layer')
        coords = tuple(int(row[k]) for k in ('xmin_dbu','ymin_dbu','xmax_dbu','ymax_dbu'))
        if not (0 <= coords[0] < coords[2] <= 70000 and 0 <= coords[1] < coords[3] <= 70000):
            raise ValueError('Invalid pin rectangle')
        result[row['layer']].append(coords)
    if any(not boxes for boxes in result.values()):
        raise ValueError('Missing pin layer')
    return result


def analyze(root, run, gds):
    import klayout.db as k
    manifest_path = run/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for rel, expected in manifest['source_sha256'].items():
        if sha(root/rel) != expected:
            raise ValueError('Changed run source: ' + rel)
    for rel, expected in manifest['outputs_sha256'].items():
        if sha(run/rel) != expected:
            raise ValueError('Changed run output: ' + rel)
    contract = root/'runs/croc-bondpad-io-ab-20260905-001/inputs/fixture_summary.json'
    if sha(gds) != json.loads(contract.read_text())['lef_gds_contract']['gds_sha256']:
        raise ValueError('Unexpected reference GDS')
    log = (run/'tool.log').read_text()
    counts = access_counts(log, manifest['returncode'])
    boxes = pin_rectangles((run/'loaded_pin_geometry.tsv').read_text())
    layout = k.Layout(); layout.read(str(gds))
    assert layout.dbu == 0.001
    cell = layout.cell('bondpad70_m2_ring'); assert cell is not None
    comparisons = {}
    for name, pair in LAYERS.items():
        idx = layout.find_layer(*pair)
        if idx is None:
            raise ValueError('Missing GDS layer: ' + name)
        physical = k.Region(cell.begin_shapes_rec(idx)).merged()
        loaded = k.Region()
        for box in boxes[name]:
            loaded.insert(k.Box(*box))
        diff = physical ^ loaded
        comparisons[name] = {'opendb_rectangles': len(boxes[name]), 'gds_area_um2': physical.area()*layout.dbu**2,
            'symmetric_difference_area_um2': diff.area()*layout.dbu**2, 'geometry_equal': diff.is_empty()}
    return {'schema_version': '1.0.0', 'classification': 'pin_geometry_and_aggregate_access_not_route_signoff',
        'run_id': run.name, 'source_sha256': {str(p.relative_to(root)): sha(p) for p in
            (manifest_path, gds, contract, run/'tool.log', run/'loaded_pin_geometry.tsv', root/'scripts/audit_bondpad_pin_access.py')},
        'source_run_hashes_verified': True, 'dbu_um': layout.dbu, 'counts': counts,
        'pin_geometry': comparisons, 'all_pin_metals_match_gds': all(v['geometry_equal'] for v in comparisons.values()),
        'router_warnings': [line for line in log.splitlines() if '[WARNING ' in line],
        'all_connected_pad_terminals_individually_audited': False,
        'via_access_qualified': False, 'route_performed': False, 'lvs_performed': False,
        'public_rule_signoff': False,
        'limits': 'Aggregate macro access only; router reports zero valid via AP and unsupported LEF58 enclosure clauses. Full public deck and routed connectivity are separate gates.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/work'))
    p.add_argument('--run', default='croc-bondpad-pin-access-20260905-003')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = analyze(a.root, a.root/'runs'/a.run, a.root/'runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.gds')
    with a.output.open('x') as f:
        json.dump(result, f, indent=2, sort_keys=True); f.write('\n')
    print(json.dumps({'geometry_equal': result['all_pin_metals_match_gds'], 'counts': result['counts']}))
    raise SystemExit(0 if result['all_pin_metals_match_gds'] and result['counts']['aggregate_macro_access_check_passed'] else 1)
