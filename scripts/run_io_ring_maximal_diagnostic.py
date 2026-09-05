#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded single-thread deep replay with retained terminal container evidence."""
import argparse
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from audit_io_ring_composite_v2 import ERROR, maximal_categories, validate_report
from run_io_ring_floorplan import IMAGE, now, sha, write


def observe(name):
    observation = {'observed_at': now()}
    for key, args in (
        ('state', ['docker', 'inspect', '--format', '{{json .State}}', name]),
        ('resources', ['docker', 'stats', '--no-stream', '--format', '{{json .}}', name]),
    ):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=12)
            observation[key + '_returncode'] = result.returncode
            if result.returncode == 0 and result.stdout.strip():
                observation[key] = json.loads(result.stdout)
            else:
                observation[key + '_error'] = result.stderr.strip()[:400]
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            observation[key + '_error'] = str(exc)
    return observation


def run(root, run_id):
    if not re.fullmatch(r'croc-io-ring-maximal-deep1-[a-zA-Z0-9_-]+', run_id):
        raise ValueError('Independent run ID required')
    prior = root/'runs/croc-io-ring-drc-20260905-001'
    original_replay = root/'runs/croc-io-ring-maximal-flat-20260905-001/manifest.json'
    pm = json.loads((prior/'manifest.json').read_text())
    rm = json.loads(original_replay.read_text())
    for rel, digest in rm['source_sha256'].items():
        if sha(root/rel) != digest:
            raise ValueError('Source changed: ' + rel)
    source_command = rm['original_command']
    changes = {
        'threads=4': 'threads=1',
        'report=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.lyrdb': 'report=/output/maximal.lyrdb',
        'log=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.log': 'log=/output/maximal.log',
    }
    if sum(arg in changes for arg in source_command) != 3 or 'run_mode=deep' not in source_command:
        raise ValueError('Unexpected original mode/output/threads')
    args = [changes.get(arg, arg) for arg in source_command]
    dest = root/'runs'/run_id
    dest.mkdir(exist_ok=False)
    command = ['docker', 'run', '--name', run_id, '--cpus', '2', '--memory', '8g',
        '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1',
        '--entrypoint', '/bin/bash', '-v', f'{root}:/work:ro', '-v', f'{dest}:/output:rw',
        IMAGE, '-lc', shlex.join(['timeout', '--verbose', '--signal=TERM', '--kill-after=15s', '900s', *args])]
    files = [original_replay, prior/'manifest.json', root/'scripts/run_io_ring_maximal_diagnostic.py',
        root/'scripts/audit_io_ring_composite_v2.py', root/'scripts/run_io_ring_floorplan.py']
    sources = dict(rm['source_sha256'])
    sources.update({str(path.relative_to(root)): sha(path) for path in files})
    manifest = {
        'schema_version': '1.0.0', 'run_id': run_id,
        'classification': 'single_maximal_task_runtime_diagnostic_not_full_chip_signoff',
        'started_at': now(), 'status': 'running', 'original_run': prior.name,
        'command': command, 'source_sha256': sources, 'original_rule_command': source_command,
        'replay_rule_command': args, 'changed_rule_arguments': [[a, changes[a]] for a in source_command if a in changes],
        'all_rule_enable_disable_arguments_unchanged': True, 'run_mode_unchanged': 'deep',
        'hypothesis': 'The terminal failure may depend on deep-engine multithreading; replay only maximal with one thread and retain actual resource/exit evidence.',
        'limits': {'cpus': 2, 'memory_gb': 8, 'inner_seconds': 900, 'kill_grace_seconds': 15, 'outer_seconds': 945},
        'public_rule_signoff': False, 'whole_chip_modified': False,
    }
    write(dest/'manifest.json', manifest)
    samples = []
    start = time.monotonic()
    outer_expired = False
    with (dest/'tool.log').open('x') as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if time.monotonic() - start > 945:
                outer_expired = True
                stop = subprocess.run(['docker', 'stop', '--time', '5', run_id], capture_output=True, text=True, timeout=15)
                manifest['outer_stop_returncode'] = stop.returncode
                break
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                observation = observe(run_id)
                samples.append(observation)
                write(dest/'resource_samples.json', samples)
                state = observation.get('state', {})
                print(json.dumps({'run_id': run_id, 'elapsed_seconds': round(time.monotonic()-start, 1),
                    'container_status': state.get('Status'), 'memory': observation.get('resources', {}).get('MemUsage')}), flush=True)
        try:
            returncode = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            # Terminate only the client after the container stop request; the
            # retained state below determines whether cleanup is safe.
            process.terminate()
            returncode = process.wait(timeout=10)
    terminal = observe(run_id)
    write(dest/'terminal_observation.json', terminal)
    write(dest/'resource_samples.json', samples)
    state = terminal.get('state', {})
    log_text = (dest/'tool.log').read_text(errors='replace')
    report = dest/'maximal.lyrdb'
    markers = None
    report_error = None
    if report.exists():
        try:
            deck = root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_maximal.drc'
            markers = validate_report(report, maximal_categories(deck), 'io_ring_sealed')
        except Exception as exc:
            report_error = type(exc).__name__ + ': ' + str(exc)
    clean = bool(returncode == 0 and state.get('Status') == 'exited' and state.get('ExitCode') == 0
        and state.get('OOMKilled') is False and markers is not None and not ERROR.search(log_text)
        and 'DRC run for maximum ruleSet completed in' in log_text and not outer_expired)
    manifest.update(returncode=returncode, finished_at=now(), elapsed_seconds=time.monotonic()-start,
        status='completed' if clean else 'failed', execution_complete=clean, maximal_raw_markers=markers,
        report_validation_error=report_error, outer_timeout_expired=outer_expired,
        timeout_verbose_signal_lines=[line for line in log_text.splitlines() if line.startswith('timeout:')],
        terminal_container_state=state, source_hashes_unchanged=all(sha(root/p)==v for p,v in sources.items()))
    # Normal cleanup only after inspecting the actual terminal state. No force
    # removal or new invocation is used to hide a still-running process.
    if state.get('Status') == 'exited' and state.get('Running') is False:
        cleanup = subprocess.run(['docker', 'rm', run_id], capture_output=True, text=True, timeout=15)
        manifest['cleanup_returncode'] = cleanup.returncode
    else:
        manifest['cleanup_returncode'] = None
    manifest['outputs_sha256'] = {p.name: sha(p) for p in dest.iterdir() if p.is_file() and p.name != 'manifest.json'}
    write(dest/'manifest.json', manifest)
    print(json.dumps({key: manifest[key] for key in ('run_id', 'returncode', 'status', 'execution_complete', 'maximal_raw_markers', 'terminal_container_state')}), flush=True)
    return 0 if clean else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id))
