#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Add real OpenDB IO leads, stream actual Croc GDS and generate fixed-PDK seal."""
import argparse, json, os, re, shlex, subprocess
from pathlib import Path
from run_io_ring_floorplan import IMAGE,sha,now,write


def run(root,rid,source_id):
    if not re.fullmatch(r'croc-io-ring-physical-[a-zA-Z0-9_-]+',rid):raise ValueError('Independent physical run id required')
    if not re.fullmatch(r'croc-io-ring-floorplan-[a-zA-Z0-9_-]+',source_id):raise ValueError('Invalid floorplan run')
    source=root/'runs'/source_id
    fm=json.loads((source/'manifest.json').read_text())
    if fm['returncode']!=0 or fm['status']!='completed':raise ValueError('Floorplan did not complete')
    for rel,value in fm['outputs_sha256'].items():
        if sha(source/rel)!=value:raise ValueError('Floorplan output changed: '+rel)
    ref=root/'runs/croc-bondpad-io-ab-20260905-001/inputs'
    pdk=root/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout'
    out=root/'runs'/rid;out.mkdir(exist_ok=False)
    paths=[source/'manifest.json',source/'io_ring.odb',root/'scripts/add_io_ring_connected_leads.tcl',
       root/'scripts/run_io_ring_physical_connected.py',root/'scripts/run_io_ring_floorplan.py',
       ref/'bondpad70_m2_ring.lef',ref/'bondpad70_m2_ring.gds',root/'upstream/croc/technology/gds/sg13g2_io.gds',
       root/'upstream/croc/technology/lef/sg13g2_io.lef',root/'upstream/croc/technology/lef/sg13g2_tech.lef',
       root/'upstream/croc/klayout/scripts/def2stream.py',root/'upstream/croc/klayout/scripts/generate_seal_ring.py',
       root/'upstream/croc/klayout/scripts/merge_sealring.py',pdk/'tech/sg13g2.map']
    paths += sorted((pdk/'python/sg13g2_pycell_lib').rglob('*.py'))
    paths += sorted((pdk/'python/sg13g2_pycell_lib').glob('*.json'))
    paths += sorted((root/'upstream/croc/ihp13/sg13g2/ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python').rglob('*.py'))
    m={'run_id':rid,'classification':'io_only_ring_physical_not_full_chip','started_at':now(),'floorplan_source_run':source_id,
      'source_sha256':{str(p.relative_to(root)):sha(p) for p in paths},'public_rule_signoff':False,'whole_chip_modified':False,
      'core_instances_and_core_routes_included':False,'phases':[]}
    write(out/'manifest.json',m)
    def phase(name,args,seconds=120):
        cmd=['docker','run','--rm','--name',rid+'-'+name,'--cpus','2','--memory','4g','--user',f'{os.getuid()}:{os.getgid()}',
         '-e','HOME=/tmp','-e','CROC_PDK=sg13g2','-e','CROC_SKIP_TECH_SETUP=1','-e','PYTHONDONTWRITEBYTECODE=1',
         '--entrypoint','/bin/bash','-v',f'{root}:/work:ro','-v',f'{root}/upstream/croc:/fosic/designs/croc:ro',
         '-v',f'{source}:/input:ro','-v',f'{out}:/output:rw','-w','/work/upstream/croc/openroad',IMAGE,'-lc',
         'source ../env.sh && export KLAYOUT_PATH=/work/upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout && '+
         shlex.join(['timeout','--signal=TERM','--kill-after=10s',str(seconds)+'s',*args])]
        record={'name':name,'command':cmd,'started_at':now()};m['phases'].append(record);write(out/'manifest.json',m)
        try:
            with (out/(name+'.log')).open('x') as f: rc=subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT,timeout=seconds+25).returncode
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','stop','--time','5',rid+'-'+name],stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=15);rc=124
        record.update(returncode=rc,finished_at=now(),log_sha256=sha(out/(name+'.log')))
        write(out/'manifest.json',m)
        if rc:print((out/(name+'.log')).read_text()[-5000:]);raise RuntimeError(name+' failed with '+str(rc))
        print(json.dumps({'phase':name,'returncode':rc}),flush=True)
    w=lambda p:'/work/'+str(p.relative_to(root))
    try:
        phase('leads',['openroad','-exit','/work/scripts/add_io_ring_connected_leads.tcl'])
        lef=' '.join(w(p) for p in (root/'upstream/croc/technology/lef/sg13g2_tech.lef',root/'upstream/croc/technology/lef/sg13g2_io.lef',ref/'bondpad70_m2_ring.lef'))
        gds=' '.join(w(p) for p in (root/'upstream/croc/technology/gds/sg13g2_io.gds',ref/'bondpad70_m2_ring.gds'))
        phase('stream',['klayout','-b','-rd','gds_allow_empty=False','-rd','design_name=io_ring','-rd','in_def=/output/io_ring.def',
          '-rd','layer_map='+w(pdk/'tech/sg13g2.map'),'-rd','lef_files='+lef,'-rd','gds_files='+gds,
          '-rd','out_file=/output/io_ring.gds','-rm','/work/upstream/croc/klayout/scripts/def2stream.py'])
        phase('seal',['klayout','-b','-rd','width=2058','-rd','height=2058','-rd','output=/output/seal_ring.gds',
          '-rm','/work/upstream/croc/klayout/scripts/generate_seal_ring.py'])
        phase('merge',['klayout','-b','-rd','chip_gds=/output/io_ring.gds','-rd','seal_gds=/output/seal_ring.gds',
          '-rd','top_name=io_ring_sealed','-rd','dx_um=42','-rd','dy_um=42','-rd','out_gds=/output/io_ring_sealed.gds',
          '-rm','/work/upstream/croc/klayout/scripts/merge_sealring.py'])
        m['status']='completed';rc=0
    except RuntimeError as error:m['status']='failed';m['failure']=str(error);rc=1
    m.update(returncode=rc,finished_at=now(),source_hashes_unchanged=all(sha(root/p)==v for p,v in m['source_sha256'].items()),
       outputs_sha256={p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'})
    write(out/'manifest.json',m);return rc


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);p.add_argument('--floorplan-run',required=True)
    a=p.parse_args();raise SystemExit(run(Path(__file__).resolve().parents[1],a.run_id,a.floorplan_run))
