#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare pinned old/new IO geometry and verify LEF pins against actual GDS metal."""
import argparse
import hashlib
import json
import re
from pathlib import Path

CELLS=('sg13g2_IOPadOut16mA','sg13g2_IOPadInOut30mA','sg13g2_IOPadIn')
METALS={'Metal1':(8,0),'Metal2':(10,0),'Metal3':(30,0),'Metal4':(50,0),'Metal5':(67,0),'TopMetal1':(126,0),'TopMetal2':(134,0)}
OFFICIAL='upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io'
OLD='upstream/croc/technology'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def lef_macro(text,name):
    macros=re.findall(r'^MACRO '+re.escape(name)+r'\s*$(.*?)^END '+re.escape(name)+r'\s*$',text,re.M|re.S)
    if len(macros)!=1:raise ValueError('Missing/duplicated macro '+name)
    body=macros[0]
    sizes=re.findall(r'\bSIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;',body)
    if len(sizes)!=1:raise ValueError('Missing/duplicated SIZE')
    pins={}
    for pin,content in re.findall(r'^\s*PIN\s+(\S+)\s*$(.*?)^\s*END\s+\1\s*$',body,re.M|re.S):
        if pin in pins:raise ValueError('Duplicated pin')
        if 'POLYGON' in content or 'PATH' in content:raise ValueError('Unsupported non-RECT pin geometry')
        layer=None;rects=[]
        for line in content.splitlines():
            fields=line.split()
            if not fields:continue
            if fields[0]=='LAYER':layer=fields[1]
            if fields[0]=='RECT':
                if layer not in METALS:raise ValueError('Unsupported pin layer '+str(layer))
                xy=[float(v) for v in fields[1:5]]
                if not xy[0]<xy[2] or not xy[1]<xy[3]:raise ValueError('Empty pin rectangle')
                rects.append({'layer':layer,'um':xy})
        directions=re.findall(r'\bDIRECTION\s+(\w+)\s*;',content)
        uses=re.findall(r'\bUSE\s+(\w+)\s*;',content)
        if len(directions)!=1 or len(uses)!=1 or not rects:raise ValueError('Incomplete pin '+pin)
        pins[pin]={'direction':directions[0],'use':uses[0],'rects':rects}
    if not pins:raise ValueError('No pins')
    return {'size_um':[float(v) for v in sizes[0]],'pins':pins}

def probe(root,out):
    import klayout.db as k
    layouts={}
    hashes={}
    for label,base in [('official',OFFICIAL),('croc',OLD)]:
        for folder,suffix in [('gds','.gds'),('lef','.lef')]:
            p=root/base/folder/('sg13g2_io'+suffix);hashes[str(p.relative_to(root))]=sha(p)
        layout=k.Layout();layout.read(str(root/base/'gds/sg13g2_io.gds'))
        if layout.dbu!=0.001:raise ValueError('Unexpected DBU')
        layouts[label]=layout
    def region(layout,cell,pair):
        idx=layout.find_layer(*pair)
        return k.Region(cell.begin_shapes_rec(idx)).merged() if idx is not None else k.Region()
    report={'classification':'matched_IO_physical_views_not_connectivity_or_signoff','source_sha256':hashes,
            'cells':{},'official_pdk_modified':False,'chip_layout_modified':False,'full_chip_lvs_performed':False}
    for name in CELLS:
        cells={label:layout.cell(name) for label,layout in layouts.items()}
        if any(c is None for c in cells.values()):raise ValueError('Missing GDS cell '+name)
        lef={label:lef_macro((root/base/'lef/sg13g2_io.lef').read_text(),name) for label,base in [('official',OFFICIAL),('croc',OLD)]}
        layers=set()
        for layout in layouts.values():
            layers.update((layout.get_info(idx).layer,layout.get_info(idx).datatype) for idx in layout.layer_indexes())
        differences={}
        for pair in sorted(layers):
            regions={label:region(layout,cells[label],pair) for label,layout in layouts.items()}
            delta=regions['official']^regions['croc']
            if not delta.is_empty():differences[str(pair)]={'xor_area_um2':delta.area()*1e-6,'official_area_um2':regions['official'].area()*1e-6,'croc_area_um2':regions['croc'].area()*1e-6}
        checks=[]
        for pin,info in lef['official']['pins'].items():
            for rect in info['rects']:
                values=[v*1000 for v in rect['um']]
                if any(abs(v-round(v))>1e-6 for v in values):raise ValueError('Off-DBU pin')
                area=k.Region(k.Box(*[round(v) for v in values]))
                uncovered=area-region(layouts['official'],cells['official'],METALS[rect['layer']])
                checks.append({'pin':pin,'layer':rect['layer'],'rect_um':rect['um'],'uncovered_um2':uncovered.area()*1e-6,'covered':uncovered.is_empty()})
        labels=[]
        layout=layouts['official'];cell=cells['official']
        for idx in layout.layer_indexes():
            info=layout.get_info(idx);iterator=cell.begin_shapes_rec(idx)
            while not iterator.at_end():
                shape=iterator.shape()
                if shape.is_text():
                    text=shape.text;pos=iterator.trans()*text.trans.disp
                    if text.string in lef['official']['pins']:
                        labels.append({'name':text.string,'layer':[info.layer,info.datatype],'position_um':[pos.x*.001,pos.y*.001]})
                iterator.next()
        saved=out/(name+'.gds');cell.write(str(saved))
        readback=k.Layout();readback.read(str(saved));tops=[c.name for c in readback.top_cells()]
        if tops!=[name]:raise ValueError('Export has wrong tops')
        xor_export={str(pair):(region(layout,cell,pair)^region(readback,readback.cell(name),pair)).area() for pair in layers}
        if any(xor_export.values()):raise ValueError('Geometry changed on export')
        report['cells'][name]={'official_lef':lef['official'],'croc_lef':lef['croc'],
            'same_lef_size':lef['official']['size_um']==lef['croc']['size_um'],
            'same_lef_pin_names':set(lef['official']['pins'])==set(lef['croc']['pins']),
            'same_lef_pin_shapes':lef['official']==lef['croc'],
            'gds_bbox_um':{label:[c.bbox().left*.001,c.bbox().bottom*.001,c.bbox().right*.001,c.bbox().top*.001] for label,c in cells.items()},
            'changed_polygon_layers':differences,'official_pin_metal_checks':checks,'official_gds_pin_labels':labels,
            'pin_label_names_complete':{x['name'] for x in labels}==set(lef['official']['pins']),
            'all_LEF_pin_rectangles_covered_by_GDS_metal':all(c['covered'] for c in checks),
            'export_geometry_equal':True,'exported_gds_sha256':sha(saved),'exported_gds_file':saved.name,
            'strict_LVS':'NOT_RUN_leaf_gate_unresolved','PG_connectivity':'NOT_PROVEN_by_geometry_overlap'}
    (out/'geometry.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({name:{'changed_polygon_layers':len(v['changed_polygon_layers']),'pin_rects_covered':v['all_LEF_pin_rectangles_covered_by_GDS_metal'],'pin_label_names_complete':v['pin_label_names_complete']} for name,v in report['cells'].items()}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();probe(a.root,a.output)
