#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Version 2: fail-closed composite audit with validated replay report identity."""
import argparse
import json
import re
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_bondpad_drc import antenna_complete
from audit_bondpad_integration import audit
from run_io_ring_floorplan import IMAGE, now, sha, write

ERROR = re.compile(r'(?im)^ERROR:|Signal number:|Traceback|CalledProcessError|std::bad_alloc|Killed|generated an exception')
CHANGES = {
    'threads=4': 'threads=1',
    'run_mode=deep': 'run_mode=flat',
    'report=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.lyrdb': 'report=/output/maximal.lyrdb',
    'log=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.log': 'log=/output/maximal.log',
}


def validate_arguments(original, actual):
    if sum(x in CHANGES for x in original) != 4:
        raise ValueError('Expected exactly four documented argument changes')
    if actual != [CHANGES.get(x, x) for x in original]:
        raise ValueError('Replay changed a rule, source, or undocumented argument')


def execution_gate(expected, observations, exceptions, replay):
    """Missing task evidence or an unsuccessful replay must stay incomplete."""
    healthy = expected - {'sg13g2_maximal'}
    return bool(
        len(expected) == 40 and 'sg13g2_maximal' in expected
        and set(observations) == healthy
        and all(v is True for v in observations.values())
        and exceptions == ['sg13g2_maximal']
        and type(replay.get('returncode')) is int
        and replay.get('returncode') == 0
        and replay.get('report_structure_valid') is True
        and replay.get('required_output_hashes_verified') is True
        and replay.get('terminal_completion') is True
        and replay.get('error_free') is True
        and type(replay.get('markers')) is int
        and replay['markers'] >= 0
        and replay.get('source_identity_verified') is True
    )



def maximal_categories(deck_path):
    names = set(re.findall(r'\.output\("([^"\n]+)"', deck_path.read_text()))
    if not names:
        raise ValueError('No maximal rule category definitions found')
    return names


def validate_report(report_path, expected_categories, expected_top):
    tree = ET.parse(report_path)
    root = tree.getroot()
    if root.tag != 'report-database':
        raise ValueError('Not a KLayout report-database')
    for tag in ('cells', 'categories', 'items', 'top-cell'):
        if len(root.findall(tag)) != 1:
            raise ValueError('Missing or duplicate report node: ' + tag)
    if root.findtext('top-cell') != expected_top:
        raise ValueError('Replay report top-cell mismatch')
    cells = [c.findtext('name') for c in root.findall('./cells/cell')]
    if not cells or any(not n for n in cells) or len(cells) != len(set(cells)) or expected_top not in cells:
        raise ValueError('Invalid replay cells/top-cell inventory')
    categories = [c.findtext('name') for c in root.findall('./categories/category')]
    if not expected_categories or len(categories) != len(set(categories)) or set(categories) != expected_categories:
        raise ValueError('Maximal rule category inventory mismatch')
    items = root.findall('./items/item')
    for item in items:
        category = (item.findtext('category') or '').strip("'\"")
        cell = (item.findtext('cell') or '').strip("'\"")
        if category not in expected_categories or cell not in cells or item.find('values') is None:
            raise ValueError('Invalid marker cell/category/values')
    return len(items)


def validate_replay_report(folder, manifest, expected_categories, expected_top):
    rc = manifest.get('returncode')
    if type(rc) is not int:
        raise ValueError('Replay returncode must be an integer, not bool/null/string')
    hashes = manifest.get('outputs_sha256')
    if not isinstance(hashes, dict):
        raise ValueError('Missing output hash inventory')
    required = {'tool.log', 'maximal.log', 'maximal.lyrdb'}
    missing = sorted(required - set(hashes))
    if rc == 0 and missing:
        raise ValueError('Successful replay missing required output hashes: ' + ', '.join(missing))
    for name, digest in hashes.items():
        if Path(name).name != name or not (folder/name).is_file() or sha(folder/name) != digest:
            raise ValueError('Invalid replay output hash: ' + name)
    result = {'report_structure_valid': False, 'required_output_hashes_verified': not missing,
              'missing_required_output_hashes': missing, 'markers': None, 'report_error': None}
    report = folder/'maximal.lyrdb'
    if not report.is_file():
        result['report_error'] = 'missing maximal.lyrdb; incomplete, marker count unknown'
        if rc == 0:
            raise ValueError(result['report_error'])
        return result
    try:
        count = validate_report(report, expected_categories, expected_top)
    except (ET.ParseError, ValueError) as exc:
        if rc == 0:
            raise ValueError('Invalid successful replay report: ' + str(exc)) from exc
        result['report_error'] = str(exc)
        return result
    # An unbound report from a failed run is not accepted as terminal evidence.
    if 'maximal.lyrdb' not in hashes:
        result['report_error'] = 'maximal.lyrdb is not hash-bound'
        return result
    result.update(markers=count, report_structure_valid=True)
    return result


