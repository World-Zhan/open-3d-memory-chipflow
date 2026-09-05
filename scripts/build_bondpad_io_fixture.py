#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate isolated pad/IO gap A/B and a geometry-matched ring-pad LEF."""
import argparse,hashlib,json
from pathlib import Path
import klayout.db as k

LAYERS={'Metal2':(10,0),'Metal3':(30,0),'Metal4':(50,0),'Metal5':(67,0),'TopMetal1':(126,0),'TopMetal2':(134,0)}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def region(layout,cell,pair):
    index=layout.find_layer(*pair)
    return k.Region(cell.begin_shapes_rec(index)).merged() if index is not None else k.Region()
def make(root,output):
    source=root/'runs/bondpad-geometry-20260905-003/official_m2_square70.gds'
    source_summary=root/'runs/bondpad-geometry-20260905-003/geometry_summary.json'
    io_source=root/'upstream/croc/technology/gds/sg13g2_io.gds'
    original=root/'upstream/croc/technology/gds/bondpad_70x70.gds'
    facts=json.loads(source_summary.read_text())
    assert sha(source)==facts['official_variants']['official_m2_square70']['generated_gds_sha256']
    output.mkdir(parents=True,exist_ok=True)
    summary={'classification':'physical_fixture_not_chip_signoff','source_sha256':{str(p.relative_to(root)):sha(p) for p in (source,source_summary,io_source,original)},
             'source_io':'actual_Croc_technology_GDS_not_assumed_identical_to_PDK_GDS',
             'full_chip_modified':False,'pin_access_performed':False,'lvs_performed':False,'arms':[]}
    # Normalize the official centered macro to the Croc 0..70um origin.
    layout=k.Layout()
    layout.read(str(source))
    assert layout.dbu==0.001
    centered=layout.top_cell()
    pad=layout.create_cell('bondpad70_m2_ring')
    pad.insert(k.CellInstArray(centered.cell_index(),k.Trans(35000,35000)))
    pad.flatten(False)
    assert pad.bbox()==k.Box(0,0,70000,70000)
    pad_path=output/'bondpad70_m2_ring.gds'
    assert not pad_path.exists()
    pad.write(str(pad_path))
    lines=['VERSION 5.8 ;','MACRO bondpad70_m2_ring','  CLASS COVER ;','  ORIGIN 0 0 ;',
           '  FOREIGN bondpad70_m2_ring 0 0 ;','  SIZE 70 BY 70 ;','  SYMMETRY X Y R90 ;',
           '  SITE sg13g2_ioSite ;','  PIN pad','    DIRECTION INOUT ;','    USE SIGNAL ;','    PORT']
    matched={}
    for name,pair in LAYERS.items():
        actual=region(layout,pad,pair)
        reconstructed=k.Region()
        rects=[]
        for polygon in actual.each():
            for piece in polygon.decompose_trapezoids():
                box=piece.bbox()
                if k.Region(piece).area()!=box.area():raise ValueError('Non-rectangular geometry needs explicit LEF POLYGON')
                rects.append(box);reconstructed.insert(box)
        assert not actual.is_empty() and (actual^reconstructed).is_empty()
        lines.append('      LAYER '+name+' ;')
        for b in rects:
            lines.append('        RECT '+' '.join(f'{v*layout.dbu:.3f}' for v in (b.left,b.bottom,b.right,b.top))+' ;')
        matched[name]={'rectangles':len(rects),'area_um2':actual.area()*layout.dbu**2,'symmetric_difference_area_um2':0}
    lines += ['    END','  END pad','  OBS']
    for name in ['Metal1',*LAYERS]:
        lines += ['    LAYER '+name+' ;','      RECT 0 0 70 70 ;']
    lines += ['  END','END bondpad70_m2_ring','']
    lef=output/'bondpad70_m2_ring.lef'
    with lef.open('x') as f:f.write('\n'.join(lines))
    summary['lef_gds_contract']={'macro':'bondpad70_m2_ring','translation_um':[35,35],
            'pin_layer_geometry':matched,'lower_metal_holes_preserved':True,
            'obstructions':'conservative full 70x70 metal blockage; matching ring pin ports override only real pin geometry',
            'route_pin_access_or_via_legality_proven':False,'gds_sha256':sha(pad_path),'lef_sha256':sha(lef)}
    # Each arm uses one actual R0 IOPadIn in local outward/downward coordinates.
    for name,pad_file,gap in [('original_gap0',original,0),('official_gap0',pad_path,0),
                             ('official_gap4',pad_path,4),('official_gap10',pad_path,10)]:
        l=k.Layout();l.read(str(pad_file));bond=l.top_cell()
        l.read(str(io_source))
        io=l.cell('sg13g2_IOPadIn')
        if io is None:raise ValueError('Actual Croc IO cell missing')
        top=l.create_cell(name)
        top.insert(k.CellInstArray(io.cell_index(),k.Trans()))
        top.insert(k.CellInstArray(bond.cell_index(),k.Trans(5000,-(70000+gap*1000))))
        pin=k.Region(k.Box(5000,0,75000,3000))
        # Add only external leads. Do not extend inside the IO beyond its pad pin.
        per_layer={}
        for layer,pair in LAYERS.items():
            existing=region(l,io,pair)
            if not (pin-existing).is_empty():raise ValueError('Actual IO pin not fully covered on '+layer)
            bond_region=region(l,bond,pair).transformed(k.Trans(5000,-(70000+gap*1000)))
            lead=k.Region(k.Box(5000,-gap*1000,75000,0)) if gap else k.Region()
            if not (lead&existing).is_empty():raise ValueError('External lead overlaps existing IO metal area')
            if gap:top.shapes(l.layer(*pair)).insert(lead)
            combined=(bond_region|lead|pin).merged()
            if combined.count()!=1:raise ValueError('Pad-to-IO pin continuity failed on '+layer)
            strip=k.Region(k.Box(5000,-gap*1000,75000,7000-gap*1000))
            missing=(strip-(bond_region|lead|existing)).area()*l.dbu**2
            per_layer[layer]={'pad_lead_pin_connected':True,'seven_um_exit_missing_area_um2':missing,
                              'new_lead_overlap_existing_io_area_um2':0}
        opening=region(l,top,(9,0))&region(l,top,(41,0))
        active=region(l,io,(1,0))
        item={'name':name,'topcell':name,'gap_um':gap,'io_origin_um':[0,0],'io_orientation':'R0',
              'bondpad_origin_um':[5,-70-gap],'bbox_um':str(top.dbbox()),'per_layer':per_layer,
              'opening_active_separation_11p2um_pairs':opening.separation_check(active,11200).count(),
              'complete_netlist_equivalence_proven':False,'sealring_included':False}
        dest=output/(name+'.gds');assert not dest.exists();top.write(str(dest))
        item['gds_sha256']=sha(dest)
        summary['arms'].append(item)
    summary['outputs_sha256']={p.name:sha(p) for p in output.iterdir() if p.suffix in ('.gds','.lef')}
    with (output/'fixture_summary.json').open('x') as f:json.dump(summary,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({'arms':[(a['name'],a['opening_active_separation_11p2um_pairs']) for a in summary['arms']],'lef_contract':'passed_geometry_only'}))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/work'))
    parser.add_argument('--output',type=Path,default=Path('/output'))
    a=parser.parse_args();make(a.root,a.output)
