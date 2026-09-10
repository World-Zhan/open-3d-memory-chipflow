#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Apply one bounded eight-buffer ECO to the current full CTS candidate."""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from run_io_ring_floorplan import IMAGE, now, sha, write
from run_io_ring_maximal_diagnostic import observe
from run_croc_full_cts import CAPTURE, AFTER, replace_once


def diagnosis(source):
    text = (source / 'electrical_violators.rpt').read_text()
    fanout = text.split('max fanout\n', 1)[1].split('max capacitance\n', 1)[0]
    rows = re.findall(r'^(\S+)\s+(\d+)\s+(\d+)\s+(-?\d+)\s+\(VIOLATED\)$', fanout, re.M)
    expected = {f'clkbuf_2_{branch}_0_soc_clk_i_regs/X' for branch in range(4)}
    if {row[0] for row in rows} != expected or len(rows) != 4 or any(row[1:] != ('8', '16', '-8') for row in rows):
        raise ValueError('Require exactly the four observed fanout 16 versus limit 8 violations')
    with (source / 'after_iterms.tsv').open() as handle:
        terms = list(csv.DictReader(handle, delimiter='\t'))
    result = []
    for branch in range(4):
        name = f'clkbuf_2_{branch}_0_soc_clk_i_regs'
        drivers = [r for r in terms if r['instance'] == name and r['pin'] == 'X']
        if len(drivers) != 1:
            raise ValueError('Missing or duplicate diagnosed driver')
        net = drivers[0]['net']
        loads = sorted(r['instance'] + '/' + r['pin'] for r in terms if r['net'] == net and r['io_type'] == 'INPUT')
        if len(loads) != 16 or len(set(loads)) != 16:
            raise ValueError('Diagnosed branch no longer has 16 distinct loads')
        result.append({'driver': name + '/X', 'net': net, 'limit': 8, 'actual': 16, 'loads': loads})
    return result


