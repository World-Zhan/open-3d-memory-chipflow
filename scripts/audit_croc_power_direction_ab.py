#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail-closed pure audit of the bounded INOUT/INPUT power experiments."""
import argparse
import csv
import io
import json
import math
import re
from pathlib import Path

from run_croc_power_direction_ab import IMAGE, direction_lef, power_groups
from run_io_ring_floorplan import now, sha

RUNS = {mode: f'runs/croc-power-direction-{mode}-20260910-001' for mode in ('tiny', 'full')}
OLD_READBACK = 'runs/croc-placement-sta-readback-20260909-001/manifest.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def complete_state(arm, observed_state, log):
    require(type(arm.get('returncode')) is int and arm['returncode'] == 0, 'Process did not exit zero')
    require(arm.get('status') == 'completed' and arm.get('execution_complete') is True, 'Incomplete arm')
    require(arm.get('outer_timeout_expired') is False, 'Timeout missing or expired')
    state = arm.get('terminal_container_state', {})
    require(state == observed_state, 'Independent terminal observation differs')
    require(state.get('Status') == 'exited' and state.get('Running') is False and state.get('OOMKilled') is False
        and type(state.get('ExitCode')) is int and state['ExitCode'] == 0, 'Container is not healthy and terminal')
    require(arm.get('cleanup_returncode') == 0, 'Container cleanup not verified')
    require('OpenROAD v2.0-27244-gfecb04286' in log and 'POWER_DIRECTION_AB_COMPLETE' in log,
        'Tool version or completion sentinel missing')


def check_power(groups):
    require(set(groups) == {'Sequential', 'Combinational', 'Clock', 'Macro', 'Pad', 'Total'}, 'Power group missing')
    for group in groups.values():
        require(set(group) == {'internal_w', 'switching_w', 'leakage_w', 'total_w'}, 'Power field missing')
        require(all(type(v) in (float, int) and math.isfinite(v) and v >= 0 for v in group.values()), 'Power not finite nonnegative')
    require(groups['Total']['total_w'] > 0, 'Total power must be positive')


def compare_directions(inout, input_text, expected_count):
    rows = [list(csv.DictReader(io.StringIO(text), delimiter='\t')) for text in (inout, input_text)]
    require(all(len(rs) == expected_count for rs in rows), 'Bondpad instance count changed')
    signatures = []
    for direction, rs in zip(('INOUT', 'INPUT'), rows):
        require(all(r.get('direction') == direction and r.get('master') == 'bondpad70_m2_ring' and r.get('pin') == 'pad' for r in rs), 'Unexpected master or direction')
        require(len({r['instance'] for r in rs}) == len(rs), 'Duplicate bondpad instance')
        signatures.append(sorted((r['instance'], r['master'], r['pin'], r['net']) for r in rs))
    require(signatures[0] == signatures[1], 'Bondpad net endpoints changed')
    return expected_count