def analyze(root, prior, replay):
    pm = json.loads((prior / 'manifest.json').read_text())
    rm = json.loads((replay / 'manifest.json').read_text())
    if 'returncode' not in rm:
        raise ValueError('Replay still running; do not infer terminal state')
    if len(pm['arms']) != 1 or type(pm['arms'][0]['returncode']) is not int or pm['arms'][0]['returncode'] != 1:
        raise ValueError('Expected one preserved failed original arm')
    for rel, value in rm['source_sha256'].items():
        if sha(root / rel) != value:
            raise ValueError('Replay source changed: ' + rel)
    for rel, value in pm['source_sha256'].items():
        if rm['source_sha256'].get(rel) != value:
            raise ValueError('Source/deck identity mismatch: ' + rel)
    for name, value in rm['outputs_sha256'].items():
        if sha(replay / name) != value:
            raise ValueError('Replay output changed: ' + name)
    # Recompute the original audit from actual GDS, full report, and all hashes.
    original_audit = audit(root, prior)
    arm = original_audit['arms'][0]
    folder = prior / arm['name']
    tool = (folder / 'tool.log').read_text(errors='replace')
    matches = re.findall(r"sg13g2_maximal generated an exception: Command '(.*?)' returned non-zero exit status 11\.", tool, re.S)
    if len(matches) != 1:
        raise ValueError('Expected one captured maximal signal-11 command')
    command = shlex.split(matches[0])
    if command != rm['original_command']:
        raise ValueError('Original command differs from replay provenance')
    actual = shlex.split(rm['command'][-1])
    prefix = ['timeout', '--signal=TERM', '--kill-after=15s', '600s']
    if actual[:4] != prefix or IMAGE not in rm['command'] or IMAGE not in pm['arms'][0]['command']:
        raise ValueError('Timeout/tool image mismatch')
    validate_arguments(command, actual[4:])
    exceptions = re.findall(r'\b(\w+) generated an exception:', tool)
    expected = set(pm['expected_rule_tasks'])
    deck = root / 'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks'
    derived = {'antenna', 'density', 'sg13g2_maximal'}
    for group in ('feol', 'beol', 'forbidden', 'geometry', 'pin'):
        derived.update('_'.join(p.stem.split('_')[2:]) for p in (deck / group).glob('*.drc'))
    if expected != derived or set(arm['rule_task_completion']) != expected:
        raise ValueError('Rule task inventory mismatch')
    report = next(folder.glob('*_full.lyrdb'))
    categories = {e.findtext('name') for e in ET.parse(report).findall('.//categories/category')}
    observations, evidence = {}, {}
    for task in sorted(expected - {'sg13g2_maximal'}):
        logpath = folder / f'{arm["name"]}_{arm["name"]}_{task}.log'
        text = logpath.read_text(errors='replace')
        complete = antenna_complete(text, categories) if task == 'antenna' else bool(re.search(r'completed in\s+[\d.]+\s+seconds', text, re.I))
        observations[task] = bool(complete and not ERROR.search(text))
        evidence[task] = {'log_sha256': sha(logpath), 'terminal_log_complete_and_error_free': observations[task]}
    replay_text = (replay / 'tool.log').read_text(errors='replace')
    replay_report = replay / 'maximal.lyrdb'
    report_facts = validate_replay_report(replay, rm, maximal_categories(deck / 'sg13g2_maximal.drc'), 'io_ring_sealed')
    markers = report_facts['markers']
    facts = {
        **report_facts, 'returncode': rm['returncode'],
        'terminal_completion': 'DRC run for maximum ruleSet completed in' in replay_text,
        'error_free': not bool(ERROR.search(replay_text)),
        'markers': markers, 'source_identity_verified': True,
    }
    complete = execution_gate(expected, observations, exceptions, facts)
    if tool.count('ERROR: Signal number: 11') != 1 or 'Total DRC Run time:' not in tool:
        complete = False
    # The original merged DB excluded the failed task. Only an empty successful
    # replay permits reuse of its counts as the composite marker inventory.
    counts_valid = complete and markers == 0
    result = {
        'schema_version': '1.0.0', 'auditor_version': 2, 'generated_at': now(),
        'classification': 'io_only_ring_composite_task_audit_not_full_chip_signoff',
        'original_run': prior.name, 'replay_run': replay.name,
        'original_run_execution_complete': False, 'original_runner_returncode': 1,
        'original_exception_tasks': exceptions,
        'original_healthy_tasks': evidence, 'replay': facts,
        'all_rule_switches_and_source_hashes_unchanged': True,
        'composite_rule_execution_complete': complete,
        'composite_marker_inventory_complete': counts_valid,
        'original_merged_markers': arm['merged_markers'],
        'composite_merged_markers': arm['merged_markers'] if counts_valid else None,
        'composite_density_marker_counts': arm['density_marker_counts'] if counts_valid else None,
        'composite_density_marker_scopes': arm['density_marker_scopes'] if counts_valid else None,
        'composite_non_density_markers': arm['non_density_markers'] if counts_valid else None,
        'composite_pad_markers': arm['pad_markers'] if counts_valid else None,
        'fixture_drc_passed': bool(counts_valid and arm['merged_markers'] == 0),
        'public_rule_signoff': False, 'full_chip_drc_lvs_performed': False,
        'scope': '39 original task logs/merged DB plus 1 separately executed maximal task; original failed run remains failed.',
        'source_sha256': {str(p.relative_to(root)): sha(p) for p in (
            prior / 'manifest.json', prior / 'audit.json', report, folder / 'tool.log',
            replay / 'manifest.json', replay / 'tool.log',
            root / 'scripts/audit_io_ring_composite.py',
            root / 'scripts/audit_io_ring_composite_v2.py',
            deck / 'sg13g2_maximal.drc',
        )},
    }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-run', required=True)
    parser.add_argument('--replay-run', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = analyze(root, root / 'runs' / args.prior_run, root / 'runs' / args.replay_run)
    if args.output.exists():
        raise ValueError('Independent output required')
    write(args.output, result)
    print(json.dumps({k: result[k] for k in ('composite_rule_execution_complete', 'composite_merged_markers', 'fixture_drc_passed')}))
