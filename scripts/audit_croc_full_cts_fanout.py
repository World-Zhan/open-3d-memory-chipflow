#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit the full CTS fanout ECO, preserving all remaining signoff failures."""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import audit_croc_placement_structure as base
import validate_croc_clock_eco as eco
from collect_croc_evidence import final_timing, timing_checks


def normalized_sdc(text):
    """Ignore only write_sdc's standalone weekday timestamp, never commands."""
    return re.sub(r'^# (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} +\d{1,2} \d\d:\d\d:\d\d \d{4}\r?\n', '', text, flags=re.M)


def check_constraints(source, before, after):
    if not normalized_sdc(source) == normalized_sdc(before) == normalized_sdc(after):
        raise ValueError('Source, before and after saved SDC commands differ')
    loads = re.findall(r'^set_load -pin_load ([0-9.]+) ', source, re.M)
    if not loads or any(float(value) != 15.0 for value in loads):
        raise ValueError('Require the original explicit 15 pF load commands')
    return {'result': 'PASS', 'commands_unchanged': True, 'io_load_pf': 15.0, 'load_command_count': len(loads)}


def check_placement_pg(rows, log):
    expected = {'check_placement': '', 'check_power_grid_VDD': '1', 'check_power_grid_VSS': '1'}
    if len(rows) != len(expected) or {r['check'] for r in rows} != set(expected):
        raise ValueError('Missing or duplicate actual placement/PG checks')
    if any(r['tcl_catch_code'] != '0' or r['message'] != expected[r['check']] for r in rows):
        raise ValueError('Placement/PG check failed or changed return signature')
    if '[ERROR' in log or 'PLACEMENT_LEGALITY_END catch=0 result=' not in log:
        raise ValueError('Tool log contains an error or lacks placement completion')
    for net in ('VDD', 'VSS'):
        if f'[INFO PSM-0040] All shapes on net {net} are connected.' not in log:
            raise ValueError('Missing actual ordinary core PG connected observation')
    return {'result': 'PASS', 'ordinary_placement_check': True, 'ordinary_core_pg_connected': ['VDD', 'VSS'],
            'full_io_pg_or_ir_em_proven': False}


def rows(path):
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter='\t'))


def check_source_capture(source, candidate):
    for kind in ('instances', 'iterms', 'bterms', 'bpin_boxes', 'bounds'):
        def inventory(path):
            return Counter(tuple(sorted(r.items())) for r in rows(path))
        if inventory(source / ('after_' + kind + '.tsv')) != inventory(candidate / ('before_' + kind + '.tsv')):
            raise ValueError('Fresh before capture differs from current source: ' + kind)
    return {'result': 'PASS', 'current_source_run': source.name,
            'complete_instance_terminal_port_geometry_inventory_matches': True}


def active_area(path):
    return sum(float(row['area_um2']) for row in rows(path) if row['type'] in ('CORE', 'BLOCK')) / 1e6


def raw_power(path):
    text = path.read_text()
    match = re.search(r'report_power tt\n-+\n(.*?)(?=\n=|\Z)', text, re.S)
    total = re.search(r'^Total\s+\S+\s+\S+\s+\S+\s+(\S+)', match[1], re.M) if match else None
    return float(total[1]) * 1000 if total else None


