#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build an IO-only OpenROAD ring from the real Croc pad instances and net names."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from datetime import datetime, timezone

IMAGE='sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def write(p,x): p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')


def select_pads(source):
    body=re.search(r'^COMPONENTS\s+\d+\s*;(.*?)^END COMPONENTS',source,re.M|re.S)[1]
    cells={}
    for record in body.split(';'):
        match=re.match(r'\s*-\s+(\S+)\s+(sg13g2_IOPad\S+)',record)
        if match: cells[match[1]]=match[2]
    if len(cells)!=64: raise ValueError('Expected all 64 actual Croc pad instances')
    signals={}
    for section in ('NETS','SPECIALNETS'):
        body=re.search(r'^'+section+r'\s+\d+\s*;(.*?)^END '+section,source,re.M|re.S)[1]
        for record in body.split(';'):
            name=re.match(r'\s*-\s+(\S+)',record)
            if not name: continue
            terms=[(i,p) for i,p in re.findall(r'\(\s*(\S+)\s+(\S+)\s*\)',record)
                   if i in cells and p not in ('vdd','vss','iovdd','iovss')]
            if terms: signals[name[1]]=terms
    return cells,signals


TCL='''# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
source scripts/init_tech_sg13g2.tcl
read_lef /reference/bondpad70_m2_ring.lef
read_def /output/io_ring_input.def
set chipW 1974
set chipH 1974
set padD 180
set padW 80
# IO offset is an integer multiple of the 1um IO site width.
set padBond 92
set bondPadCell bondpad70_m2_ring
source /output/padring_candidate.tcl
foreach {net pin kind} {VDD vdd power VSS vss ground VDDIO iovdd power VSSIO iovss ground} {
    add_global_connection -net $net -inst_pattern {.*} -pin_pattern $pin -$kind
}
global_connect
make_tracks
set f [open /output/instances.tsv w]
puts $f "name\\tmaster\\torientation\\txmin\\tymin\\txmax\\tymax"
set t [open /output/terminals.tsv w]
puts $t "instance\\tpin\\tnet"
foreach inst [[ord::get_db_block] getInsts] {
    set box [$inst getBBox]
    puts $f "[$inst getName]\\t[[$inst getMaster] getName]\\t[$inst getOrient]\\t[$box xMin]\\t[$box yMin]\\t[$box xMax]\\t[$box yMax]"
    foreach iterm [$inst getITerms] {
        set net [$iterm getNet]
        set name {UNCONNECTED}
        if {$net != "NULL"} {set name [$net getName]}
        puts $t "[$inst getName]\\t[[$iterm getMTerm] getName]\\t$name"
    }
}
close $f
close $t
write_def /output/io_ring.def
write_db /output/io_ring.odb
puts {IO_RING_FLOORPLAN_COMPLETE: IO-only placement; no core, route, extraction or signoff}
'''


def run(root,rid):
    if not re.fullmatch(r'croc-io-ring-floorplan-[a-zA-Z0-9_-]+',rid): raise ValueError('Independent run id required')
    out=root/'runs'/rid; out.mkdir(exist_ok=False)
    source=root/'runs/croc-sg13g2-baseline-20260827-001/artifacts/pnr/upstream/croc/openroad/out/croc.def'
    padring=root/'upstream/croc/openroad/src/padring.tcl'
    reference=root/'runs/croc-bondpad-io-ab-20260905-001/inputs'
    cells,signals=select_pads(source.read_text())
    pg={'VDD':'vdd','VSS':'vss','VDDIO':'iovdd','VSSIO':'iovss'}
    nets={name:[(inst,pin) for inst in sorted(cells)] for name,pin in pg.items()}
    assert not (nets.keys() & signals.keys()); nets.update(signals)
    lines=['VERSION 5.8 ;','DIVIDERCHAR "/" ;','BUSBITCHARS "[]" ;','DESIGN io_ring ;',
       'UNITS DISTANCE MICRONS 1000 ;','DIEAREA ( 0 0 ) ( 1974000 1974000 ) ;',f'COMPONENTS {len(cells)} ;']
    lines += [f'- {name} {master} + UNPLACED ;' for name,master in sorted(cells.items())]
    lines += ['END COMPONENTS',f'NETS {len(nets)} ;']
    for name,terms in sorted(nets.items()):
        use='POWER' if name in ('VDD','VDDIO') else 'GROUND' if name in ('VSS','VSSIO') else 'SIGNAL'
        lines += ['- '+name+' '+' '.join(f'( {inst} {pin} )' for inst,pin in terms)+f' + USE {use} ;']
    lines += ['END NETS','END DESIGN','']
    (out/'io_ring_input.def').write_text('\n'.join(lines))
    s=padring.read_text(); old='-offset {5.0 -70.0}'; assert s.count(old)==1
    (out/'padring_candidate.tcl').write_text(s.replace(old,'-offset {5.0 -74.2}'))
    (out/'build_io_ring.tcl').write_text(TCL)
    inputs=[source,padring,reference/'bondpad70_m2_ring.lef',root/'scripts/run_io_ring_floorplan.py',
       root/'upstream/croc/openroad/scripts/init_tech_sg13g2.tcl',root/'upstream/croc/env.sh',
       out/'io_ring_input.def',out/'padring_candidate.tcl',out/'build_io_ring.tcl']
    inputs += sorted((root/'upstream/croc/technology/lef').glob('*.lef'))
    inputs += sorted((root/'upstream/croc/technology/lib').glob('*.lib'))
    cmd=['docker','run','--rm','--name',rid,'--cpus','2','--memory','4g','--user',f'{os.getuid()}:{os.getgid()}',
       '-e','HOME=/tmp','-e','CROC_PDK=sg13g2','-e','CROC_SKIP_TECH_SETUP=1','--entrypoint','/bin/bash',
       '-v',f'{root}:/work:ro','-v',f'{root}/upstream/croc:/fosic/designs/croc:ro',
       '-v',f'{reference}:/reference:ro','-v',f'{out}:/output:rw','-w','/work/upstream/croc/openroad',IMAGE,'-lc',
       'source ../env.sh && timeout --signal=TERM --kill-after=10s 90s openroad -exit /output/build_io_ring.tcl']
    m={'run_id':rid,'classification':'io_only_ring_floorplan_not_full_chip','started_at':now(),'command':cmd,
       'source_sha256':{str(p.relative_to(root)):sha(p) for p in inputs},'whole_chip_modified':False,
       'io_instance_count':len(cells),'original_signal_net_connections_retained':signals,
       'explicit_candidate_pg_mapping':pg,'core_instances_and_core_routes_included':False,
       'electrical_die_um':[1974,1974],'planned_sealed_bbox_um':[2058,2058],
       'io_offset_um':92,'bondpad_gap_um':4.2,'io_pitch_um':90,'public_rule_signoff':False}
    write(out/'manifest.json',m)
    try:
        with (out/'tool.log').open('x') as log:
            result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,cwd=root,timeout=115)
        rc=result.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','stop','--time','5',rid],stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=15)
        rc=124
    m.update(returncode=rc,status='completed' if rc==0 else 'failed',finished_at=now(),
       source_hashes_unchanged=all(sha(root/p)==v for p,v in m['source_sha256'].items()),
       outputs_sha256={p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'})
    write(out/'manifest.json',m)
    print(json.dumps({'run_id':rid,'returncode':rc})); print((out/'tool.log').read_text()[-6500:])
    return rc


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--run-id',required=True)
    a=p.parse_args(); raise SystemExit(run(Path(__file__).resolve().parents[1],a.run_id))
