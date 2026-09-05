#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run three isolated bondpad fixtures through unchanged full public DRC."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import re,subprocess,shlex
import xml.etree.ElementTree as ET

IMAGE='sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def now():
    return datetime.now(timezone.utc).isoformat()
def write(path,data):
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
def run(root,run_id,geometry_run):
    if not re.fullmatch(r'croc-bondpad-drc-ab-[a-zA-Z0-9_-]+',run_id):
        raise ValueError('Use an independent croc-bondpad-drc-ab-* run ID')
    geometry=(root/'runs'/geometry_run).resolve()
    if geometry.parent != (root/'runs').resolve():
        raise ValueError('Geometry run must be within this repository runs/')
    evidence=json.loads((geometry/'manifest.json').read_text())
    if evidence.get('status')!='completed' or evidence.get('returncode')!=0:
        raise ValueError('Require a completed geometry generation run')
    facts=json.loads((geometry/'geometry_summary.json').read_text())
    arms=[('control',root/'upstream/croc/technology/gds/bondpad_70x70.gds','bondpad_70x70')]
    for name in ('official_default_square70','official_m2_square70'):
        p=geometry/(name+'.gds')
        if sha(p)!=facts['official_variants'][name]['generated_gds_sha256']:
            raise ValueError('Generated fixture hash mismatch')
        arms.append((name,p,name))
    source_rel='upstream/croc/technology/gds/bondpad_70x70.gds'
    if sha(arms[0][1])!=facts['source_sha256'][source_rel]:
        raise ValueError('Original Croc macro changed')
    deck=root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc'
    source_files=[Path(__file__).resolve()]+[p for _,p,_ in arms]+[geometry/'manifest.json',geometry/'geometry_summary.json']
    source_files += [p for p in deck.rglob('*') if p.is_file() and p.suffix in ('.drc','.py','.json')]
    source_files += [root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json']
    hashes={str(p.relative_to(root)):sha(p) for p in source_files}
    tables={'antenna','density','sg13g2_maximal'}
    for group in ('feol','beol','forbidden','geometry','pin'):
        for p in (deck/'rule_decks'/group).glob('*.drc'):
            words=p.stem.split('_')
            tables.add('_'.join(words[2:]) if len(words)>=3 else p.stem)
    output=root/'runs'/run_id
    output.mkdir(exist_ok=False)
    m={'run_id':run_id,'geometry_source_run':geometry_run,'classification':'isolated_fixture_drc_not_chip_signoff',
       'started_at':now(),'source_sha256':hashes,'expected_rule_tasks':sorted(tables),
       'all_public_rules_requested':True,'full_chip_drc_lvs_performed':False,
       'public_rule_signoff':False,'arms':[]}
    write(output/'manifest.json',m)
    for name,path,top in arms:
        destination=output/name
        destination.mkdir()
        cmd=['docker','run','--rm','--name',run_id+'-'+name,'--cpus','6','--memory','8g',
             '--user',f'{os.getuid()}:{os.getgid()}','--entrypoint','python3',
             '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1',
             '-v',f'{root}:/work:ro','-v',f'{destination}:/output:rw',IMAGE,
             '/work/'+str((deck/'run_drc.py').relative_to(root)),
             '--path','/work/'+str(path.relative_to(root)),
             '--topcell',top,'--run_dir','/output','--run_mode','deep','--mp','6','--density_thr','6','--antenna']
        # The pinned image configures EDA executable paths in its login shell.
        # Direct Python entrypoints can import klayout.db but cannot find klayout.
        image_index=cmd.index(IMAGE)
        invocation=['python3']+cmd[image_index+1:]
        cmd[cmd.index('--entrypoint')+1]='/bin/bash'
        cmd=cmd[:image_index+1]+['-lc',shlex.join(invocation)]
        arm={'name':name,'input':str(path.relative_to(root)),'topcell':top,'command':cmd,'started_at':now()}
        m['arms'].append(arm)
        write(output/'manifest.json',m)
        with (destination/'tool.log').open('x') as log:
            result=subprocess.run(cmd,cwd=root,stdout=log,stderr=subprocess.STDOUT)
        arm['returncode']=result.returncode
        arm['finished_at']=now()
        merged=list(destination.glob('*_full.lyrdb'))
        arm['merged_report_count']=len(merged)
        complete={}
        for table in sorted(tables):
            log=destination/f'{path.stem}_{top}_{table}.log'
            complete[table]=log.is_file() and bool(re.search(r'completed in\s+[\d.]+\s+seconds',log.read_text(errors='replace'),re.I))
        arm['rule_task_completion']=complete
        if len(merged)==1:
            tree=ET.parse(merged[0])
            arm['merged_marker_counts']=dict(sorted(Counter((i.findtext('category') or '').strip("'") for i in tree.findall('.//items/item')).items()))
            arm['merged_marker_total']=sum(arm['merged_marker_counts'].values())
        else:
            arm['merged_marker_total']=None
        arm['execution_complete']=all(complete.values()) and len(merged)==1 and result.returncode in (0,1)
        arm['fixture_drc_passed']=arm['execution_complete'] and arm['merged_marker_total']==0 and result.returncode==0
        arm['outputs_sha256']={str(p.relative_to(destination)):sha(p) for p in destination.iterdir() if p.is_file()}
        write(output/'manifest.json',m)
        print(json.dumps({k:arm[k] for k in ('name','returncode','execution_complete','merged_marker_total','fixture_drc_passed')}),flush=True)
    m['source_hashes_unchanged']=all(sha(root/p)==v for p,v in hashes.items())
    m['status']='completed' if all(a['execution_complete'] for a in m['arms']) and m['source_hashes_unchanged'] else 'incomplete'
    m['finished_at']=now()
    m['ppa']={'chip_layout_modified':False,'chip_ppa_rerun':False,
              'baseline_report':'reports/ppa/croc-ppa-rcx-20260905-001.json',
              'interpretation':'Isolated macro fixtures; no new whole-chip PPA or closure result.'}
    write(output/'manifest.json',m)
    print(json.dumps({'run_id':run_id,'status':m['status']}),flush=True)
    return 0 if m['status']=='completed' else 1
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--geometry-run',required=True)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    raise SystemExit(run(args.root.resolve(),args.run_id,args.geometry_run))
