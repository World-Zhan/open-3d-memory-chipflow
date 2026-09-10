#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit official IO digital and local multicorner STA, keeping design FAIL."""
import argparse
import csv
import io
import json
import math
import re
from pathlib import Path
import run_ihp_io_suite_digital_sta as base
import run_ihp_io_suite_sta_readback as continuation
from run_io_ring_floorplan import now, sha
from run_croc_power_direction_ab import power_groups

FIRST = 'runs/ihp_io_suite-digital-sta-20260910-001'
SECOND = 'runs/ihp_io_suite-sta-readback-20260910-002'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def terminal(record, observed, success=True):
    state = record.get('terminal_container_state', {})
    require(state == observed, 'Terminal observations disagree')
    require(type(record.get('returncode')) is int, 'Integer process exit required')
    require(state.get('Status') == 'exited' and state.get('Running') is False and state.get('OOMKilled') is False, 'Not healthy and terminal')
    require(type(state.get('ExitCode')) is int and state['ExitCode'] == record['returncode'], 'Container/process exit disagree')
    require(record.get('outer_timeout') is False and record.get('cleanup_returncode') == 0, 'Timeout or cleanup failure')
    require(record.get('execution_complete') is success and (record['returncode'] == 0) is success, 'Execution status inconsistent')


def validate_sdc(text):
    load_rows = re.findall(r'^set_load\s+(?:-pin_load\s+)?([\d.]+)\s+\[get_ports\s+\{([^{}]+)\}\]', text, re.M)
    loads = dict((name, float(value)) for value, name in load_rows)
    for port in ('out_pad', 'bi_tx_pad', 'bi_rx_pad', 'bi_z_pad'):
        require(loads.get(port) == 15, 'Missing or relaxed external load: ' + port)
    for port in ('in_core', 'clk_core', 'bi_tx_rx', 'bi_rx_rx', 'bi_z_rx'):
        require(loads.get(port) == .05, 'Core observation load changed')
    transition = re.findall(r'^set_max_transition\s+([\d.]+)\s+\[current_design\]', text, re.M)
    require(transition == ['1.2000'], 'Explicit 1.2 ns threshold missing or changed')
    cases = dict((name, int(value)) for value, name in re.findall(r'^set_case_analysis\s+([01])\s+\[get_ports\s+\{([^{}]+)\}\]', text, re.M))
    require(cases == {'bi_rx_en': 0, 'bi_tx_en': 1, 'bi_z_en': 0}, 'Direction mode/enable contract changed')
    require(re.search(r'^create_clock -name clk_sys -period 10\.0000 \[get_ports \{clk_pad\}\]', text, re.M), '100 MHz input clock contract changed')
    return {'load_pf': 15, 'explicit_slew_limit_ns': 1.2, 'clock_period_ns': 10, 'mode_enables': cases, 'core_observation_load_pf': .05}


def path_slacks(text):
    if text.strip() == 'No paths found.':
        return {'path_found': False}
    result = {}
    for mode, body in re.findall(r'Path Type: (min|max)\n(.*?)(?=Startpoint:|\Z)', text, re.S):
        value = re.findall(r'([-+\d.]+)\s+slack\s+\((MET|VIOLATED)\)', body)
        require(len(value) == 1 and mode not in result, 'Missing/duplicate timing slack')
        slack = float(value[0][0])
        require(math.isfinite(slack) and ((slack < 0) == (value[0][1] == 'VIOLATED')), 'Slack/status conflict')
        result[mode] = {'slack_ns': slack, 'status': value[0][1]}
    require(set(result) == {'min', 'max'}, 'Missing min/max path')
    return {'path_found': True, **result}


def violations(text):
    rows = []
    section = None
    for line in text.splitlines():
        if line in ('max slew', 'max capacitance', 'max fanout'):
            section = line
        if '(VIOLATED)' in line:
            m = re.fullmatch(r'\s*(\S+)\s+([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)\s+\(VIOLATED\)', line)
            require(m is not None and section is not None, 'Malformed electrical violation')
            limit, actual, slack = map(float, m.groups()[1:])
            require(all(math.isfinite(v) for v in (limit, actual, slack)) and actual > limit and slack < 0, 'Inconsistent electrical violation')
            rows.append({'check': section, 'pin': m[1], 'limit': limit, 'actual': actual, 'slack': slack})
    return rows


