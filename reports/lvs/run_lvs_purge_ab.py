#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded two-leaf strict LVS A/B using immutable copied decks and upstream purge fix."""
from datetime import datetime, timezone
import base64
import difflib
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path('/home/james_zhan/projects/open-3d-memory-chipflow')
STAGE = Path('/mnt/c/Users/James Zhan/.codex/visualizations/2026/09/05/01a06f53-62f0-7bb1-93a3-51fd2e527fa7')
RUN = ROOT / 'runs/croc-lvs-leaf-purge-ab-20260905-001'
IMAGE = 'sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
DECK_REL = Path('ihp-sg13g2/libs.tech/klayout/tech/lvs')
PDK = ROOT / 'upstream/ihp-open-pdk'
CELLS = ['sg13g2_DCNDiode', 'sg13g2_DCPDiode']

def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def main():
    RUN.mkdir()
    (RUN/'inputs').mkdir()
    (ROOT/'reports/lvs').mkdir(exist_ok=True)
    for name in ('run_lvs_purge_ab.py', 'probe_lvs_leaf_source_identity.py', 'analyze_lvs_purge_ab.py'):
        shutil.copyfile(STAGE/name, RUN/name)
        shutil.copyfile(STAGE/name, ROOT/'reports/lvs'/name)
    for name in ('official_purge_fix_blob.json', 'official_purge_fix_commit.json'):
        shutil.copyfile(STAGE/name, RUN/name)
    blob = json.loads((RUN/'official_purge_fix_blob.json').read_text(encoding='utf-8-sig'))
    fix = base64.b64decode(blob['content'])
    assert hashlib.sha1(b'blob '+str(len(fix)).encode()+b'\0'+fix).hexdigest() == blob['sha']
    original_path = PDK/DECK_REL/'rule_decks/rfmos_model_mapping.lvs'
    original = original_path.read_bytes()
    needle = b'\n  target_netlist.purge_devices\n  target_netlist.purge\n'
    assert original.count(needle) == 1
    assert original.replace(needle, b'') == fix, 'Candidate must be byte-identical to official commit 6ff43baf'
    copied_files = []
    for arm in ('control', 'upstream_purge_fix'):
        prefix = RUN/'decks'/arm
        dest = prefix/DECK_REL
        dest.mkdir(parents=True)
        shutil.copyfile(PDK/'versions.txt', prefix/'versions.txt')
        for name in ('run_lvs.py', 'sg13g2.lvs'):
            shutil.copyfile(PDK/DECK_REL/name, dest/name)
        shutil.copytree(PDK/DECK_REL/'rule_decks', dest/'rule_decks')
        if arm == 'upstream_purge_fix':
            (dest/'rule_decks/rfmos_model_mapping.lvs').write_bytes(fix)
        copied_files.extend(p for p in prefix.rglob('*') if p.is_file())
    (RUN/'upstream_purge_removal.patch').write_text(''.join(difflib.unified_diff(original.decode().splitlines(True), fix.decode().splitlines(True),
        fromfile='a/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks/rfmos_model_mapping.lvs',
        tofile='b/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks/rfmos_model_mapping.lvs')))
    baseline = ROOT/'runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260830-rerun-002'
    source_inputs = []
    for cell in CELLS:
        dest = RUN/'inputs'/cell; dest.mkdir()
        for ext in ('gds', 'cdl'):
            source = baseline/cell/'inputs'/(cell+'.'+ext)
            shutil.copyfile(source, dest/source.name); source_inputs.append(source)
    tracked_source_paths = [original_path, PDK/DECK_REL/'run_lvs.py', PDK/DECK_REL/'sg13g2.lvs', PDK/'versions.txt',
        ROOT/'scripts/analyze_small_lvsdb.py', ROOT/'reports/bondpad/compare_input_io_cell.py',
        ROOT/'upstream/croc/technology/gds/sg13g2_io.gds', PDK/'ihp-sg13g2/libs.ref/sg13g2_io/gds/sg13g2_io.gds',
        *source_inputs]
    manifest = {'run_id': RUN.name, 'started_at': now(), 'repo_head': subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'], text=True).strip(),
        'classification': 'two_leaf_strict_lvs_upstream_fix_ab_not_chip_signoff',
        'official_fix_commit': '6ff43baf328844fc65c91886d82a0ce91f190fc9',
        'official_pr': 'https://github.com/IHP-GmbH/IHP-Open-PDK/pull/1105', 'image': IMAGE,
        'only_deck_difference': str(DECK_REL/'rule_decks/rfmos_model_mapping.lvs'),
        'strictness': {'run_mode': 'deep', 'flag_missing_ports': True, 'ignore_top_ports_mismatch': False,
            'implicit_nets': False, 'tap_extraction_enabled': True, 'simplify_enabled': True, 'purge_requested': False},
        'source_pdk_modified': False, 'full_chip_lvs_performed': False,
        'source_sha256': {str(path.relative_to(ROOT)): sha(path) for path in tracked_source_paths},
        'copied_deck_sha256': {str(path.relative_to(RUN)): sha(path) for path in copied_files},
        'input_sha256': {str(path.relative_to(RUN)): sha(path) for path in (RUN/'inputs').rglob('*') if path.is_file()},
        'script_sha256': {name:sha(RUN/name) for name in ('run_lvs_purge_ab.py','probe_lvs_leaf_source_identity.py','analyze_lvs_purge_ab.py')},
        'steps': []}
    save(RUN/'manifest.json', manifest)

    def execute(name, args, output, timeout=60):
        output.mkdir(exist_ok=True)
        docker_name = RUN.name+'-'+name
        cmd = ['docker','run','--rm','--name',docker_name,'--cpus','2','--memory','4g','--user','1000:1000',
            '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/usr/bin/timeout',
            '-v',str(ROOT)+':/work:ro','-v',str(RUN)+':/output:rw',IMAGE,
            '--signal=TERM','--kill-after=3s',str(timeout)+'s','/bin/bash','-lc',shlex.join(args)]
        record = {'name': name, 'command': cmd, 'started_at': now(), 'inner_timeout_seconds': timeout}
        manifest['steps'].append(record); save(RUN/'manifest.json', manifest)
        with (output/'tool.log').open('x') as log:
            try:
                proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout+25)
                record['returncode'] = proc.returncode
            except subprocess.TimeoutExpired:
                record['returncode'] = None; record['outer_timeout'] = True
                for action in ('stop','kill'):
                    try: subprocess.run(['docker',action,docker_name],stdout=log,stderr=subprocess.STDOUT,timeout=10)
                    except subprocess.TimeoutExpired: pass
        record['finished_at'] = now()
        record['output_sha256'] = {str(path.relative_to(RUN)):sha(path) for path in output.rglob('*') if path.is_file()}
        save(RUN/'manifest.json', manifest)
        print(json.dumps({'step':name,'returncode':record['returncode']}), flush=True)
        return record

    # Source geometry only. Script expects /output/leaf_source_identity.json.
    execute('source-geometry', ['python3','/output/probe_lvs_leaf_source_identity.py'], RUN/'source-probe', 45)
    for arm in ('control','upstream_purge_fix'):
        for cell in CELLS:
            dest = RUN/arm/cell
            dest.mkdir(parents=True)
            args = ['python3','/output/decks/'+arm+'/'+str(DECK_REL/'run_lvs.py'),
                '--layout=/output/inputs/'+cell+'/'+cell+'.gds', '--netlist=/output/inputs/'+cell+'/'+cell+'.cdl',
                '--run_dir=/output/'+arm+'/'+cell,'--topcell='+cell,'--run_mode=deep']
            execute(arm+'-'+cell, args, dest)
    execute('cross-reference', ['python3','/output/analyze_lvs_purge_ab.py'], RUN/'analysis', 45)
    manifest['source_hashes_unchanged'] = all(sha(ROOT/path)==expected for path,expected in manifest['source_sha256'].items())
    manifest['finished_at'] = now()
    manifest['run_artifact_sha256'] = {str(path.relative_to(RUN)):sha(path) for path in RUN.rglob('*') if path.is_file() and path.name != 'manifest.json'}
    manifest['status'] = 'completed_requires_strict_result_review'
    save(RUN/'manifest.json', manifest)
    if (RUN/'analysis/summary.json').exists():
        print((RUN/'analysis/summary.json').read_text(), flush=True)

if __name__ == '__main__':
    main()
