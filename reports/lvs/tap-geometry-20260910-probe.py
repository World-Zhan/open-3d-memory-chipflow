#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One read-only DCN GDS geometry probe; no LVS engine or deck execution."""
import hashlib
import json
import math
from pathlib import Path
import pya

ROOT=Path('/work')
SOURCE=ROOT/'runs/croc-lvs-tap-reader-dcn-ab-20260910-001/control/inputs/sg13g2_DCNDiode.gds'
layout=pya.Layout();layout.read(str(SOURCE))
cell=layout.cell('sg13g2_DCNDiode');dbu=layout.dbu
assert cell is not None

def region(layer,datatype=0):
    idx=layout.find_layer(layer,datatype)
    return pya.Region(cell.begin_shapes_rec(idx)) if idx is not None else pya.Region()

def points(iterable):return [[p.x,p.y] for p in iterable]
def length(vertices):
    return sum(math.hypot(a[0]-b[0],a[1]-b[1]) for a,b in zip(vertices,vertices[1:]+vertices[:1]))
def polygon_record(poly):
    hull=points(poly.each_point_hull());holes=[points(poly.each_point_hole(i)) for i in range(poly.holes())]
    return {'area_um2':poly.area()*dbu*dbu,'bbox_um':[v*dbu for v in (poly.bbox().left,poly.bbox().bottom,poly.bbox().right,poly.bbox().top)],
            'hull_vertices_dbu':hull,'holes_vertices_dbu':holes,'hole_count':len(holes),
            'hull_perimeter_um':length(hull)*dbu,'hole_perimeters_um':[length(h)*dbu for h in holes],
            'perimeter_um':poly.perimeter()*dbu}
def summary(reg):
    merged=reg.merged();polys=[polygon_record(p) for p in merged.each()]
    return {'merged_component_count':len(polys),'area_um2':merged.area()*dbu*dbu,
            'perimeter_um':merged.perimeter()*dbu,'hull_perimeter_sum_um':sum(p['hull_perimeter_um'] for p in polys),
            'hole_perimeter_sum_um':sum(sum(p['hole_perimeters_um']) for p in polys),
            'hole_count':sum(p['hole_count'] for p in polys),'polygons':polys}

all_layers=[]
texts=[]
for idx in layout.layer_indices():
    info=layout.get_info(idx)
    reg=pya.Region(cell.begin_shapes_rec(idx))
    rows=[]
    it=cell.begin_shapes_rec(idx)
    while not it.at_end():
        shape=it.shape()
        if shape.is_text():
            t=shape.text.transformed(it.trans())
            row={'layer':info.layer,'datatype':info.datatype,'text':t.string,'x_dbu':t.x,'y_dbu':t.y}
            rows.append(row);texts.append(row)
        it.next()
    if reg.size() or rows:
        all_layers.append({'layer':info.layer,'datatype':info.datatype,'raw_polygon_count':reg.size(),'text_count':len(rows),
                           'area_um2':reg.area()*dbu*dbu})

active=region(1)|region(1,22);psd=region(14);nwell=region(31);substrate=region(40)
chip=pya.Region(cell.bbox())
pwell=(chip-region(46,21))-nwell-(region(60)-region(60).sized(-1))
pactiv=active&psd;nactiv=active-(psd|region(7,21))
sub_labels=[t for t in texts if t['layer']==63 and t['datatype']==0 and t['text'].lower()=='sub!']
well_labels=[t for t in texts if t['layer']==63 and t['datatype']==0 and t['text'].lower()=='well']
def select_by_labels(reg,labels):
    result=pya.Region()
    selected=[]
    for poly in reg.merged().each():
        matches=[t for t in labels if poly.inside(pya.Point(t['x_dbu'],t['y_dbu']))]
        if matches:result.insert(poly);selected.extend(matches)
    return result,selected
ptap_marker,sub_selected=select_by_labels(substrate&pwell,sub_labels)
ntap_marker,well_selected=select_by_labels(nwell,well_labels)
exclude_layers=[(5,0),(5,22),(7,0),(26,0),(33,0),(156,0),(28,0),(128,0),(111,0),(24,0),(1,20),(99,31),(27,0),(27,2)]
exclude=pya.Region()
for pair in exclude_layers:exclude=exclude|region(*pair)
ptap_tie=(pactiv&ptap_marker)-(nwell|exclude)
ntap_tie=(nactiv&ntap_marker)-(pwell|psd|exclude)
ordinary_ntap=(nactiv&nwell)-ntap_marker-region(99,31)-(region(5)|region(5,22))
contacts=region(6)
guard_contacts=contacts.interacting(ordinary_ntap)

named={'active':active,'pactiv':pactiv,'nactiv':nactiv,'nwell':nwell,'substrate':substrate,
       'ptap1_marker':ptap_marker,'ptap1_tie':ptap_tie,'ntap1_marker':ntap_marker,'ntap1_tie':ntap_tie,
       'ordinary_ntap':ordinary_ntap,'pactiv_without_marker_filter':pactiv-(nwell|exclude),
       'ptap1_hulls':ptap_tie.hulls(),'ptap1_holes':ptap_tie.holes()}
data={name:summary(reg) for name,reg in named.items()}
intermediate={'exclude_overlap_ptap_um2':((pactiv&ptap_marker)&(nwell|exclude)).area()*dbu*dbu,
              'excluded_layers_nonempty':[{'layer':a,'datatype':b,'polygon_count':region(a,b).size()} for a,b in exclude_layers if region(a,b).size()],
              'marker_filter_changes_pactiv_tie':not ((pactiv-(nwell|exclude))^ptap_tie).is_empty(),
              'pwell_block_polygons':region(46,21).size(),'digisub_polygons':region(60).size(),
              'guard_contact_count':guard_contacts.size(),'guard_contact_area_um2':guard_contacts.area()*dbu*dbu,
              'ntap1_marker_selected_well_text_count':len(well_selected),'ptap1_marker_selected_sub_text_count':len(sub_selected)}
report={'schema_version':1,'classification':'read_only_geometry_definition_probe_no_LVS',
        'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'source':str(SOURCE.relative_to(ROOT)),
        'tool_version':getattr(pya,'__version__',None),'dbu_um':dbu,'all_nonempty_layers':all_layers,'texts':texts,
        'regions':data,'derivation_observations':intermediate,
        'scope':'Flat Boolean reconstruction of this single leaf only; existing strict deep snapshots provide independent extraction A/P.'}
Path('/output/geometry.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({'ptap1_tie':{k:v for k,v in data['ptap1_tie'].items() if k!='polygons'},'derivation_observations':intermediate},indent=2))
