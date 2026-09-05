#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Version 3: compose preserved tasks with an independently audited deep replay."""
import argparse
import json
import math
import re
import shlex
from datetime import datetime
from pathlib import Path

from audit_bondpad_integration import audit
from audit_io_ring_composite_v2 import (
    ERROR, analyze as analyze_v2, execution_gate, maximal_categories,
    validate_replay_report,
)
from run_io_ring_floorplan import IMAGE, now, sha, write

CHANGES = {
    'threads=4': 'threads=1',
    'report=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.lyrdb': 'report=/output/maximal.lyrdb',
    'log=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.log': 'log=/output/maximal.log',
}
REQUIRED = {'tool.log', 'maximal.log', 'maximal.lyrdb',
            'terminal_observation.json', 'resource_samples.json'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def zero(value):
    return type(value) is int and value == 0


def timestamp(value):
    require(isinstance(value, str), 'Missing observation timestamp')
    # Docker emits nanoseconds; Python 3.10 accepts at most microseconds.
    # Sub-microsecond truncation is sufficient for these second-scale intervals.
    value = re.sub(r'(\.\d{6})\d+(?=Z$|[+-]\d{2}:\d{2}$)', r'\1', value)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None and result.year > 2000, 'Invalid observation timestamp')
    return result


def validate_arguments(original, actual):
    require(sum(x in CHANGES for x in original) == 3 and 'run_mode=deep' in original,
            'Expected exactly three documented changes and original deep mode')
    require(actual == [CHANGES.get(x, x) for x in original],
            'Replay changed mode, rule, source, or an undocumented argument')


def validate_command(root, replay, manifest, original):
    validate_arguments(original, manifest.get('replay_rule_command'))
    require(manifest.get('original_rule_command') == original, 'Original command provenance mismatch')
    changes = [[x, CHANGES[x]] for x in original if x in CHANGES]
    require(manifest.get('changed_rule_arguments') == changes, 'Changed-argument inventory mismatch')
    command = manifest.get('command')
    require(isinstance(command, list) and len(command) == 23, 'Unexpected Docker invocation')
    expected = ['docker', 'run', '--name', replay.name, '--cpus', '2', '--memory', '8g',
                '--user', '1000:1000', '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                '--entrypoint', '/bin/bash', '-v', f'{root}:/work:ro',
                '-v', f'{replay}:/output:rw', IMAGE, '-lc']
    require(command[:-1] == expected, 'Docker image, limits, mounts, or invocation changed')
    prefix = ['timeout', '--verbose', '--signal=TERM', '--kill-after=15s', '900s']
    require(shlex.split(command[-1]) == prefix + manifest['replay_rule_command'],
            'Actual shell command differs from declared rule command')
    require(manifest.get('run_id') == replay.name, 'Replay run identity mismatch')
    require(manifest.get('limits') == {'cpus': 2, 'memory_gb': 8, 'inner_seconds': 900,
                                     'kill_grace_seconds': 15, 'outer_seconds': 945},
            'Recorded resource limits mismatch')


def verify_hashes(root, hashes):
    require(isinstance(hashes, dict) and bool(hashes), 'Missing source hash inventory')
    for name, digest in hashes.items():
        path = Path(name)
        require(not path.is_absolute() and '..' not in path.parts, 'Unsafe evidence path')
        require(isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest)
                and (root/path).is_file() and sha(root/path) == digest,
                'Evidence hash mismatch: ' + name)


def validate_runtime_source_inventory(manifest):
    require('scripts/run_io_ring_maximal_diagnostic.py' in manifest.get('source_sha256', {}),
            'Missing deep runner source hash')
    require(manifest.get('source_hashes_unchanged') is True,
            'Source preservation at execution time failed or unknown')