def audit(root, run_id):
    run = root / 'runs' / run_id
    generic = base.audit(root, run_id)
    if generic['physical_invariants']['result'] != 'PASS':
        raise ValueError('Physical invariants are not proven')
    source = root / 'runs/croc-full-io-cts-20260909-001'
    before, after = ((run / (phase + '.def')).read_text() for phase in ('before', 'after'))
    proof = eco.validate(before, after)
    # Audit actual scalar Liberty identity as well as the fixed master name.
    lib = base.liberty_logic((root / 'upstream/croc/technology/lib/sg13g2_stdcell_typ_1p20V_25C.lib').read_text())
    if base.cell_kind('sg13g2_buf_8', lib) != 'buffer':
        raise ValueError('Added cell is not proven scalar identity in the actual Liberty')
    constraints = check_constraints(*[(run / name).read_text() for name in ('inputs/cts.sdc', 'before.sdc', 'after.sdc')])
    checks = check_placement_pg(rows(run / 'placement_checks.tsv'), (run / 'tool.log').read_text())
    source_capture = check_source_capture(source, run)
    gate_path = root / 'reports/placement/full-io-cts-extended-audit-20260909-001.json'
    original_clock = json.loads(gate_path.read_text())['clock_ndr']
    ap, ar = eco.clock_properties(after)
    timing = {phase: final_timing(run / (phase + '_cts.rpt')) for phase in ('before', 'after')}
    hashes = generic['source_sha256']
    for rel in ('scripts/audit_croc_full_cts_fanout.py', 'scripts/validate_croc_clock_eco.py',
                'scripts/collect_croc_evidence.py', str(gate_path.relative_to(root))):
        hashes[rel] = base.sha(root / rel)
    for kind in ('instances', 'iterms', 'bterms', 'bpin_boxes', 'bounds'):
        p = source / ('after_' + kind + '.tsv')
        hashes[str(p.relative_to(root))] = base.sha(p)
    return {'schema_version': '1.0.0', 'run_id': run_id, 'source_run': source.name,
            'classification': 'eight_buffer_cts_eco_structure_not_formal_or_signoff', 'overall_result': 'PASS',
            'source_sha256': hashes, 'execution': generic['execution'], 'source_capture': source_capture,
            'physical_invariants': generic['physical_invariants'], 'def_export_crosschecks': generic['def_export_crosschecks'],
            'exact_connectivity_after_buffer_collapse': proof, 'snapshot_delta': generic['snapshot_delta'],
            'actual_liberty_buffer_identity_proven': True,
            'generic_normalization_result': generic['normalized_connectivity'],
            'generic_normalization_limitation': 'Existing CTS unconnected clkload output is unsupported by the generic placement normalizer; exact ECO proof instead preserves every original master and terminal.',
            'constraints': constraints, 'placement_and_core_pg': checks,
            'clock_ndr': {'result': 'PASS', 'clock_net_count': sum(p[0] == 'CLOCK' for p in ap.values()),
                          'clock_nets_with_ndr': sum(p[0] == 'CLOCK' and p[1] is not None for p in ap.values()),
                          'definition_count': len(ar), 'original_net_metadata_and_rule_definitions_unchanged': True,
                          'added_clock_branches_with_inherited_ndr': len(proof['clock_ndr_inheritance']),
                          'retained_internal_branches_without_ndr': len(original_clock['internal_clock_branches_without_ndr']),
                          'retained_leaf_branches_without_ndr': original_clock['leaf_clock_branches_without_ndr'],
                          'routing_ndr_policy_qualification': 'UNVERIFIED'},
            'timing': timing, 'electrical_checks': timing_checks(timing['after']),
            'electrical_acceptance': 'PASS' if all(timing_checks(timing['after']).values()) else 'FAIL',
            'ppa': {'same_stage': 'CTS_placement_parasitics',
                    'active_area_mm2': {phase: active_area(run / (phase + '_area.tsv')) for phase in ('before', 'after')},
                    'raw_tt_power_mw': {phase: raw_power(run / (phase + '_cts.rpt')) for phase in ('before', 'after')},
                    'power_qualification': 'UNVERIFIED_clock_activity_anomaly', 'workload_power_mw': None, 'fmax_mhz': None},
            'full_formal_equivalence_proven': False, 'clock_waveform_timing_proven': False,
            'route_or_signoff_proven': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    dest = root / args.output
    if dest.exists():
        raise ValueError('Preserve prior audit; independent output required')
    result = audit(root, args.run_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('run_id', 'overall_result', 'electrical_acceptance', 'timing', 'ppa', 'clock_ndr')}, indent=2))