def normalized_sdc(text):
    return '\n'.join(line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#'))


def electrical_rows(text):
    result = {}
    section = None
    for line in text.splitlines():
        if line in ('max slew', 'max capacitance', 'max fanout'):
            section = line
        if line.endswith('(VIOLATED)'):
            values = line.split()
            require(section is not None and len(values) == 5, 'Unknown violation format')
            key = (section, values[0])
            require(key not in result, 'Duplicate violation endpoint')
            result[key] = dict(zip(('limit', 'actual', 'slack'), map(float, values[1:4])))
    return result


def audit_pair(root, mode, evidence):
    dest = root / RUNS[mode]
    path = dest / 'manifest.json'
    manifest = json.loads(path.read_text())
    evidence[str(path.relative_to(root))] = sha(path)
    require(manifest['status'] == 'completed' and manifest['mode'] == mode and manifest['fixed_image'] == IMAGE,
        'Wrong manifest completion, mode or image')
    require(manifest.get('source_hashes_unchanged') is True, 'Source hashes not marked unchanged')
    for rel, digest in manifest['source_sha256'].items():
        require(sha(root / rel) == digest, 'Source hash mismatch: ' + rel)
        evidence[rel] = digest
    powers = {}
    states = {}
    for arm, data in manifest['arms'].items():
        output = dest / arm
        state = json.loads((output / 'terminal_observation.json').read_text())['state']
        complete_state(data, state, (output / 'tool.log').read_text())
        for inventory in ('generated_input_sha256', 'outputs_sha256'):
            for rel, digest in data[inventory].items():
                require(sha(output / rel) == digest, 'Output/input hash mismatch: ' + arm + '/' + rel)
                evidence[str((output / rel).relative_to(root))] = digest
        power = power_groups((output / 'power_tt.rpt').read_text())
        check_power(power)
        require(power == data['raw_power_tt'], 'Manifest power differs from raw report')
        powers[arm] = power
        states[arm] = {'elapsed_seconds': data['elapsed_seconds'], 'exit_code': state['ExitCode'],
            'oom_killed': state['OOMKilled'], 'execution_complete': True}
    require(set(manifest['arms']) == {'inout', 'input'}, 'Two exact analysis arms required')
    left, right = dest / 'inout', dest / 'input'
    require(direction_lef((left / 'bondpad.lef').read_text(), 'INPUT') == (right / 'bondpad.lef').read_text(),
        'LEF changed beyond one direction field')
    for rel in ('probe.tcl', 'readback.def', 'readback.v'):
        require((left / rel).read_bytes() == (right / rel).read_bytes(), 'A/B structure or script changed: ' + rel)
    require(normalized_sdc((left / 'readback.sdc').read_text()) == normalized_sdc((right / 'readback.sdc').read_text()), 'A/B SDC differs')
    count = compare_directions((left / 'bondpad_directions.tsv').read_text(), (right / 'bondpad_directions.tsv').read_text(), 1 if mode == 'tiny' else 64)
    require(powers['input']['Sequential']['internal_w'] > powers['inout']['Sequential']['internal_w'] * 2,
        'Expected large sequential internal-power change not reproduced')
    result = {'result': 'PASS', 'scope': 'single_factor_analysis_direction_effect_not_design_acceptance', 'arms': states,
        'bondpad_instance_count': count, 'same_def_bytes': True, 'same_verilog_bytes': True, 'same_sdc_except_comments': True,
        'same_lef_geometry_except_direction': True, 'raw_power_tt_w': powers}
    if mode == 'tiny':
        for rel in ('input.def', 'input.sdc'):
            require((left / rel).read_bytes() == (right / rel).read_bytes(), 'Tiny input changed: ' + rel)
        require(powers['inout']['Pad']['internal_w'] == 0 and powers['inout']['Pad']['switching_w'] == 0
            and powers['input']['Pad']['internal_w'] > 0, 'Tiny IO power effect missing')
        result['description'] = 'Three instances: actual IHP IOPadIn, dfrbpq_1 DFF and no-Liberty bondpad; no placement RC or PG/signoff qualification.'
    else:
        require(powers['inout']['Macro']['internal_w'] == 0 and powers['input']['Macro']['internal_w'] > 0,
            'Full SRAM internal power recovery missing')
        old = json.loads((root / OLD_READBACK).read_text())
        old_arm = old['arms']['candidate']
        require(old['status'] == 'completed' and old_arm['status'] == 'completed'
            and old_arm['terminal_container_state']['ExitCode'] == 0, 'Prior complete readback required')
        old_tt = next(p for p in old_arm['power'] if p['corner'] == 'tt')['groups']['total']['total'] / 1000
        control = powers['inout']['Total']['total_w']
        relative = abs(control - old_tt) / old_tt
        require(relative < 0.001, 'DEF reimport control differs materially from complete ODB readback')
        evidence[OLD_READBACK] = sha(root / OLD_READBACK)
        result['reimport_control'] = {'prior_complete_odb_readback_rounded_w': old_tt, 'def_reimport_w': control,
            'relative_difference': relative, 'tolerance_fraction': 0.001,
            'interpretation': 'Within report rounding; DEF readback does not explain the large direction effect.'}
        rows_a, rows_b = [electrical_rows((p / 'electrical_violators.rpt').read_text()) for p in (left, right)]
        require(set(rows_a) == set(rows_b), 'Electrical violation endpoint set changed')
        changed = [{'check': key[0], 'endpoint': key[1], 'inout': rows_a[key], 'input': rows_b[key]}
            for key in sorted(rows_a) if rows_a[key] != rows_b[key]]
        result['electrical_effect'] = {'observed_counts_both_arms': {check: sum(k[0] == check for k in rows_a) for check in ('max slew', 'max capacitance')},
            'changed_rows': changed, 'note': 'Direction also affects timing/load graph. This is not an accepted physical repair. Fanout/setup/hold completeness is outside this diagnostic.'}
        result['raw_power_ff_w'] = {}
        for arm in ('inout', 'input'):
            groups = power_groups((dest / arm / 'power_ff.rpt').read_text())
            check_power(groups)
            require(groups == manifest['arms'][arm]['raw_power_ff'], 'FF raw power mismatch')
            result['raw_power_ff_w'][arm] = groups
    return result


def audit(root):
    evidence = {'scripts/audit_croc_power_direction_ab.py': sha(Path(__file__))}
    pairs = {mode: audit_pair(root, mode, evidence) for mode in RUNS}
    return {'schema_version': '1.0.0', 'report_id': 'croc-power-direction-ab-20260910-001', 'generated_at': now(),
        'overall_result': 'PASS', 'scope': 'causal_direction_effect_in_analysis_fixtures_only',
        'fixed_image': IMAGE, 'fixed_tool': 'OpenROAD v2.0-27244-gfecb04286', 'pairs': pairs,
        'interpretation': 'With identical geometry, connectivity, SDC and libraries, changing the no-Liberty bondpad master direction reproduces and removes zero SRAM/low FF internal power. It also changes GPIO slew; a validated analysis/physical abstraction policy is still required.',
        'source_layout_modified': False, 'source_pdk_modified': False, 'physical_design_fix': False,
        'workload_power_w': None, 'power_optimization_proven': False, 'activity_density_directly_observed': False,
        'public_rule_signoff': False, 'eda_processes': 4, 'evidence_sha256': dict(sorted(evidence.items())),
        'next_gate': 'Review passive bondpad timing abstraction, preserve geometry/endpoints/PG, validate on current CTS and realistic activity before reporting qualified power.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = audit(root)
    with (root / args.output).open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'result': report['overall_result'], 'unique_hashes': len(report['evidence_sha256']), 'eda_processes': 4}))