def validate_terminal(manifest, terminal, samples, run_id):
    """Require recorded real exited state, not a runner's summary boolean."""
    require(zero(manifest.get('returncode')) and manifest.get('status') == 'completed'
            and manifest.get('execution_complete') is True, 'Replay execution unsuccessful')
    require(manifest.get('outer_timeout_expired') is False
            and manifest.get('timeout_verbose_signal_lines') == [], 'Replay timeout observed or unknown')
    require(zero(terminal.get('state_returncode')) and zero(terminal.get('resources_returncode')),
            'Terminal Docker observation failed or missing')
    state = terminal.get('state', {})
    require(state == manifest.get('terminal_container_state'), 'Terminal state differs from manifest')
    require(state.get('Status') == 'exited' and zero(state.get('ExitCode'))
            and zero(state.get('Pid')) and state.get('Error') == '', 'Container not cleanly exited')
    require(all(state.get(key) is False for key in ('Running', 'OOMKilled', 'Dead', 'Paused', 'Restarting')),
            'Container running/OOM/dead/paused/restarting or terminal flags unknown')
    start, finish = timestamp(state.get('StartedAt')), timestamp(state.get('FinishedAt'))
    observed = timestamp(terminal.get('observed_at'))
    require(start < finish <= observed, 'Invalid terminal observation time order')
    manifest_start = timestamp(manifest.get('started_at'))
    manifest_finish = timestamp(manifest.get('finished_at'))
    elapsed = manifest.get('elapsed_seconds')
    require(type(elapsed) in (int, float) and math.isfinite(elapsed) and 0 < elapsed <= 945,
            'Invalid elapsed time or execution exceeds bounded envelope')
    require(manifest_start <= start < finish <= observed <= manifest_finish,
            'Manifest and Docker execution timestamps disagree')
    require(abs((manifest_finish-manifest_start).total_seconds()-elapsed) <= 2,
            'Manifest wall time and elapsed time disagree')
    resources = terminal.get('resources', {})
    require(resources.get('Name') == run_id and resources.get('Container') == run_id,
            'Terminal observation belongs to another container')
    require(isinstance(resources.get('ID'), str) and resources['ID'], 'Missing container ID')
    require(isinstance(samples, list) and samples, 'No resource samples')
    previous = start
    memory_bytes = []
    for sample in samples:
        require(zero(sample.get('state_returncode')) and zero(sample.get('resources_returncode')),
                'Resource observation failed or missing')
        at = timestamp(sample.get('observed_at'))
        require(previous < at < finish, 'Sample time order outside actual execution')
        previous = at
        current, usage = sample.get('state', {}), sample.get('resources', {})
        require(current.get('Status') == 'running' and current.get('Running') is True
                and type(current.get('Pid')) is int and current['Pid'] > 0
                and current.get('StartedAt') == state['StartedAt']
                and current.get('OOMKilled') is False, 'Sample is not the same healthy running execution')
        require(usage.get('Name') == run_id and usage.get('Container') == run_id
                and usage.get('ID') == resources['ID'], 'Sample belongs to another container')
        match = re.fullmatch(r'([\d.]+)(MiB|GiB) / 8GiB', usage.get('MemUsage', ''))
        require(match is not None, 'Missing or unexpected resource sample memory/limit')
        used = float(match[1]) * (2**20 if match[2] == 'MiB' else 2**30)
        require(0 < used <= 8 * 2**30, 'Invalid sampled memory usage')
        memory_bytes.append(used)
    return {'terminal_container_state_verified': True, 'resource_samples_verified': True,
            'sample_count': len(samples), 'sampled_max_memory_mib': max(memory_bytes)/2**20,
            'memory_peak_scope': 'Maximum of periodic Docker samples, not a continuous peak measurement.',
            'terminal_container_state': state, 'container_id': resources['ID']}


def validate_deep_outputs(replay, manifest, categories):
    hashes = manifest.get('outputs_sha256', {})
    require(REQUIRED <= set(hashes), 'Deep replay missing required output hashes')
    report = validate_replay_report(replay, manifest, categories, 'io_ring_sealed')
    terminal = json.loads((replay/'terminal_observation.json').read_text())
    samples = json.loads((replay/'resource_samples.json').read_text())
    state = validate_terminal(manifest, terminal, samples, replay.name)
    for name in ('tool.log', 'maximal.log'):
        text = (replay/name).read_text(errors='replace')
        require(not ERROR.search(text) and 'DRC run for maximum ruleSet completed in' in text,
                'Missing clean terminal completion: ' + name)
        require('Klayout will use 1 thread(s)' in text and 'deep mode is enabled for sg13g2_maximal runset.' in text,
                'Actual mode or thread log differs: ' + name)
    tool = (replay/'tool.log').read_text(errors='replace')
    counts = re.findall(r'^Number of DRC errors for maximum rule set: (\d+)$', tool, re.M)
    require(len(counts) == 1 and int(counts[0]) == report['markers'], 'Log/report marker count disagreement')
    require(type(manifest.get('maximal_raw_markers')) is int
            and manifest['maximal_raw_markers'] == report['markers'], 'Manifest/report marker count disagreement')
    return {**report, **state, 'returncode': manifest['returncode'], 'terminal_completion': True,
            'error_free': True, 'source_identity_verified': True}


