#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Correct hierarchy-aware text anchors and verify direct macro pin labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from probe_ihp_io_physical import CELLS,METALS,OFFICIAL,lef_macro

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(row):return (row['name'],*row['layer'],*row['position_dbu'])
def counters(rows):return Counter(canonical(row) for row in rows)

def direct_pin_checks(direct_labels,lef,dbu):
    checks={}
    for pin,definition in lef['pins'].items():
        matches=[]
        for label in direct_labels:
            if label['name']!=pin:continue
            for index,rect in enumerate(definition['rects']):
                # LEF drawing metal and GDS text datatype 25 denote the same
                # physical metal layer; do not accept a child alias or another metal.
                if label['layer']!=[METALS[rect['layer']][0],25]:continue
                x,y=[v*dbu for v in label['position_dbu']];x0,y0,x1,y1=rect['um']
                if x0<=x<=x1 and y0<=y<=y1:
                    matches.append({'label':label,'lef_rectangle_index':index,'lef_layer':rect['layer'],'lef_rectangle_um':rect['um']})
        checks[pin]={'at_least_one_direct_label_in_same_metal_pin_rect':bool(matches),'matches':matches}
    return checks

def probe(root,out):
    import klayout.db as k
    source=root/OFFICIAL/'gds/sg13g2_io.gds';lef_path=root/OFFICIAL/'lef/sg13g2_io.lef'
    historical_dir=root/'runs/ihp-io-physical-20260910-001/geometry'
    historical=json.loads((historical_dir/'geometry.json').read_text())
    layout=k.Layout();layout.read(str(source))
    if layout.dbu!=0.001:raise ValueError('Unexpected source DBU')
    def collect(layout,cell):
        rows=[];direct=[];legacy=[];shifted=[]
        for idx in layout.layer_indexes():
            info=layout.get_info(idx);pair=[info.layer,info.datatype]
            for shape in cell.shapes(idx).each():
                if shape.is_text():
                    text=shape.text
                    direct.append({'name':text.string,'layer':pair,'position_dbu':[text.x,text.y]})
            iterator=cell.begin_shapes_rec(idx)
            while not iterator.at_end():
                shape=iterator.shape()
                if shape.is_text():
                    text=shape.text
                    # Point transformation includes translation; Vector does not.
                    position=iterator.trans()*k.Point(text.x,text.y)
                    transformed_text=text.transformed(iterator.trans())
                    if (position.x,position.y)!=(transformed_text.x,transformed_text.y):
                        raise ValueError('Point and full Text transform disagree')
                    row={'name':text.string,'layer':pair,'position_dbu':[position.x,position.y]}
                    rows.append(row)
                    old=iterator.trans()*text.trans.disp
                    oldrow={'name':text.string,'layer':pair,'position_dbu':[old.x,old.y]};legacy.append(oldrow)
                    if oldrow!=row:shifted.append({'correct':row,'legacy_vector_position_dbu':[old.x,old.y]})
                iterator.next()
        return {'recursive':sorted(rows,key=canonical),'direct':sorted(direct,key=canonical),
                'legacy':sorted(legacy,key=canonical),'translation_affected':shifted}
    report={'schema_version':1,'classification':'corrected_label_anchor_readback_not_connectivity_or_signoff',
            'coordinate_method':'iterator.trans() * k.Point(text.x,text.y), independently checked against transformed Text',
            'tool_version':getattr(k,'__version__',None),'dbu_um':layout.dbu,'source_sha256':{
                str(source.relative_to(root)):sha(source),str(lef_path.relative_to(root)):sha(lef_path),
                str((historical_dir/'geometry.json').relative_to(root)):sha(historical_dir/'geometry.json')},
            'cells':{},'old_geometry_json_modified':False,'source_pdk_modified':False,
            'new_DRC_or_LVS_performed':False,'public_rule_signoff':False}
    for name in CELLS:
        cell=layout.cell(name)
        if cell is None:raise ValueError('Missing source macro')
        export=historical_dir/(name+'.gds')
        if sha(export)!=historical['cells'][name]['exported_gds_sha256']:raise ValueError('Export hash differs')
        readback=k.Layout();readback.read(str(export))
        if readback.dbu!=layout.dbu or [c.name for c in readback.top_cells()]!=[name]:raise ValueError('Export DBU/top differs')
        original=collect(layout,cell);copied=collect(readback,readback.cell(name))
        a,b=counters(original['recursive']),counters(copied['recursive'])
        direct_equal=counters(original['direct'])==counters(copied['direct'])
        lef=lef_macro(lef_path.read_text(),name)
        checks=direct_pin_checks(original['direct'],lef,layout.dbu)
        old_rows=[{'name':r['name'],'layer':r['layer'],'position_dbu':[round(v/layout.dbu) for v in r['position_um']]}
                  for r in historical['cells'][name]['official_gds_pin_labels']]
        reconstructed_legacy=[r for r in original['legacy'] if r['name'] in lef['pins']]
        if counters(old_rows)!=counters(reconstructed_legacy):raise ValueError('Historical bug reproduction does not match archived labels')
        complete=a==b and direct_equal and all(v['at_least_one_direct_label_in_same_metal_pin_rect'] for v in checks.values())
        report['source_sha256'][str(export.relative_to(root))]=sha(export)
        report['cells'][name]={'recursive_text_names_layers_and_global_positions_equal':a==b,
            'direct_top_texts_equal':direct_equal,'source_recursive_text_count':sum(a.values()),'export_recursive_text_count':sum(b.values()),
            'recursive_missing_from_export':[list(v) for v in (a-b).elements()],
            'recursive_added_in_export':[list(v) for v in (b-a).elements()],
            'correct_recursive_labels':original['recursive'],'correct_direct_top_labels':original['direct'],
            'direct_pin_checks':checks,'all_LEF_pins_have_direct_top_label_in_same_metal_rect':all(v['at_least_one_direct_label_in_same_metal_pin_rect'] for v in checks.values()),
            'legacy_wrong_coordinate_behavior_reproduced':True,
            'hierarchy_translation_affected_text_count':len(original['translation_affected']),
            'translation_correction_examples':original['translation_affected'][:8],
            'result':'PASS' if complete else 'FAIL',
            'scope':'label identity/anchors and direct pin naming; no conductor connectivity, DRC, LVS or port electrical qualification'}
    report['result']='PASS' if all(c['result']=='PASS' for c in report['cells'].values()) else 'FAIL'
    (out/'labels.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'result':report['result'],'cells':{n:{k:v for k,v in c.items() if k in (
        'source_recursive_text_count','export_recursive_text_count','hierarchy_translation_affected_text_count',
        'all_LEF_pins_have_direct_top_label_in_same_metal_rect','result')} for n,c in report['cells'].items()}},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();probe(args.root,args.output)
