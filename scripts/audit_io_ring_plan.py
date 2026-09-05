#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit placed pitch and explicit IO/bondpad nets; physical PG is a separate gate."""
import argparse,csv,json,re
from collections import Counter
from pathlib import Path
from run_io_ring_floorplan import sha


def placed_pitch(rows):
    edges={k:[] for k in ('west','east','south','north')}
    for row in rows:
        if not row['master'].startswith('sg13g2_IOPad'):continue
        x1,y1,x2,y2=[int(row[k]) for k in ('xmin','ymin','xmax','ymax')]
        if any(x%1000 for x in (x1,y1,x2,y2)):raise ValueError('IO is off the 1um site grid')
        if x1==92000 and x2==272000:edge,pos='west',y1
        elif x1==1702000 and x2==1882000:edge,pos='east',y1
        elif y1==92000 and y2==272000:edge,pos='south',x1
        elif y1==1702000 and y2==1882000:edge,pos='north',x1
        else:raise ValueError('Unexpected IO row offset or depth')
        edges[edge].append(pos)
    expected=[272000+i*90000 for i in range(16)]
    if any(sorted(values)!=expected for values in edges.values()):raise ValueError('Incomplete ring or pitch differs from 90um')
    return {edge:{'count':len(values),'pitch_um':90,'first_dbu':min(values),'last_dbu':max(values)} for edge,values in edges.items()}


def net_connections(def_text,instances):
    connections={}
    for section in ('NETS','SPECIALNETS'):
        match=re.search(r'^'+section+r'\s+\d+\s*;(.*?)^END '+section,def_text,re.M|re.S)
        if not match:continue
        for record in match[1].split(';'):
            name=re.match(r'\s*-\s+(\S+)',record)
            if not name:continue
            for inst,pin in re.findall(r'\(\s*(\S+)\s+(\S+)\s*\)',record):
                if inst not in instances:continue
                key=(inst,pin)
                if key in connections and connections[key]!=name[1]:raise ValueError('Conflicting pin nets')
                connections[key]=name[1]
    return connections


def validate_connections(rows,connections,source_signals):
    masters={r['name']:r['master'] for r in rows}
    pg={'vdd':'VDD','vss':'VSS','iovdd':'VDDIO','iovss':'VSSIO'}
    signal_pins=0;pg_pins=0;bond_pins=0
    for net,terms in source_signals.items():
        for inst,pin in terms:
            if connections.get((inst,pin))!=net:raise ValueError('Original IO signal connection changed')
            signal_pins+=1
    for inst,master in masters.items():
        if master=='bondpad70_m2_ring':continue
        for pin,net in pg.items():
            if connections.get((inst,pin))!=net:raise ValueError('Candidate PG pin is missing or misconnected')
            pg_pins+=1
        if not master.startswith('sg13g2_IOPad'):continue
        pin={'sg13g2_IOPadVdd':'vdd','sg13g2_IOPadVss':'vss','sg13g2_IOPadIOVdd':'iovdd','sg13g2_IOPadIOVss':'iovss'}.get(master,'pad')
        net=connections.get((inst,pin))
        if net is None or connections.get(('IO_BOND_'+inst,'pad'))!=net:raise ValueError('Bondpad not explicitly connected to its IO terminal')
        bond_pins+=1
    return {'original_signal_terminals_preserved':signal_pins,'explicit_candidate_pg_terminals':pg_pins,'explicit_bondpad_connections':bond_pins}


def audit(root,physical):
    m=json.loads((physical/'manifest.json').read_text());floor=root/'runs'/m['floorplan_source_run']
    fm=json.loads((floor/'manifest.json').read_text())
    for source,manifest in ((physical,m),(floor,fm)):
        if manifest['returncode']!=0 or manifest['status']!='completed':raise ValueError('Unfinished source run')
        for rel,value in manifest['source_sha256'].items():
            if sha(root/rel)!=value:raise ValueError('Source hash changed')
        for rel,value in manifest['outputs_sha256'].items():
            if sha(source/rel)!=value:raise ValueError('Output hash changed')
    with (floor/'instances.tsv').open() as f:rows=list(csv.DictReader(f,delimiter='\t'))
    edges=placed_pitch(rows)
    parsed=net_connections((physical/'io_ring.def').read_text(),{r['name'] for r in rows})
    connectivity=validate_connections(rows,parsed,fm['original_signal_net_connections_retained'])
    areas=Counter()
    for row in rows:
        area=(int(row['xmax'])-int(row['xmin']))*(int(row['ymax'])-int(row['ymin']))/1e6
        areas['cover' if row['master']=='bondpad70_m2_ring' else 'pad']=areas.get('cover' if row['master']=='bondpad70_m2_ring' else 'pad',0)+area
    baseline_path=root/'reports/ppa/croc-ppa-rcx-20260905-001.json'
    baseline=json.loads(baseline_path.read_text())['area']['hierarchy_um2']['<top>']
    before=baseline['pad']+baseline['cover'];after=sum(areas.values())
    return {'classification':'io_only_ring_placement_and_explicit_net_audit_not_signoff','source_sha256':{str(p.relative_to(root)):sha(p) for p in
      (physical/'manifest.json',physical/'io_ring.def',floor/'manifest.json',floor/'instances.tsv',baseline_path,root/'scripts/audit_io_ring_plan.py')},
      'input_output_hashes_verified':True,'edges':edges,'connectivity':connectivity,'placement_and_explicit_net_contract_passed':True,
      'physical_pg_connectivity_proven_by_this_audit':False,'core_logic_included':False,'public_rule_signoff':False,
      'ppa':{'candidate_io_instance_area_um2':dict(areas),'candidate_io_instance_area_total_um2':after,
        'baseline_io_instance_area_total_um2':before,'io_instance_area_delta_um2':after-before,
        'candidate_electrical_bbox_area_mm2':1.974**2,'candidate_sealed_bbox_area_mm2':2.058**2,
        'baseline_sealed_bbox_area_mm2':4.0,'sealed_bbox_delta_percent':((2.058**2)/4-1)*100,
        'new_whole_chip_power_mw':None,'new_whole_chip_fmax_mhz':None,'new_whole_chip_active_area_mm2':None}}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--physical-run',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[1];result=audit(root,root/'runs'/a.physical_run)
    with a.output.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({'contract_passed':result['placement_and_explicit_net_contract_passed'],'connectivity':result['connectivity'],'ppa':result['ppa']}))
