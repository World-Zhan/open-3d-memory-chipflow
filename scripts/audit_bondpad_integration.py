#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Add input-GDS integrity and explicit global/local density classification."""
import argparse, json, re
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
from audit_bondpad_drc import analyze, sha


def verify_generated_inputs(run):
    manifest = json.loads((run/'manifest.json').read_text())
    facts_path = run/'inputs/fixture_summary.json'
    if sha(facts_path) != manifest['fixture_summary_sha256']:
        raise ValueError('Fixture summary changed')
    facts = json.loads(facts_path.read_text())
    for name, expected in facts['outputs_sha256'].items():
        if Path(name).name != name or sha(run/'inputs'/name) != expected:
            raise ValueError('Generated fixture input changed: ' + name)
    by_name = {arm['name']: arm for arm in facts['arms']}
    if len(by_name) != len(facts['arms']) or set(by_name) != {a['name'] for a in manifest['arms']}:
        raise ValueError('Fixture arm set mismatch')
    checked = {}
    for arm in manifest['arms']:
        name = arm['name']
        expected = by_name[name]['gds_sha256']
        if Path(name).name != name or expected != arm['fixture_gds_sha256'] or sha(run/'inputs'/(name+'.gds')) != expected:
            raise ValueError('Arm GDS input mismatch: ' + name)
        checked[name] = expected
    return checked


def density_kind(item, description):
    values = ' '.join(v.text or '' for v in item.findall('./values/value'))
    if 'Local Density Window Violation' in values:
        return 'local_window'
    if 'Global Density Violation' in values:
        return 'global'
    if re.search(r'density|coverage ratio', description, re.I):
        return 'density_unspecified_scope'
    return None


def audit(root, run):
    checked = verify_generated_inputs(run)
    result = analyze(root, run)
    result['generated_input_gds_sha256_verified'] = checked
    result['auditor_sha256'] = sha(root/'scripts/audit_bondpad_integration.py')
    result['note'] = 'Independent reassessment preserves raw audit. Density includes explicit local-window coverage markers whose descriptions omit the word density.'
    for arm in result['arms']:
        report = next((run/arm['name']).glob('*_full.lyrdb'))
        tree = ET.parse(report)
        desc = {e.findtext('name'): e.findtext('description','') for e in tree.findall('.//categories/category')}
        density, other, scopes = Counter(), Counter(), Counter()
        for item in tree.findall('.//items/item'):
            category = (item.findtext('category') or '').strip("'")
            kind = density_kind(item, desc.get(category,''))
            if kind:
                density[category] += 1; scopes[kind] += 1
            else:
                other[category] += 1
        arm['density_marker_counts'] = dict(sorted(density.items()))
        arm['density_markers'] = sum(density.values())
        arm['density_marker_scopes'] = dict(sorted(scopes.items()))
        arm['non_density_marker_counts'] = dict(sorted(other.items()))
        arm['non_density_markers'] = sum(other.values())
        arm['pad_markers'] = sum(v for k,v in other.items() if k.startswith('Pad.'))
        assert arm['merged_markers'] == arm['density_markers'] + arm['non_density_markers']
    result['ppa']['scope'] = ('One IO plus complete 2mm seal; sparse-fixture density is not populated-chip density.'
        if run.name.startswith('croc-bondpad-seal') else 'Single pad and IO; density is evaluated on this fixture bbox, not the chip.')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); root = Path(__file__).resolve().parents[1]
    result = audit(root, root/'runs'/a.run)
    with a.output.open('x') as f:
        json.dump(result, f, indent=2, sort_keys=True); f.write('\n')
    print(json.dumps({a['name']: {k:a[k] for k in ('rule_execution_complete','merged_markers','density_markers','pad_markers','fixture_drc_passed')} for a in result['arms']}))
