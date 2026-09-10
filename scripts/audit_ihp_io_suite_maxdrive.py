#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pure audit of the final Out30 single-master trial, preserving FAIL."""
import argparse
import csv
import io
import json
from pathlib import Path
import audit_ihp_io_suite_digital_sta as prior
import run_ihp_io_suite_maxdrive as runner
import run_ihp_io_suite_sta_readback as continuation
from run_io_ring_floorplan import now, sha

RUN = 'runs/ihp_io_suite-maxdrive-20260910-003'
BASELINE = 'runs/ihp_io_suite-sta-readback-20260910-002'


def single_master_change(original, candidate):
    old = '- out16 sg13g2_IOPadOut16mA '
    new = '- out16 sg13g2_IOPadOut30mA '
    prior.require(original.count(old) == 1 and candidate.count(new) == 1, 'Exactly one selected master required')
    prior.require(original.replace(old, new) == candidate, 'Change exceeds selected master')


def audit(root):
    validated_prior = prior.audit(root)
    run, baseline = root / RUN, root / BASELINE
    m = json.loads((run / 'manifest.json').read_text())
    evidence = dict(validated_prior['evidence_sha256'])
    for rel, digest in m['source_sha256'].items():
        prior.require(sha(root / rel) == digest, 'Source hash changed: ' + rel)
        evidence[rel] = digest
    output = run / 'multicorner'
    prior.terminal(m['execution'], json.loads((output / 'terminal_observation.json').read_text())['state'])
    for rel, digest in m['execution']['output_sha256'].items():
        prior.require(sha(output / rel) == digest, 'Output hash changed: ' + rel)
        evidence[str((output / rel).relative_to(root))] = digest
    prior.require(m['status'] == 'completed' and m['source_hashes_unchanged'] is True, 'Incomplete or changed run')
    view = runner.out30_interface(root)
    prior.require(view == json.loads((run / 'out30_interface_audit.json').read_text()), 'Out30 interface audit mismatch')
    single_master_change((baseline / 'multicorner/input.def').read_text(), (output / 'input.def').read_text())
    prior.require((baseline / 'multicorner/input.sdc').read_bytes() == (output / 'input.sdc').read_bytes(), 'SDC modified')
    prior.require((output / 'run.tcl').read_text() == continuation.tcl(), 'STA script changed')
    corners = {}
    log = (output / 'tool.log').read_text()
    prior.require('IHP_IO_SUITE_STA_COMPLETE' in log, 'Incomplete STA capture')
    for corner in ('tt','ff','ss'):
        old, new = baseline / 'multicorner' / corner, output / corner
        prior.require('IHP_IO_SUITE_CORNER_COMPLETE_' + corner in log, 'Missing corner')
        prior.validate_sdc((new / 'readback.sdc').read_text())
        single_master_change((old / 'readback.def').read_text(), (new / 'readback.def').read_text())
        old_terms = list(csv.DictReader(io.StringIO((old / 'actual_terms.tsv').read_text()), delimiter='\t'))
        new_terms = list(csv.DictReader(io.StringIO((new / 'actual_terms.tsv').read_text()), delimiter='\t'))
        for row in old_terms:
            if row['instance'] == 'out16':
                row['master'] = 'sg13g2_IOPadOut30mA'
        prior.require(old_terms == new_terms, 'Terminal/PG mapping changed')
        rows = prior.violations((new / 'electrical_violators.rpt').read_text())
        selected = [r for r in rows if r['pin'] == 'out16/pad']
        prior.require(len(selected) == 1 and selected[0]['check'] == 'max slew'
            and abs(selected[0]['limit'] - 1.2) < 1e-6, 'Out30 expected slew failure missing; review needed')
        path = prior.path_slacks((new / 'out16_path.rpt').read_text())
        prior.require(path['path_found'], 'Out30 timing path missing')
        previous = next(r for r in validated_prior['corners'][corner]['electrical_violation_rows'] if r['pin'] == 'out16/pad')
        corners[corner] = {'pvt': validated_prior['corners'][corner]['pvt'], 'execution_complete': True,
            'out16_slew_ns': previous['actual'], 'out30_slew_ns': selected[0]['actual'],
            'explicit_limit_ns': 1.2, 'out30_path': path, 'qualification_result': 'FAIL'}
    for path in (run / 'manifest.json', run / 'out30_interface_audit.json', Path(__file__), root / 'scripts/audit_ihp_io_suite_digital_sta.py', root / 'scripts/run_ihp_io_suite_maxdrive.py'):
        evidence[str(path.relative_to(root))] = sha(path)
    return {'schema_version': '1.0.0', 'report_id': 'ihp_io_suite-maxdrive-20260910-003', 'generated_at': now(),
        'audit_result': 'PASS', 'qualification_result': 'FAIL', 'scope': 'one_official_Out16_to_Out30_master_change_in_local_fixture_only',
        'source_run': RUN, 'baseline_run': BASELINE, 'fixed_pdk_commit': m['fixed_pdk_commit'], 'fixed_image': m['fixed_image'],
        'execution': {'exit_code': m['execution']['returncode'], 'oom_killed': False, 'elapsed_seconds': m['execution']['elapsed_seconds'], 'complete': True},
        'same_constraints_load_and_endpoints': True, 'load_pf': 15, 'explicit_max_transition_ns': 1.2,
        'actual_candidate_instance_name': 'out16', 'actual_candidate_master': 'sg13g2_IOPadOut30mA',
        'external_GPIO_input_driver_unchanged': 'sg13g2_IOPadOut16mA', 'out30_interface_audit': view,
        'out30_behavior_simulation_performed': False, 'corners': corners,
        'digital_simulation': validated_prior['behavior_simulation'],
        'total_eda_processes_this_branch': 4, 'prior_failed_TT_run_preserved': True,
        'tested_drivers': ['sg13g2_IOPadOut16mA', 'sg13g2_IOPadInOut30mA', 'sg13g2_IOPadOut30mA'],
        'conclusion': 'None of the tested official drivers meets 15 pF with the retained 1.2 ns slew limit in all tested corners. Out30 still fails even FF and has negative SS max-path slack. This is not a claim about untested circuits or architectures.',
        'source_pdk_modified': False, 'main_design_modified': False, 'new_liberty_applied_to_old_gds': False,
        'chip_ppa_changed': False, 'workload_power_w': None, 'public_rule_signoff': False,
        'limitations': validated_prior['limitations'] + ['Out30 interface/PG and three-corner STA checked; no extra Out30 Verilog simulation, GDS or LVS performed in this fourth process.',
            'The instance name out16 is retained intentionally; the actual candidate master is Out30.'],
        'evidence_sha256': dict(sorted(evidence.items())), 'unique_hash_count': len(evidence)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = audit(root)
    with (root / args.output).open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'audit': result['audit_result'], 'qualification': result['qualification_result'], 'hashes': result['unique_hash_count']}))
