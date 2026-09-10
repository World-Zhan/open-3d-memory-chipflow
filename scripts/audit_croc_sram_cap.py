#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit SRAM output buffering without inheriting electrical or signoff PASS."""
import argparse
import csv
import json
from pathlib import Path

import audit_croc_placement_structure as base
import validate_croc_clock_eco as defs
from audit_croc_full_cts_fanout import check_constraints, check_placement_pg, check_source_capture, rows, active_area, raw_power
from collect_croc_evidence import final_timing, timing_checks
from run_croc_sram_cap import diagnosis


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def prove_buffers(before, after, branches):
    bcells, bnets, bdie = defs.parse_def(before)
    acells, anets, adie = defs.parse_def(after)
    expected = {f'eco_sram_cap_b{bank}_d{bit:02d}' for bank in range(2) for bit in range(32)}
    require(len(branches) == 64 and {r['buffer'] for r in branches} == expected, 'Require all 64 unique diagnosed buffers')
    require(set(acells) - set(bcells) == expected, 'Only 64 specified SRAM buffers may be added')
    require(all(acells.get(name) == master for name, master in bcells.items()), 'Original instance/master changed')
    require(all(acells[name] == 'sg13g2_buf_4' for name in expected), 'Unexpected new buffer master')
    require(bdie == adie, 'Die or units changed')
    bp, br = defs.clock_properties(before)
    ap, ar = defs.clock_properties(after)
    require(br == ar, 'NDR definitions changed')
    require(all(ap.get(net) == value for net, value in bp.items()), 'Original net use/NDR changed')
    mapping = {}
    for net, pins in anets.items():
        for pin in pins:
            if pin[0] == '*':
                continue
            require(pin not in mapping or mapping[pin] == net, 'One terminal appears on multiple nets')
            mapping[pin] = net
    aliases, observed = {}, []
    for row in branches:
        name, net = row['buffer'], row['net']
        driver = (row['instance'], row['pin'])
        load_pins = {tuple(value.rsplit('/', 1)) for value in row['loads']}
        require(len(load_pins) == 4, 'Require four distinct original loads per output')
        require(bnets.get(net) == load_pins | {driver}, 'Original SRAM source/load endpoints differ')
        require(bp.get(net) == ('SIGNAL', None), 'SRAM source is not an unmodified data net')
        require(name not in bnets and ap.get(name) == ('SIGNAL', None), 'New data net has wrong identity/use/NDR')
        require(mapping.get((name, 'A')) == net and mapping.get((name, 'X')) == name, 'Buffer does not bridge expected source and destination')
        require(mapping.get((name, 'VDD')) == 'VDD' and mapping.get((name, 'VSS')) == 'VSS', 'New buffer lacks explicit VDD/VSS')
        require(anets.get(net) == {driver, (name, 'A')}, 'SRAM output must drive exactly its isolation buffer')
        require(anets.get(name) == load_pins | {(name, 'X')}, 'Buffer output does not preserve all four original loads')
        aliases[name] = net
        observed.append({'buffer': name, 'sram_driver': '/'.join(driver), 'original_net': net, 'new_data_net': name, 'loads': sorted(row['loads'])})
    collapsed = {}
    for net, pins in anets.items():
        target = aliases.get(net, net)
        collapsed.setdefault(target, set()).update(p for p in pins if p[0] not in expected)
    require(collapsed == bnets, 'Complete connectivity differs after buffer collapse')
    return {'result': 'PASS', 'new_buffers': 64, 'buffer_master': 'sg13g2_buf_4',
            'original_net_connectivity_after_collapse_unchanged': True, 'original_masters_unchanged': True,
            'explicit_new_buffer_pg': True, 'per_buffer_original_loads': 4, 'branches': observed,
            'clock_ndr': {'result': 'PASS', 'original_net_metadata_and_rule_definitions_unchanged': True,
                          'clock_net_count': sum(use == 'CLOCK' for use, _ in ap.values()),
                          'clock_nets_with_ndr': sum(use == 'CLOCK' and ndr is not None for use, ndr in ap.values()),
                          'definition_count': len(ar), 'new_signal_nets': 64,
                          'routing_ndr_policy_qualification': 'UNVERIFIED'}}


def original_geometry(before, after):
    def inventory(records):
        result = {r['name']: r for r in records}
        require(len(result) == len(records), 'Duplicate instance snapshot')
        return result
    bmap, amap = inventory(before), inventory(after)
    require(all(amap.get(name) == row for name, row in bmap.items()), 'Original geometry, orientation, master or placement status changed')
    return {'result': 'PASS', 'original_instances_preserved': len(bmap), 'original_instance_rows_identical': True,
            'all_original_core_geometry_preserved': True, 'temporary_fix_status_restored': True,
            'added_instances': len(set(amap) - set(bmap))}


def sram_violations(text):
    require(text.count('max capacitance\n') == 1, 'Missing or duplicate cap report section')
    section = text.split('max capacitance\n', 1)[1]
    records = [line.split()[0] for line in section.splitlines() if '/A_DOUT[' in line and line.endswith('(VIOLATED)')]
    require(len(records) == len(set(records)), 'Duplicate SRAM cap violation')
    return records