def analyze(root, prior, flat, replay, preserved_v2):
    # Recompute all original task/hash checks and retain the failed flat history.
    baseline = analyze_v2(root, prior, flat)
    archived = json.loads(preserved_v2.read_text())
    require({k:v for k,v in baseline.items() if k != 'generated_at'} ==
            {k:v for k,v in archived.items() if k != 'generated_at'},
            'Preserved v2 audit no longer reproduces')
    require(baseline['replay']['returncode'] == 137 and baseline['replay']['markers'] is None
            and baseline['composite_rule_execution_complete'] is False,
            'Expected preserved unsuccessful flat replay')
    pm = json.loads((prior/'manifest.json').read_text())
    fm = json.loads((flat/'manifest.json').read_text())
    rm = json.loads((replay/'manifest.json').read_text())
    require(rm.get('original_run') == prior.name, 'Replay prior-run mismatch')
    validate_runtime_source_inventory(rm)
    verify_hashes(root, rm.get('source_sha256'))
    for name, digest in fm['source_sha256'].items():
        require(rm['source_sha256'].get(name) == digest, 'Source/deck inventory changed: ' + name)
    require(rm['source_sha256'].get(str((flat/'manifest.json').relative_to(root))) == sha(flat/'manifest.json'),
            'Missing immutable flat provenance')
    validate_command(root, replay, rm, fm['original_command'])
    deck = root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_maximal.drc'
    facts = validate_deep_outputs(replay, rm, maximal_categories(deck))
    expected = set(pm['expected_rule_tasks'])
    healthy = {key:value['terminal_log_complete_and_error_free']
               for key,value in baseline['original_healthy_tasks'].items()}
    complete = execution_gate(expected, healthy, baseline['original_exception_tasks'], facts)
    complete = bool(complete and facts['terminal_container_state_verified'] and facts['resource_samples_verified'])
    # Only an empty maximal replay allows reuse of the original merged inventory.
    counts_valid = complete and facts['markers'] == 0
    arm = audit(root, prior)['arms'][0]
    sources = dict(rm['source_sha256'])
    sources.update(baseline['source_sha256'])
    files = [preserved_v2, replay/'manifest.json', root/'scripts/audit_io_ring_composite_v3.py',
             root/'tests/test_io_ring_composite_v3.py'] + [replay/name for name in REQUIRED]
    sources.update({str(path.relative_to(root)): sha(path) for path in files})
    return {
        **baseline, 'auditor_version': 3, 'generated_at': now(),
        'replay_run': replay.name, 'replay': facts,
        'preserved_v2_report': str(preserved_v2.relative_to(root)),
        'preserved_v2_recomputed_exactly_except_timestamp': True,
        'preserved_flat_replay': {'run': flat.name, **baseline['replay']},
        'run_mode_unchanged': 'deep', 'documented_argument_changes': rm['changed_rule_arguments'],
        'tool_image': IMAGE, 'maximal_report_category_count': len(maximal_categories(deck)),
        'causal_limit': 'The successful single-task replay also uses a different Docker CPU limit and '
                        'timeout envelope from the original full runner; it does not isolate multithreading '
                        'as the cause of the original signal-11 failure.',
        'composite_rule_execution_complete': complete,
        'composite_marker_inventory_complete': counts_valid,
        'composite_merged_markers': arm['merged_markers'] if counts_valid else None,
        'composite_density_marker_counts': arm['density_marker_counts'] if counts_valid else None,
        'composite_density_marker_scopes': arm['density_marker_scopes'] if counts_valid else None,
        'composite_non_density_markers': arm['non_density_markers'] if counts_valid else None,
        'composite_pad_markers': arm['pad_markers'] if counts_valid else None,
        'fixture_drc_passed': bool(counts_valid and arm['merged_markers'] == 0),
        'scope': 'IO-only ring: 39 original successful tasks plus one successful deep maximal replay. '
                 'Original signal-11 and flat exit-137 runs remain failed. No core, full-chip DRC/LVS, or signoff.',
        'source_sha256': sources,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-run', required=True)
    parser.add_argument('--flat-run', required=True)
    parser.add_argument('--replay-run', required=True)
    parser.add_argument('--preserved-v2', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    require(not args.output.exists(), 'Independent output required')
    result = analyze(root, root/'runs'/args.prior_run, root/'runs'/args.flat_run,
                     root/'runs'/args.replay_run, root/args.preserved_v2)
    write(args.output, result)
    print(json.dumps({key:result[key] for key in ('composite_rule_execution_complete',
          'composite_merged_markers', 'composite_density_marker_scopes', 'fixture_drc_passed')}))
