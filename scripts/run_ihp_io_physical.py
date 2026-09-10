#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded physical-view probe and all-rule DRC of official IO macro fixtures."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
from run_io_ring_floorplan import IMAGE,now,sha,write
from run_io_ring_maximal_diagnostic import observe
from probe_ihp_io_physical import OFFICIAL,OLD,CELLS

def execute(root,out,name,args,seconds):
    cmd=['docker','run','--name',name,'--cpus','2','--memory','4g','--ulimit','core=0','--user',f'{os.getuid()}:{os.getgid()}',
        '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/bin/bash',
        '-v',f'{root}:/work:ro','-v',f'{out}:/output:rw',IMAGE,'-lc',
        shlex.join(['timeout','--signal=TERM','--kill-after=5s',str(seconds)+'s',*args])]
    execution={'command':cmd,'started_at':now(),'inner_timeout_seconds':seconds,'outer_timeout_seconds':seconds+25}
    with (out/'tool.log').open('x') as log:
        try:rc=subprocess.run(cmd,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=seconds+25).returncode
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','stop','--time','3',name],capture_output=True,timeout=12);rc=124
    observation=observe(name);write(out/'terminal_observation.json',observation)
    state=observation.get('state',{})
    execution.update(returncode=rc,finished_at=now(),terminal_state=state,
        process_completed=state.get('Status')=='exited' and state.get('Running') is False and state.get('OOMKilled') is False and state.get('ExitCode')==rc and rc in (0,1))
    cleanup=subprocess.run(['docker','rm',name],capture_output=True,text=True,timeout=15)
    execution['container_cleanup_returncode']=cleanup.returncode
    write(out/'execution.json',execution)
    return execution

def run(root,rid):
    if not re.fullmatch(r'ihp-io-physical-[0-9-]+',rid):raise ValueError('Independent run id required')
    fixed='331c00484213b13414777eec1336ef5c29b969bd'
    pdk=root/'upstream/ihp-open-pdk'
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=pdk,text=True).strip()!=fixed:raise ValueError('Unexpected PDK revision')
    if subprocess.check_output(['git','status','--porcelain'],cwd=pdk,text=True).strip():raise ValueError('PDK is dirty')
    out=root/'runs'/rid;out.mkdir(exist_ok=False)
    deck=pdk/'ihp-sg13g2/libs.tech/klayout/tech/drc'
    sources=[root/'scripts'/n for n in ('probe_ihp_io_physical.py','run_ihp_io_physical.py','run_io_ring_floorplan.py','run_io_ring_maximal_diagnostic.py')]
    for base in (OFFICIAL,OLD):
        sources += [root/base/'gds/sg13g2_io.gds',root/base/'lef/sg13g2_io.lef']
    sources += [p for p in deck.rglob('*') if p.is_file() and p.suffix in ('.drc','.py','.json')]
    sources += [pdk/'ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json']
    m={'run_id':rid,'classification':'official_macro_geometry_and_DRC_not_chip_signoff','fixed_pdk_commit':fixed,
       'source_sha256':{str(p.relative_to(root)):sha(p) for p in sources},'started_at':now(),'status':'running',
       'source_pdk_modified':False,'current_chip_modified':False,'strict_lvs':'NOT_RUN_leaf_gate_unresolved',
       'public_rule_signoff':False,'foundry_signoff':False,'arms':{}}
    write(out/'manifest.json',m)
    geom=out/'geometry';geom.mkdir()
    execution=execute(root,geom,rid+'-geometry',['python3','/work/scripts/probe_ihp_io_physical.py','--root','/work','--output','/output'],60)
    m['geometry_execution']=execution;write(out/'manifest.json',m)
    if not execution['process_completed'] or execution['returncode']!=0:raise ValueError('Geometry execution failed; preserve this run')
    facts=json.loads((geom/'geometry.json').read_text())
    tasks={'antenna','density','sg13g2_maximal'}
    for group in ('feol','beol','forbidden','geometry','pin'):
        for p in (deck/'rule_decks'/group).glob('*.drc'):
            words=p.stem.split('_');tasks.add('_'.join(words[2:]) if len(words)>=3 else p.stem)
    m['expected_rule_tasks']=sorted(tasks)
    # Each isolated macro remains context-limited; no assembly or pad-ring migration.
    for name in CELLS[:2]:
        path=geom/(name+'.gds')
        if sha(path)!=facts['cells'][name]['exported_gds_sha256']:raise ValueError('Changed exported macro')
        dest=out/name;dest.mkdir()
        args=['python3','/work/'+str((deck/'run_drc.py').relative_to(root)),
              '--path','/work/'+str(path.relative_to(root)),'--topcell',name,'--run_dir','/output',
              '--run_mode','deep','--mp','1','--density_thr','1','--antenna']
        execution=execute(root,dest,rid+'-'+name.lower(),args,240)
        completion={}
        for task in tasks:
            log=dest/(name+'_'+name+'_'+task+'.log')
            completion[task]=log.is_file() and bool(re.search(r'completed in\s+[\d.]+\s+seconds',log.read_text(errors='replace'),re.I))
        merged=list(dest.glob('*_full.lyrdb'));counts=None
        if len(merged)==1:counts=dict(sorted(Counter((item.findtext('category') or '').strip("'") for item in ET.parse(merged[0]).findall('.//items/item')).items()))
        raw=dest/(name+'_'+name+'_sg13g2_maximal.lyrdb')
        raw_count=len(ET.parse(raw).findall('.//items/item')) if raw.is_file() else None
        complete=execution['process_completed'] and all(completion.values()) and counts is not None
        m['arms'][name]={'execution':execution,'input_gds_sha256':sha(path),'rule_task_completion':completion,
            'all_public_rules_requested':True,'disabled_rules':[],'maximal_raw_markers':raw_count,
            'merged_marker_counts':counts,'merged_marker_total':sum(counts.values()) if counts is not None else None,
            'execution_complete':complete,'strict_fixture_DRC':'PASS' if complete and not counts and execution['returncode']==0 else 'FAIL' if complete else 'INCOMPLETE',
            'scope':'isolated_unassembled_official_IO_macro_density_and_boundary_context_not_whole_chip'}
        write(out/'manifest.json',m)
        print(json.dumps({name:{k:v for k,v in m['arms'][name].items() if k not in ('execution','rule_task_completion')}}),flush=True)
    m.update(finished_at=now(),status='completed' if all(a['execution_complete'] for a in m['arms'].values()) else 'incomplete',
        source_hashes_unchanged=all(sha(root/p)==v for p,v in m['source_sha256'].items()),
        outputs_sha256={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'})
    write(out/'manifest.json',m)
    return 0 if m['status']=='completed' and m['source_hashes_unchanged'] else 1
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1],a.run_id))