def audit(root, run_id):
    run = root / 'runs' / run_id
    source = root / 'runs/croc-full-io-cts-fanout-20260910-001'
    generic = base.audit(root, run_id)
    require(generic['physical_invariants']['result'] == 'PASS', 'Physical invariants not proven')
    recorded = json.loads((run / 'diagnosed_branches.json').read_text())
    require(recorded == diagnosis(root, source), 'Recorded diagnosis differs from actual current source and libraries')
    bdef, adef = [(run / (phase + '.def')).read_text() for phase in ('before', 'after')]
    proof = prove_buffers(bdef, adef, recorded['branches'])
    require(base.cell_kind('sg13g2_buf_4', base.liberty_logic((root / 'upstream/croc/technology/lib/sg13g2_stdcell_typ_1p20V_25C.lib').read_text())) == 'buffer',
            'Actual buffer Liberty is not scalar identity')
    geometry = original_geometry(rows(run / 'before_instances.tsv'), rows(run / 'after_instances.tsv'))
    constraints = check_constraints(*[(run / name).read_text() for name in ('inputs/cts.sdc', 'before.sdc', 'after.sdc')])
    placement = check_placement_pg(rows(run / 'placement_checks.tsv'), (run / 'tool.log').read_text())
    capture = check_source_capture(source, run)
    timing = {phase: final_timing(run / (phase + '_cts.rpt')) for phase in ('before', 'after')}
    required = {phase: sram_violations((run / name).read_text()) for phase, name in
                [('before', 'before_electrical_violators.rpt'), ('after', 'electrical_violators.rpt')]}
    require(len(required['before']) == 64, 'Control does not reproduce all 64 SRAM cap violations')
    prior_path = root / 'reports/placement/full-io-cts-fanout-audit-20260910-001.json'
    prior_clock = json.loads(prior_path.read_text())['clock_ndr']
    proof['clock_ndr'].update(retained_internal_branches_without_ndr=prior_clock['retained_internal_branches_without_ndr'],
                              retained_leaf_branches_without_ndr=prior_clock['retained_leaf_branches_without_ndr'])
    hashes = generic['source_sha256']
    for rel in ('scripts/audit_croc_sram_cap.py', 'scripts/run_croc_sram_cap.py', 'scripts/audit_croc_full_cts_fanout.py',
                'scripts/validate_croc_clock_eco.py', 'scripts/collect_croc_evidence.py', str(prior_path.relative_to(root))):
        hashes[rel] = base.sha(root / rel)
    for kind in ('instances', 'iterms', 'bterms', 'bpin_boxes', 'bounds'):
        rel = str((source / ('after_' + kind + '.tsv')).relative_to(root))
        hashes[rel] = base.sha(root / rel)
    return {'schema_version': '1.0.0', 'run_id': run_id, 'source_run': source.name,
            'classification': 'sram_output_buffer_eco_structure_not_formal_or_signoff', 'overall_result': 'PASS',
            'source_sha256': hashes, 'execution': generic['execution'], 'source_capture': capture,
            'physical_invariants': generic['physical_invariants'], 'original_geometry': geometry,
            'def_export_crosschecks': generic['def_export_crosschecks'], 'exact_buffer_proof': proof,
            'snapshot_delta': generic['snapshot_delta'], 'library_limits': recorded['library_limits'],
            'constraints': constraints, 'placement_and_core_pg': placement,
            'timing': timing, 'electrical_checks': timing_checks(timing['after']),
            'electrical_acceptance': 'PASS' if all(timing_checks(timing['after']).values()) else 'FAIL',
            'sram_capacitance': {'before_count': len(required['before']), 'after_count': len(required['after']),
                                 'remaining_endpoints': required['after'],
                                 'current_placement_estimate_repaired': not required['after'], 'routed_capacitance_proven': False},
            'ppa': {'same_stage': 'CTS_placement_parasitics',
                    'active_area_mm2': {phase: active_area(run / (phase + '_area.tsv')) for phase in ('before', 'after')},
                    'raw_tt_power_mw': {phase: raw_power(run / (phase + '_cts.rpt')) for phase in ('before', 'after')},
                    'power_qualification': 'UNVERIFIED_clock_activity_anomaly', 'qualified_power_mw': None,
                    'workload_power_mw': None, 'fmax_mhz': None},
            'generic_normalization_result': generic['normalized_connectivity'],
            'generic_normalization_limitation': 'Generic normalization does not support existing floating clkload outputs; exact proof retains all original masters and full terminal graph.',
            'full_formal_equivalence_proven': False, 'clock_waveform_timing_proven': False, 'route_or_signoff_proven': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    dest = root / args.output
    if dest.exists():
        raise ValueError('Preserve existing audit')
    result = audit(root, args.run_id)
    with dest.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('run_id', 'overall_result', 'electrical_acceptance', 'timing', 'sram_capacitance', 'ppa', 'original_geometry')}, indent=2))
