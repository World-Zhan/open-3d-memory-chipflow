#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One bounded strict DCN LVS with observation-only stage instrumentation."""
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path('/home/james_zhan/projects/open-3d-memory-chipflow')
STAGE = Path('/mnt/c/Users/James Zhan/.codex/visualizations/2026/09/05/01a06f53-62f0-7bb1-93a3-51fd2e527fa7')
SOURCE = ROOT / 'runs/croc-lvs-leaf-purge-ab-20260905-001'
RUN = ROOT / 'runs/croc-lvs-dcn-stage-snapshots-20260909-001'
REL = Path('ihp-sg13g2/libs.tech/klayout/tech/lvs')
IMAGE = 'sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
CELL = 'sg13g2_DCNDiode'

def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')
def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)

def main():
    RUN.mkdir()
    (RUN/'snapshots').mkdir()
    (RUN/'result').mkdir()
    shutil.copytree(SOURCE/'decks/control', RUN/'deck')
    shutil.copytree(SOURCE/'inputs'/CELL, RUN/'inputs')
    for name in ('run_lvs_stage_snapshots.py', 'lvs_stage_observer.rb'):
        shutil.copyfile(STAGE/name, RUN/name)
        shutil.copyfile(STAGE/name, ROOT/'reports/lvs'/name)
    historical = json.loads((SOURCE/'manifest.json').read_text())
    for name, expected in historical['copied_deck_sha256'].items():
        if name.startswith('decks/control/'):
            assert sha(SOURCE/name) == expected
    for ext in ('gds', 'cdl'):
        rel = f'inputs/{CELL}/{CELL}.{ext}'
        assert sha(SOURCE/rel) == historical['input_sha256'][rel]
    sg = RUN/'deck'/REL/'sg13g2.lvs'
    rf = RUN/'deck'/REL/'rule_decks/rfmos_model_mapping.lvs'
    original_sg = sg.read_text(); original_rf = rf.read_text()
    sg_text = replace_once(original_sg, '# Instantiate a reader using the new delegate',
        '# %include rule_decks/stage_observer.lvs\n\n# Instantiate a reader using the new delegate')
    sg_text = replace_once(sg_text, '# Instantiate a writer using the new delegate',
        "stage_snapshot.call(schematic, 'schematic_after_reader') unless NET_ONLY\n\n# Instantiate a writer using the new delegate")
    for operation, flag in [('simplify','SIMPLIFY'),('make_top_level_pins','TOP_LVL_PINS'),
                            ('combine_devices','COMBINE_DEVICES'),('purge','PURGE'),('purge_nets','PURGE_NETS')]:
        old = f'  target_netlist.{operation} if {flag}'
        sg_text = replace_once(sg_text, old,
            f"  stage_snapshot.call(target_netlist, label + '_before_{operation}')\n"+old+
            f"\n  stage_snapshot.call(target_netlist, label + '_after_{operation}')")
    sg_text = replace_once(sg_text, '  align\n',
        "  stage_snapshot.call(netlist, 'layout_before_align')\n  stage_snapshot.call(schematic, 'schematic_before_align')\n  align\n  stage_snapshot.call(netlist, 'layout_after_align')\n  stage_snapshot.call(schematic, 'schematic_after_align')\n")
    sg_text = replace_once(sg_text, '  #================================================\n  #------------- COMPARISON RESULTS',
        "  stage_snapshot.call(netlist, 'layout_after_compare')\n  stage_snapshot.call(schematic, 'schematic_after_compare')\n\n  #================================================\n  #------------- COMPARISON RESULTS")
    rf_text = replace_once(original_rf, 'apply_rfmos_model_mapping = lambda do |target_netlist, label|\n',
        "apply_rfmos_model_mapping = lambda do |target_netlist, label|\n  stage_snapshot.call(target_netlist, label + '_raw_before_rf_mapping')\n")
    rf_text = replace_once(rf_text, '  target_netlist.purge_devices\n  target_netlist.purge\n',
        "  stage_snapshot.call(target_netlist, label + '_after_rf_mapping')\n  target_netlist.purge_devices\n  stage_snapshot.call(target_netlist, label + '_after_rf_purge_devices')\n  target_netlist.purge\n  stage_snapshot.call(target_netlist, label + '_after_rf_purge')\n")
    sg.write_text(sg_text); rf.write_text(rf_text)
    shutil.copyfile(RUN/'lvs_stage_observer.rb', RUN/'deck'/REL/'rule_decks/stage_observer.lvs')
    patch = ''
    for rel, before, after in [(REL/'sg13g2.lvs', original_sg, sg_text),
                              (REL/'rule_decks/rfmos_model_mapping.lvs', original_rf, rf_text)]:
        patch += ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                         fromfile='a/'+str(rel), tofile='b/'+str(rel)))
    (RUN/'observation_only.patch').write_text(patch)
    sources = [SOURCE/'manifest.json', SOURCE/'control'/CELL/'cross_reference.json',
               *[p for p in (SOURCE/'decks/control').rglob('*') if p.is_file()],
               *[p for p in (SOURCE/'inputs'/CELL).iterdir() if p.is_file()]]
    manifest = {'run_id': RUN.name, 'started_at': now(),
        'classification': 'strict_single_DCN_LVS_observation_only_not_signoff',
        'image':IMAGE,'repo_head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sources},
        'strictness':historical['strictness'], 'source_pdk_modified':False,
        'full_chip_lvs_performed':False,'parent_lvs_performed':False,
        'observer_trigger':'inside_rf_mapping_lambda_after_original_lazy_netlist_evaluation',
        'input_and_deck_sha256':{str(p.relative_to(RUN)):sha(p) for folder in ('inputs','deck') for p in (RUN/folder).rglob('*') if p.is_file()},
        'script_sha256':{n:sha(RUN/n) for n in ('run_lvs_stage_snapshots.py','lvs_stage_observer.rb','observation_only.patch')}}
    args = ['python3','/output/deck/'+str(REL/'run_lvs.py'),'--layout=/output/inputs/'+CELL+'.gds',
            '--netlist=/output/inputs/'+CELL+'.cdl','--run_dir=/output/result','--topcell='+CELL,'--run_mode=deep']
    name = RUN.name
    cmd = ['docker','run','--name',name,'--cpus','2','--memory','4g','--user','1000:1000',
           '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/usr/bin/timeout',
           '-v',str(ROOT)+':/work:ro','-v',str(RUN)+':/output:rw',IMAGE,'--signal=TERM','--kill-after=3s','60s',
           '/bin/bash','-lc','ulimit -c 0\n'+shlex.join(args)]
    manifest['command'] = cmd; manifest['inner_timeout_seconds']=60; manifest['outer_timeout_seconds']=85
    save(RUN/'manifest.json', manifest)
    with (RUN/'tool.log').open('x') as log:
        try:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=85)
            manifest['runner_returncode'] = proc.returncode
        except subprocess.TimeoutExpired:
            manifest['outer_timeout'] = True; manifest['runner_returncode'] = None
            subprocess.run(['docker','kill',name],stdout=log,stderr=subprocess.STDOUT,timeout=10)
        state = subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=10)
        (RUN/'terminal_observation.json').write_text(state.stdout)
        manifest['docker_inspect_returncode']=state.returncode
        if state.returncode == 0:
            manifest['terminal_state']=json.loads(state.stdout)[0]['State']
            if not manifest['terminal_state']['Running']:
                subprocess.run(['docker','rm',name],stdout=log,stderr=subprocess.STDOUT,timeout=10,check=True)
    manifest['source_hashes_unchanged']=all(sha(ROOT/p)==h for p,h in manifest['source_sha256'].items())
    manifest['finished_at']=now()
    manifest['output_sha256']={str(p.relative_to(RUN)):sha(p) for p in RUN.rglob('*') if p.is_file() and p.name!='manifest.json'}
    save(RUN/'manifest.json',manifest)
    print(json.dumps({'run':str(RUN),'returncode':manifest['runner_returncode'],
                      'snapshots':len(list((RUN/'snapshots').glob('*.inventory.json'))),
                      'terminal_state':manifest.get('terminal_state')},indent=2),flush=True)

if __name__ == '__main__': main()
