#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read actual IO-ring streams and check placements, all leads and seal extent."""
import argparse,csv,json,re
from collections import Counter
from pathlib import Path
import klayout.db as k
from run_io_ring_floorplan import sha
from build_bondpad_io_fixture import LAYERS,region


def check(root,source):
    manifest=json.loads((source/'manifest.json').read_text())
    if manifest['status']!='completed' or manifest['returncode']!=0:raise ValueError('Physical generation not complete')
    for rel,value in manifest['source_sha256'].items():
        if sha(root/rel)!=value:raise ValueError('Source changed: '+rel)
    for rel,value in manifest['outputs_sha256'].items():
        if sha(source/rel)!=value:raise ValueError('Output changed: '+rel)
    floor=root/'runs'/manifest['floorplan_source_run']
    with (floor/'instances.tsv').open() as f:placements=list(csv.DictReader(f,delimiter='\t'))
    with (source/'lead_boxes.tsv').open() as f:leads=list(csv.DictReader(f,delimiter='\t'))
    layout=k.Layout();layout.read(str(source/'io_ring.gds'));top=layout.cell('io_ring')
    assert layout.dbu==0.001 and top is not None
    orientations={'R0':k.Trans.R0,'R90':k.Trans.R90,'R180':k.Trans.R180,'R270':k.Trans.R270,
                  'MX':k.Trans.M0,'MY':k.Trans.M90,'MXR90':k.Trans.M45,'MYR90':k.Trans.M135}
    sizes={}
    for path in (root/'upstream/croc/technology/lef/sg13g2_io.lef',root/'runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.lef'):
        for name,body in re.findall(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',path.read_text(),re.M|re.S):
            dims=re.search(r'SIZE\s+([\d.]+)\s+BY\s+([\d.]+)',body)
            sizes[name]=tuple(round(float(v)*1000) for v in dims.groups())
    transform={};expected=[]
    for row in placements:
        x1,y1,x2,y2=[int(row[v]) for v in ('xmin','ymin','xmax','ymax')]
        mirror=k.Trans(orientations[row['orientation']])
        # Rotate the LEF macro extent, then translate its bbox to OpenDB placement.
        size=sizes[row['master']]
        box=mirror*k.Box(0,0,*size)
        trans=k.Trans(x1-box.left,y1-box.bottom)*mirror
        assert trans*k.Box(0,0,*size)==k.Box(x1,y1,x2,y2)
        transform[row['name']]=(row['master'],trans,row['orientation'])
        expected.append((row['master'],str(trans)))
    actual=[(i.cell.name,str(i.trans)) for i in top.each_inst()]
    placement_equal=Counter(expected)==Counter(actual)
    if not placement_equal:raise ValueError('OpenDB-to-GDS instance transform mismatch')
    direct={name:k.Region(top.shapes(layout.find_layer(*pair))).merged() for name,pair in LAYERS.items()}
    expected_leads={name:k.Region() for name in LAYERS}
    results=[]
    for lead in leads:
        layer=lead['layer'];pair=LAYERS[layer]
        coords=[int(lead[v]) for v in ('xmin','ymin','xmax','ymax')]
        box=k.Box(*coords);wire=k.Region(box);expected_leads[layer].insert(box)
        master,io_trans,orient=transform[lead['io']]
        io=region(layout,layout.cell(master),pair).transformed(io_trans)
        bmaster,btrans,_=transform[lead['bond']]
        pad=region(layout,layout.cell(bmaster),pair).transformed(btrans)
        x1,y1,x2,y2=coords
        pinbox={'R0':(x1,y2,x2,y2+3000),'MX':(x1,y1-3000,x2,y1),
            'MXR90':(x2,y1,x2+3000,y2),'R90':(x1-3000,y1,x1,y2)}[orient]
        pin=k.Region(k.Box(*pinbox))
        checks={'lead_present_in_gds':(wire-direct[layer]).is_empty(),'actual_io_covers_pin':(pin-io).is_empty(),
            'pad_lead_io_pin_connected':(pad|wire|pin).merged().count()==1,
            'lead_overlap_other_io_metal_area_um2':(wire&io).area()*layout.dbu**2}
        results.append({'io':lead['io'],'net':lead['net'],'layer':layer,**checks})
    metal_xor={layer:(direct[layer]^expected_leads[layer]).area()*layout.dbu**2 for layer in LAYERS}
    sealed=k.Layout();sealed.read(str(source/'io_ring_sealed.gds'));seal_top=sealed.cell('io_ring_sealed')
    actual_bbox=seal_top.bbox();expected_bbox=k.Box(0,0,2058000,2058000)
    child_transforms={i.cell.name:str(i.trans) for i in seal_top.each_inst()}
    seal_ok=actual_bbox==expected_bbox and child_transforms=={'io_ring':'r0 42000,42000','sealring_top':'r0 0,0'}
    opening=region(sealed,seal_top,(9,0))&region(sealed,seal_top,(41,0))
    checks_ok=all(x['lead_present_in_gds'] and x['actual_io_covers_pin'] and x['pad_lead_io_pin_connected'] and x['lead_overlap_other_io_metal_area_um2']==0 for x in results)
    return {'classification':'io_ring_stream_geometry_not_signoff','source_sha256':{str(p.relative_to(root)):sha(p) for p in
       (source/'manifest.json',source/'io_ring.gds',source/'io_ring_sealed.gds',source/'lead_boxes.tsv',floor/'instances.tsv',root/'scripts/check_io_ring_geometry_lef.py',root/'upstream/croc/technology/lef/sg13g2_io.lef',root/'runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.lef')},
       'input_output_hashes_verified':True,'placements_equal':placement_equal,'instance_count':len(placements),
       'instance_master_counts':dict(sorted(Counter(p['master'] for p in placements).items())),
       'lead_count':len(leads),'bondpad_count':len({x['bond'] for x in leads}),'opening_count':opening.count(),
       'direct_metal_xor_area_um2':metal_xor,'lead_checks':results,'seal_bbox_um':str(seal_top.dbbox()),
       'seal_transforms':child_transforms,'seal_geometry_scope_passed':seal_ok,
       'geometry_contract_passed':bool(placement_equal and checks_ok and seal_ok and len(leads)==384 and opening.count()==64 and all(v==0 for v in metal_xor.values())),
       'sealed_bbox_area_mm2':actual_bbox.area()*sealed.dbu**2/1e6,
       'full_chip_modified':False,'electrical_network_extraction_performed':False,'public_rule_signoff':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('/work'));p.add_argument('--run',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=check(a.root,a.root/'runs'/a.run)
    with a.output.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({v:result[v] for v in ('geometry_contract_passed','instance_count','lead_count','opening_count','seal_bbox_um')}))
    raise SystemExit(0 if result['geometry_contract_passed'] else 1)