def run(root, run_id):
    if not re.fullmatch(r'croc-full-io-cts-fanout-[a-zA-Z0-9_-]+', run_id):
        raise ValueError('Independent full CTS fanout run ID required')
    source = root / 'runs/croc-full-io-cts-20260909-001'
    gate_path = root / 'reports/placement/full-io-cts-extended-audit-20260909-001.json'
    gate = json.loads(gate_path.read_text())
    if gate.get('overall_result') != 'PASS' or gate.get('run_id') != source.name:
        raise ValueError('Current source CTS structural prerequisite failed')
    for rel, digest in gate['source_sha256'].items():
        if sha(root / rel) != digest:
            raise ValueError('Prerequisite evidence changed: ' + rel)
    diagnosed = diagnosis(source)
    dest = root / 'runs' / run_id
    dest.mkdir(exist_ok=False)
    work = dest / 'work/openroad'
    (work / 'scripts').mkdir(parents=True)
    (dest / 'inputs').mkdir()
    sources = {str(gate_path.relative_to(root)): sha(gate_path)}
    def copy(path, target):
        shutil.copyfile(path, target)
        sources[str(path.relative_to(root))] = sha(path)
    for path in sorted((source / 'work/openroad/scripts').iterdir()):
        if path.is_file():
            copy(path, work / 'scripts' / path.name)
    checkpoint = source / 'work/openroad/save/03_croc.cts.zip'
    sources[str(checkpoint.relative_to(root))] = sha(checkpoint)
    with zipfile.ZipFile(checkpoint) as archive:
        for suffix in ('odb', 'sdc'):
            (dest / 'inputs' / ('cts.' + suffix)).write_bytes(archive.read('03_croc.cts.' + suffix))
    for name in ('manifest.json', 'electrical_violators.rpt', 'after_iterms.tsv'):
        sources[str((source / name).relative_to(root))] = sha(source / name)
    for name in ('scripts/run_croc_full_cts_fanout.py', 'scripts/run_croc_full_cts.py',
                 'scripts/croc_cts_branch_odb_ndr_eco.tcl', 'scripts/run_io_ring_floorplan.py',
                 'scripts/run_io_ring_maximal_diagnostic.py', 'upstream/croc/env.sh'):
        sources[name] = sha(root / name)
    for folder in ('lef', 'lib'):
        for path in sorted((root / 'upstream/croc/technology' / folder).glob('*')):
            if path.is_file():
                sources[str(path.relative_to(root))] = sha(path)
    write(dest / 'diagnosed_branches.json', diagnosed)
    (dest / 'capture_placement.tcl').write_text(CAPTURE)
    (dest / 'after_placement.tcl').write_text(AFTER)
    edit = (root / 'scripts/croc_cts_branch_odb_ndr_eco.tcl').read_text()
    edit = replace_once(edit, 'set_thread_count 6', 'set_thread_count 2\nset report_dir /output')
    edit = replace_once(edit, 'read_db /input/cts.odb', '''read_db /output/inputs/cts.odb
read_sdc /output/inputs/cts.sdc
source scripts/reports.tcl
source /output/capture_placement.tcl
verify_placement_ports
setDefaultParasitics
set_propagated_clock [all_clocks]
estimate_parasitics -placement
capture_placement before
report_metrics before_cts
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/before_electrical_violators.rpt''')
    (dest / 'edit.tcl').write_text(edit)
    check = '''# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
source /output/capture_placement.tcl
read_db /output/eco_unplaced.odb
read_sdc /output/inputs/cts.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
set_propagated_clock [all_clocks]
detailed_placement
estimate_parasitics -placement
source /output/after_placement.tcl
report_metrics after_cts
write_db /output/cts.odb
puts {FULL_CTS_FANOUT_ECO_COMPLETE}
'''
    (dest / 'check.tcl').write_text(check)
    (dest / 'execute.sh').write_text('set -e\nsource /work/upstream/croc/env.sh\nopenroad -exit /output/edit.tcl\nopenroad -exit /output/check.tcl\n')
    command = ['docker', 'run', '--name', run_id, '--cpus', '2', '--memory', '8g', '--ulimit', 'core=0',
               '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp', '-e', 'QT_QPA_PLATFORM=offscreen',
               '-e', 'CROC_PDK=sg13g2', '-e', 'CROC_SKIP_TECH_SETUP=1', '--entrypoint', '/bin/bash',
               '-v', f'{root}:/work:ro', '-v', f'{dest}:/output:rw', '-w', '/output/work/openroad', IMAGE,
               '-lc', 'timeout --verbose --signal=TERM --kill-after=15s 180s /bin/bash /output/execute.sh']
    manifest = {'schema_version': '1.0.0', 'run_id': run_id, 'source_run': source.name, 'started_at': now(),
                'status': 'running', 'classification': 'full_cts_fanout_eco_candidate_not_route_or_signoff',
                'source_sha256': sources, 'command': command,
                'generated_inputs_sha256': {str(p.relative_to(dest)): sha(p) for p in dest.rglob('*') if p.is_file()},
                'limits': {'cpus': 2, 'memory_gb': 8, 'inner_seconds': 180, 'kill_grace_seconds': 15, 'outer_seconds': 215},
                'io_load_constraint_unchanged': True, 'original_layout_modified': False,
                'route_performed': False, 'public_rule_signoff': False, 'routing_ndr_policy_qualification': 'UNVERIFIED'}
    write(dest / 'manifest.json', manifest)
    start = time.monotonic()
    samples, outer_expired = [], False
    print(json.dumps({'run_id': run_id, 'status': 'starting', 'diagnosed_branches': len(diagnosed)}), flush=True)
    with (dest / 'tool.log').open('x') as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if time.monotonic() - start > 215:
                outer_expired = True
                stop = subprocess.run(['docker', 'stop', '--time', '5', run_id], capture_output=True, text=True, timeout=15)
                manifest['outer_stop_returncode'] = stop.returncode
                break
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                samples.append(observe(run_id))
                write(dest / 'resource_samples.json', samples)
                print(json.dumps({'run_id': run_id, 'elapsed_seconds': round(time.monotonic() - start, 1)}), flush=True)
        try:
            returncode = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            returncode = process.wait(timeout=10)
    terminal = observe(run_id)
    write(dest / 'terminal_observation.json', terminal)
    write(dest / 'resource_samples.json', samples)
    state = terminal.get('state', {})
    log = (dest / 'tool.log').read_text(errors='replace')
    complete = bool(returncode == 0 and state.get('Status') == 'exited' and state.get('ExitCode') == 0
                    and state.get('OOMKilled') is False and not outer_expired
                    and 'FULL_CTS_FANOUT_ECO_COMPLETE' in log and (dest / 'cts.odb').is_file())
    manifest.update(returncode=returncode, status='completed' if complete else 'failed', execution_complete=complete,
                    finished_at=now(), elapsed_seconds=time.monotonic() - start, outer_timeout_expired=outer_expired,
                    terminal_container_state=state, source_hashes_unchanged=all(sha(root / p) == v for p, v in sources.items()),
                    design_checks_require_independent_audit=True)
    if state.get('Status') == 'exited' and state.get('Running') is False:
        manifest['cleanup_returncode'] = subprocess.run(['docker', 'rm', run_id], capture_output=True, text=True, timeout=15).returncode
    else:
        manifest['cleanup_returncode'] = None
    manifest['outputs_sha256'] = {str(p.relative_to(dest)): sha(p) for p in dest.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    write(dest / 'manifest.json', manifest)
    print(json.dumps({key: manifest[key] for key in ('run_id', 'status', 'returncode', 'elapsed_seconds', 'terminal_container_state')}), flush=True)
    return 0 if complete else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id))