def audit(root):
    first, second = root / FIRST, root / SECOND
    original = json.loads((first / 'manifest.json').read_text())
    current = json.loads((second / 'manifest.json').read_text())
    evidence = {}
    def verify(base_path, mapping):
        for rel, digest in mapping.items():
            path = base_path / rel
            require(path.is_file() and sha(path) == digest, 'Hash mismatch: ' + str(path))
            evidence[str(path.relative_to(root))] = digest
    for folder, manifest in ((first, original), (second, current)):
        evidence[str((folder / 'manifest.json').relative_to(root))] = sha(folder / 'manifest.json')
        verify(root, manifest['source_sha256'])
        require(manifest['source_hashes_unchanged'] is True, 'Source mutation')
    require(original['status'] == 'failed' and current['status'] == 'completed', 'Failed original or successful continuation misrepresented')
    for arm, record in original['runs'].items():
        terminal(record, json.loads((first / arm / 'terminal_observation.json').read_text())['state'], arm == 'simulation')
        verify(first / arm, record['output_sha256'])
    require(set(original['runs']) == {'simulation', 'tt'}, 'Original run unexpectedly enlarged')
    require('invalid command name "report_case_analysis"' in (first / 'tt/tool.log').read_text(), 'Original API failure evidence missing')
    simlog = (first / 'simulation/tool.log').read_text()
    require('ASSERTIONS=42 FAILURES=0' in simlog and 'OFFICIAL_IO_BEHAVIOR_PASS' in simlog, 'Behavior test not complete')
    require(len(re.findall(r'^BIDIR ', simlog, re.M)) == 16, 'Missing bidirectional cases')
    multi = second / 'multicorner'
    terminal(current['execution'], json.loads((multi / 'terminal_observation.json').read_text())['state'])
    verify(multi, current['execution']['output_sha256'])
    logfile = (multi / 'tool.log').read_text()
    require('OpenROAD v2.0-27244-gfecb04286' in logfile and 'IHP_IO_SUITE_STA_COMPLETE' in logfile, 'Fixed tool/completion missing')
    require((multi / 'run.tcl').read_text() == continuation.tcl(), 'Unexpected repaired script')
    require((multi / 'input.def').read_bytes() == (first / 'tt/input.def').read_bytes(), 'Fixture changed in continuation')
    require((multi / 'input.sdc').read_bytes() == (first / 'tt/input.sdc').read_bytes(), 'Constraints changed in continuation')
    interface = base.interfaces(root)
    require(interface == json.loads((first / 'interface_audit.json').read_text()), 'Stored interface audit differs')
    evidence[FIRST + '/interface_audit.json'] = sha(first / 'interface_audit.json')
    corners = {}
    canonical_sdc = None
    canonical_def = None
    for corner in base.CORNERS:
        out = multi / corner
        require('IHP_IO_SUITE_CORNER_COMPLETE_' + corner in logfile, 'Missing corner completion')
        sdc = (out / 'readback.sdc').read_text()
        contract = validate_sdc(sdc)
        normalized = '\n'.join(l for l in sdc.splitlines() if not l.lstrip().startswith('#'))
        if canonical_sdc is not None:
            require(normalized == canonical_sdc and (out / 'readback.def').read_bytes() == canonical_def, 'Physical or SDC corner confound')
        canonical_sdc, canonical_def = normalized, (out / 'readback.def').read_bytes()
        terms = list(csv.DictReader(io.StringIO((out / 'actual_terms.tsv').read_text()), delimiter='\t'))
        require(len(terms) == 42 and len({r['instance'] for r in terms}) == 6, 'Fixture instance/terminal count changed')
        pg = [r for r in terms if r['pin'] in base.PG]
        require(len(pg) == 24 and all(r['net'] == r['pin'] and r['signal_type'] == base.PG[r['pin']] for r in pg), 'PG terminal mapping changed')
        rows = violations((out / 'electrical_violators.rpt').read_text())
        require(len(rows) == 6 and all(r['check'] == 'max slew' and abs(r['limit'] - 1.2) < 1e-6 for r in rows), 'Slew result changed; review required')
        paths = {mode: path_slacks((out / (mode + '_path.rpt')).read_text()) for mode in ('out16', 'bidir_tx', 'bidir_rx', 'input', 'bidir_highz')}
        require(not paths['bidir_highz']['path_found'] and all(paths[m]['path_found'] for m in ('out16', 'bidir_tx', 'bidir_rx', 'input')), 'Mode paths do not match intended active/disabled states')
        corners[corner] = {'execution_complete': True, 'pvt': base.CORNERS[corner], 'electrical_acceptance': 'FAIL',
            'constraints': contract, 'electrical_violation_rows': rows, 'path_results': paths,
            'raw_default_power_w': power_groups((out / 'raw_default_power.rpt').read_text()),
            'constraint_warnings': (out / 'constraints.rpt').read_text().strip(),
            'explicit_pg_terminal_connections': 24, 'physical_pg_continuity_proven': False}
    count_rows = list(csv.DictReader(io.StringIO((multi / 'combined_counts.tsv').read_text()), delimiter='\t'))
    counts = {r['check']: int(r['count']) for r in count_rows}
    require(counts == {'max_slew': 6, 'max_capacitance': 0, 'max_fanout': 0, 'setup': 2, 'hold': 0}, 'Combined count changed or missing; review required')
    return {'schema_version': '1.0.0', 'report_id': 'ihp_io_suite-digital-sta-20260910-001', 'generated_at': now(),
        'audit_result': 'PASS', 'qualification_result': 'FAIL', 'classification': 'official_suite_behavior_pass_three_corner_local_STA_fail',
        'fixed_pdk_commit': current['fixed_pdk_commit'], 'fixed_image': current['fixed_image'], 'interface_audit': interface,
        'behavior_simulation': {'result': 'PASS', 'assertions': 42, 'failures': 0, 'bidirectional_binary_cases': 16,
            'four_state_transfer': True, 'high_impedance_and_contention_checked': True, 'enable_active_high': True,
            'tool': (first / 'simulation/compiler_version.txt').read_text().splitlines()[0], 'elapsed_seconds': original['runs']['simulation']['elapsed_seconds'],
            'analog_voltage_ESD_power_off_behavior_proven': False},
        'original_attempt': {'status': 'failed', 'tt_exit_code': 1, 'reason': 'report_case_analysis unavailable', 'ff': 'NOT_RUN', 'ss': 'NOT_RUN', 'preserved': True},
        'continuation': {'status': 'completed', 'exit_code': 0, 'oom_killed': False, 'elapsed_seconds': current['execution']['elapsed_seconds'], 'source_run': SECOND},
        'corners': corners, 'aggregate_tt_ff_ss_counts': counts, 'eda_processes_used': 3,
        'scope': 'Six independent official IO instances; output/input/high-Z modes use explicit top port directions and fixed enable cases. Pin plus lumped RC only.',
        'clock_and_bondpad': {'input_clock_period_ns': 10, 'input_clock_transition_ns': .2, 'clock_io_cell': 'sg13g2_IOPadIn',
            'no_liberty_bondpad_present': False, 'bondpad_model_included': False,
            'note': 'Clock is declared at top clk_pad and passes through the official receiver. No full clock tree/FF/SRAM activity qualification; no bondpad direction override applied.'},
        'source_pdk_modified': False, 'main_design_modified': False, 'new_liberty_applied_to_old_gds': False,
        'workload_power_w': None, 'chip_ppa_changed': False, 'public_rule_signoff': False,
        'limitations': ['1.2 ns remains explicit despite the new library default of 3.5 ns.',
            'Three limiting signal nets produce six STA pin/port violation rows; these are not six independent physical failures.',
            'SS output and bidirectional TX max paths fail the chosen 100 MHz local delay budget.',
            'Two inactive core inputs lack input delays; four observation/high-Z/clock outputs lack output delays. Complete chip timing qualification is not claimed.',
            'Core observation load 0.05 pF is an explicit tiny-fixture assumption, not a measured whole-core load.',
            'No GDS/route/DRC/LVS/IR/EM or analog characterization performed by this digital/STA branch.'],
        'next_gate': 'Official suite is not a drop-in closure at 15 pF and 1.2 ns. Preserve both requirements; assess actual board/output timing specification and physically characterized driver alternatives without silently relaxing either.',
        'evidence_sha256': dict(sorted(evidence.items())), 'unique_hash_count': len(evidence)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = audit(root)
    with (root / args.output).open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'audit': report['audit_result'], 'qualification': report['qualification_result'], 'hashes': report['unique_hash_count']}))
