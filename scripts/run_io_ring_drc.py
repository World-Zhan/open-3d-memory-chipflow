#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded full-public-deck DRC for a geometry-verified complete IO-only ring."""
import argparse,json,os,re,shlex,subprocess
from pathlib import Path
from run_io_ring_floorplan import IMAGE,sha,now,write
from audit_bondpad_integration import audit


def run(root,rid,physical_id):
    if not re.fullmatch(r'croc-io-ring-drc-[a-zA-Z0-9_-]+',rid):raise ValueError('Independent DRC run ID required')
    if not re.fullmatch(r'croc-io-ring-physical-[a-zA-Z0-9_-]+',physical_id):raise ValueError('Invalid physical run ID')
    physical=root/'runs'/physical_id
    pm=json.loads((physical/'manifest.json').read_text())
    geometry=json.loads((physical/'geometry_audit.json').read_text())
    if pm['status']!='completed' or pm['returncode']!=0 or geometry['geometry_contract_passed'] is not True:
        raise ValueError('Physical/geometry prerequisite not met')
    for rel,value in geometry['source_sha256'].items():
        if sha(root/rel)!=value:raise ValueError('Geometry evidence changed: '+rel)
    source=physical/'io_ring_sealed.gds'
    if sha(source)!=pm['outputs_sha256'][source.name]:raise ValueError('Physical GDS changed')
    out=root/'runs'/rid;out.mkdir(exist_ok=False);inputs=out/'inputs';inputs.mkdir()
    gds=inputs/source.name;gds.write_bytes(source.read_bytes())
    name=source.stem;dest=out/name;dest.mkdir()
    facts={'classification':'complete_io_only_ring_not_full_chip','arms':[{'name':name,'topcell':name,'gds_sha256':sha(gds)}],
       'outputs_sha256':{gds.name:sha(gds)},'whole_chip_modified':False,'physical_source_run':physical_id}
    write(inputs/'fixture_summary.json',facts)
    deck=root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc'
    files=[physical/'manifest.json',physical/'geometry_audit.json',source]+[root/'scripts'/p for p in
       ('run_io_ring_drc.py','run_io_ring_floorplan.py','audit_bondpad_drc.py','audit_bondpad_integration.py')]
    files += [p for p in deck.rglob('*') if p.is_file() and p.suffix in ('.drc','.py','.json')]
    files += [root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json']
    tasks={'antenna','density','sg13g2_maximal'}
    for group in ('feol','beol','forbidden','geometry','pin'):
        for p in (deck/'rule_decks'/group).glob('*.drc'):
            words=p.stem.split('_');tasks.add('_'.join(words[2:]) if len(words)>=3 else p.stem)
    args=['timeout','--signal=TERM','--kill-after=15s','600s','python3','/work/'+str((deck/'run_drc.py').relative_to(root)),
       '--path','/work/'+str(gds.relative_to(root)),'--topcell',name,'--run_dir','/output','--run_mode','deep','--mp','4','--density_thr','4','--antenna']
    cmd=['docker','run','--rm','--name',rid,'--cpus','4','--memory','8g','--user',f'{os.getuid()}:{os.getgid()}',
       '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/bin/bash','-v',f'{root}:/work:ro','-v',f'{dest}:/output:rw',IMAGE,'-lc',shlex.join(args)]
    arm={'name':name,'command':cmd,'started_at':now(),'fixture_gds_sha256':sha(gds)}
    m={'run_id':rid,'classification':'complete_io_only_ring_not_full_chip','source_sha256':{str(p.relative_to(root)):sha(p) for p in files},
       'fixture_summary_sha256':sha(inputs/'fixture_summary.json'),'public_rule_signoff':False,'whole_chip_modified':False,
       'expected_rule_tasks':sorted(tasks),'all_public_rules_requested':True,'arms':[arm],'started_at':now(),'status':'running'}
    write(out/'manifest.json',m)
    try:
        with (dest/'tool.log').open('x') as f:rc=subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT,timeout=640).returncode
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','stop','--time','5',rid],stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=15);rc=124
    arm.update(returncode=rc,finished_at=now())
    arm['rule_task_completion']={}
    for task in sorted(tasks):
        log=dest/(name+'_'+name+'_'+task+'.log')
        arm['rule_task_completion'][task]=log.exists() and bool(re.search(r'completed in\s+[\d.]+\s+seconds',log.read_text(errors='replace'),re.I))
    arm['outputs_sha256']={p.name:sha(p) for p in dest.iterdir() if p.is_file()}
    m.update(status='executed_requires_audit',finished_at=now(),source_hashes_unchanged=all(sha(root/p)==v for p,v in m['source_sha256'].items()))
    write(out/'manifest.json',m)
    if rc not in (0,1):print(json.dumps({'returncode':rc,'status':'tool_failed_or_timed_out'}));return 1
    result=audit(root,out)
    result['classification']='complete_io_only_ring_drc_not_full_chip_signoff'
    result['ppa']={'whole_chip_modified':False,'new_whole_chip_power_timing':False,
       'io_only_sealed_bbox_area_mm2':4.235364,'old_whole_chip_sealed_bbox_area_mm2':4.0,
       'area_change_scope':'Proposed boundary requirement only. IO-only ring lacks core/functional logic/density fill.',
       'complete_chip_drc_lvs_proven':False}
    write(out/'audit.json',result)
    print(json.dumps({a['name']:{k:a[k] for k in ('rule_execution_complete','merged_markers','density_markers','non_density_marker_counts','fixture_drc_passed')} for a in result['arms']}),flush=True)
    return 0 if all(a['rule_execution_complete'] for a in result['arms']) else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);p.add_argument('--physical-run',required=True)
    a=p.parse_args();raise SystemExit(run(Path(__file__).resolve().parents[1],a.run_id,a.physical_run))
