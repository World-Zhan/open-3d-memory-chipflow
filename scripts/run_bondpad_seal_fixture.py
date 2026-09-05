#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create single IO/complete-seal fixtures then execute unchanged complete public DRC."""
import argparse,json,os,re,shlex,subprocess
from pathlib import Path
from run_croc_bondpad_drc_ab import IMAGE,sha,now,write
from audit_bondpad_drc import analyze

def run(root,rid):
    if not re.fullmatch(r'croc-bondpad-seal-ab-[a-zA-Z0-9_-]+',rid):raise ValueError('Independent croc-bondpad-seal-ab-* run ID required')
    out=root/'runs'/rid;out.mkdir(exist_ok=False)
    inputs=out/'inputs';inputs.mkdir()
    deck=root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc'
    files=[root/'scripts'/n for n in ('build_bondpad_seal_fixture.py','build_bondpad_io_fixture.py','run_bondpad_seal_fixture.py','run_croc_bondpad_drc_ab.py','audit_bondpad_drc.py')]
    files += [root/p for p in ('upstream/croc/technology/gds/sg13g2_io.gds','upstream/croc/technology/gds/bondpad_70x70.gds',
         'runs/bondpad-geometry-20260905-003/official_m2_square70.gds','runs/bondpad-geometry-20260905-003/geometry_summary.json',
         'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json')]
    files += [root/p for p in ('runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.gds','runs/croc-bondpad-io-ab-20260905-001/inputs/fixture_summary.json','runs/croc-sg13g2-baseline-20260827-001/artifacts/gds.attempt-4/upstream/croc/klayout/out/croc.filled.gds.gz')]
    files += [p for p in deck.rglob('*') if p.is_file() and p.suffix in ('.drc','.py','.json')]
    hashes={str(p.relative_to(root)):sha(p) for p in files}
    common=['docker','run','--rm','--cpus','6','--memory','8g','--user',f'{os.getuid()}:{os.getgid()}',
            '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','-v',f'{root}:/work:ro']
    build=common+['--name',rid+'-build','--entrypoint','python3','-v',f'{inputs}:/output:rw',IMAGE,
                  '/work/scripts/build_bondpad_seal_fixture.py']
    manifest={'run_id':rid,'classification':'single_io_complete_seal_fixture_not_chip_signoff','started_at':now(),
              'source_sha256':hashes,'build_command':build,'full_chip_modified':False,
              'public_rule_signoff':False,'full_chip_drc_lvs_performed':False,'arms':[]}
    write(out/'manifest.json',manifest)
    with (out/'build.log').open('x') as f:
        proc=subprocess.run(build,stdout=f,stderr=subprocess.STDOUT,cwd=root)
    manifest['build_returncode']=proc.returncode
    manifest['build_log_sha256']=sha(out/'build.log')
    if proc.returncode:
        manifest['status']='fixture_generation_failed';write(out/'manifest.json',manifest)
        print((out/'build.log').read_text()[-4000:],flush=True)
        return proc.returncode
    facts=json.loads((inputs/'fixture_summary.json').read_text())
    manifest['fixture_summary_sha256']=sha(inputs/'fixture_summary.json')
    tables={'antenna','density','sg13g2_maximal'}
    for group in ('feol','beol','forbidden','geometry','pin'):
        for p in (deck/'rule_decks'/group).glob('*.drc'):
            words=p.stem.split('_');tables.add('_'.join(words[2:]) if len(words)>=3 else p.stem)
    manifest['expected_rule_tasks']=sorted(tables)
    for fixture in facts['arms']:
        name=fixture['name'];dest=out/name;dest.mkdir()
        source=inputs/(name+'.gds')
        if sha(source)!=fixture['gds_sha256']:raise ValueError('Fixture input hash changed')
        argv=['python3','/work/'+str((deck/'run_drc.py').relative_to(root)),
             '--path','/work/'+str(source.relative_to(root)),'--topcell',fixture['topcell'],
             '--run_dir','/output','--run_mode','deep','--mp','6','--density_thr','6','--antenna']
        cmd=common+['--name',rid+'-'+name,'--entrypoint','/bin/bash','-v',f'{dest}:/output:rw',IMAGE,'-lc',shlex.join(argv)]
        arm={'name':name,'command':cmd,'started_at':now(),'fixture_gds_sha256':sha(source)}
        manifest['arms'].append(arm);write(out/'manifest.json',manifest)
        with (dest/'tool.log').open('x') as f:
            proc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,cwd=root)
        arm.update(returncode=proc.returncode,finished_at=now())
        complete={}
        for table in sorted(tables):
            log=dest/f'{name}_{fixture["topcell"]}_{table}.log'
            complete[table]=log.exists() and bool(re.search(r'completed in\s+[\d.]+\s+seconds',log.read_text(errors='replace'),re.I))
        arm['rule_task_completion']=complete
        arm['outputs_sha256']={p.name:sha(p) for p in dest.iterdir() if p.is_file()}
        write(out/'manifest.json',manifest)
        print(json.dumps({'arm':name,'returncode':proc.returncode,'tool_completed':True}),flush=True)
    manifest['source_hashes_unchanged']=all(sha(root/p)==v for p,v in hashes.items())
    manifest['status']='executed_requires_audit';manifest['finished_at']=now()
    manifest['ppa']={'chip_modified':False,'new_whole_chip_ppa':False,
                     'reference':'reports/ppa/croc-ppa-rcx-20260905-001.json',
                     'scope':'Local physical connectivity/spacing experiment; gap increases may change future floorplan and IO lead parasitics.'}
    write(out/'manifest.json',manifest)
    audit=analyze(root,out)
    audit['note']='Complete public DRC on single IO and complete original seal fixtures; pinned antenna deck completion checked by 31 categories and terminal Ant.i.'
    with (out/'audit.json').open('x') as f:json.dump(audit,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({a['name']:{k:a[k] for k in ('rule_execution_complete','merged_markers','density_markers','non_density_marker_counts')} for a in audit['arms']}),flush=True)
    return 0 if all(a['rule_execution_complete'] for a in audit['arms']) else 1
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True)
    a=p.parse_args();raise SystemExit(run(Path(__file__).resolve().parents[1],a.run_id))
