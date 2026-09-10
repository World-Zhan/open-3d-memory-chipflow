#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pure-read geometry/model audit. Does not run KLayout or change any deck."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('tap_reader_audit',ROOT/'scripts/audit_lvs_tap_reader.py')
TAP=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(TAP)
RUN='tap-geometry-20260910-001'
require=TAP.require
sha=TAP.sha
read=TAP.read

def perimeter(vertices):
    require(len(vertices)>=4,'insufficient polygon vertices')
    return sum(math.hypot(a[0]-b[0],a[1]-b[1]) for a,b in zip(vertices,vertices[1:]+vertices[:1]))

def area(vertices):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(vertices,vertices[1:]+vertices[:1])))/2

def number(value):
    match=re.fullmatch(r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)([fpnumk]?)',value.strip(),re.I)
    require(match is not None,'unsupported SPICE numeric token')
    return float(match[1])*{'':1,'f':1e-15,'p':1e-12,'n':1e-9,'u':1e-6,'m':1e-3,'k':1e3}[match[2].lower()]

def parse_cdl(text):
    statements=[line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith(('*','.'))]
    taps=[s for s in statements if re.search(r'\bptap1\b',s,re.I)]
    require(len(taps)==1,'expected one DCN tap statement')
    params=dict(re.findall(r'\b(A|P)\s*=\s*(\S+)',taps[0],re.I))
    require(set(k.upper() for k in params)=={'A','P'},'missing DCN A/P')
    return {'area_um2':number(params['A'])*1e12,'perimeter_um':number(params['P'])*1e6,
            'statement':taps[0],'guard_device_references':sum('GUARD' in s.upper().split()[1:] for s in statements)}

def evaluate(geometry,raw_snapshot,cdl,grid_um,raspec_ohm_m2,rpspec_ohm_m):
    TAP.STAGES.validate_snapshot(raw_snapshot)
    require(geometry['dbu_um']==0.001,'unexpected layout DBU')
    tie=geometry['regions']['ptap1_tie'];dbu=geometry['dbu_um']
    require(tie['merged_component_count']==1 and tie['hole_count']==2 and len(tie['polygons'])==1,'tap topology changed')
    poly=tie['polygons'][0];hull=poly['hull_vertices_dbu'];holes=poly['holes_vertices_dbu']
    require(len(holes)==2,'hole inventory incomplete')
    hp=perimeter(hull)*dbu;ip=sum(perimeter(h) for h in holes)*dbu
    ga=(area(hull)-sum(area(h) for h in holes))*dbu*dbu
    require(abs(ga-tie['area_um2'])<1e-9,'area disagrees with vertices')
    require(abs(hp+ip-tie['perimeter_um'])<1e-9,'perimeter disagrees with vertices')
    require(abs(hp-86.64)<1e-9 and abs(ip-135.12)<1e-9 and abs(ga-141.2964)<1e-9,'unexpected DCN dimensions')
    devices=raw_snapshot['inventory']['circuits'][0]['devices']
    taps=[d for d in devices if d['class']=='ptap1']
    require(len(taps)==1,'raw extraction does not contain exactly one tap')
    params=TAP.parameters(taps[0])
    require(abs(params['A']-ga)<1e-9 and abs(params['P']-(hp+ip))<1e-9,'raw strict extraction does not match geometry')
    require(cdl['guard_device_references']==0,'guard has schematic device reference; review model diagnosis')
    obs=geometry['derivation_observations']
    require(obs['ntap1_marker_selected_well_text_count']==0 and geometry['regions']['ntap1_marker']['merged_component_count']==0,
            'guard marked ntap1; review diagnosis')
    require(geometry['regions']['ordinary_ntap']['merged_component_count']==1 and obs['guard_contact_count']==288,
            'ordinary physical guard path evidence changed')
    require(obs['exclude_overlap_ptap_um2']==0 and obs['marker_filter_changes_pactiv_tie'] is False,'tap exclusion affects geometry')
    require(grid_um==0.005,'official PCell grid changed')
    side=round(math.sqrt(ga)/grid_um)*grid_um
    square_a=side*side;square_p=4*side
    square_consistent=abs(round(square_a,3)-cdl['area_um2'])<1e-9 and abs(square_p-cdl['perimeter_um'])<1e-9
    require(square_consistent,'CDL no longer consistent with quantized equivalent square')
    ra=raspec_ohm_m2*1e12;rp=rpspec_ohm_m*1e6
    return {'physical_geometry_proven':{'connected_components':1,'holes':2,'outer_size_um':[33.06,10.26],
                'hole_sizes_um':[[30.54,3.24],[30.54,3.24]],'hull_perimeter_um':hp,'hole_perimeter_sum_um':ip,
                'total_perimeter_um':hp+ip,'area_um2':ga,'matches_raw_strict_extraction':True},
            'cdl':cdl,
            'parameter_residuals':{'area_um2':ga-cdl['area_um2'],'perimeter_um':hp+ip-cdl['perimeter_um'],
                'area_fraction':ga/cdl['area_um2']-1,'perimeter_ratio':(hp+ip)/cdl['perimeter_um']},
            'rejected_explanations':{
                'missing_holes_only':abs(hp-cdl['perimeter_um'])>1e-9,
                'hole_perimeter_only':abs(ip-cdl['perimeter_um'])>1e-9,
                'duplicated_components_required':True,
                'shared_area_perimeter_unit_multiplier':abs(ga/cdl['area_um2']-(hp+ip)/cdl['perimeter_um'])>1e-6,
                'tap_exclusions_changed_the_actual_tie':True},
            'equivalent_square_hypothesis':{'classification':'arithmetic_consistency_not_authorship_proof',
                'actual_area_square_side_um':math.sqrt(ga),'official_grid_um':grid_um,'nearest_grid_side_um':side,
                'area_um2':square_a,'perimeter_um':square_p,'rounded_area_matches_CDL':True,
                'perimeter_matches_CDL':True,'original_IO_schematic_generator_proven':False},
            'model_sensitivity_not_measured_resistance':{
                'formula':'R = 1 / (A / raspec + P / rpspec), with consistent SI units',
                'source_parameters_ohm_m2_and_ohm_m':[raspec_ohm_m2,rpspec_ohm_m],
                'CDL_parameter_R_ohm':1/(cdl['area_um2']/ra+cdl['perimeter_um']/rp),
                'layout_geometric_parameter_R_ohm':1/(ga/ra+(hp+ip)/rp),
                'parameter_substitution_changes_model':True,'silicon_resistance_qualified':False},
            'guard_model_findings':{'ordinary_ntap_component_count':1,'contact_count':288,
                'well_marker_count':0,'ntap1_device_expected_from_current_marker_rules':False,
                'schematic_guard_device_references':0,'guard_is_real_geometry_but_unloaded_boundary_in_device_model':True}}

def audit(root):
    run=root/'runs'/RUN;manifest=read(run/'manifest.json');verified={}
    def verify(path,expected=None):
        actual=sha(path);require(expected is None or actual==expected,'hash mismatch: '+str(path))
        verified[str(path.relative_to(root))]=actual
    for rel,h in manifest['source_sha256'].items():verify(root/rel,h)
    for rel,h in manifest['output_sha256'].items():verify(run/rel,h)
    require(manifest['source_hashes_unchanged'] is True and manifest['lvs_performed'] is False,'scope or sources changed')
    terminal=read(run/'terminal_observation.json')[0]
    TAP.validate_terminal(manifest['execution'],terminal['State'])
    require(terminal['HostConfig']['NanoCpus']==2000000000 and terminal['HostConfig']['Memory']==4294967296,'resource cap changed')
    geometry=read(run/'geometry.json')
    input_file=root/geometry['source'];verify(input_file,geometry['source_sha256'])
    pdk=root/'upstream/ihp-open-pdk/ihp-sg13g2'
    source_files=[pdk/'libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech.json',
                  pdk/'libs.tech/klayout/python/sg13g2_pycell_lib/ihp/ptap1_code.py',
                  pdk/'libs.tech/klayout/python/sg13g2_pycell_lib/ihp/utility_functions.py',
                  pdk/'libs.tech/xschem/sg13g2_pr/ptap1.sym',pdk/'libs.ref/sg13g2_io/cdl/sg13g2_io.cdl']
    deck=pdk/'libs.tech/klayout/tech/lvs/rule_decks'
    source_files += [deck/n for n in ('diode_derivations.lvs','diode_extraction.lvs','general_connections.lvs')]
    for p in source_files:verify(p)
    archived_deck=root/'runs/croc-lvs-tap-reader-dcn-ab-20260910-001/control/deck/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks'
    for name in ('tap_derivations.lvs','tap_extraction.lvs','tap_connections.lvs','general_derivations.lvs',
                 'layers_definitions.lvs','custom_devices.lvs','custom_combiner.lvs','diode_derivations.lvs',
                 'diode_extraction.lvs','general_connections.lvs'):
        verify(archived_deck/name,sha(deck/name))
    snapshots=root/'runs/croc-lvs-tap-reader-dcn-ab-20260910-001/candidate/snapshots'
    stages={n:read(snapshots/(n+'.inventory.json')) for n in ('layout_netlist_raw_before_rf_mapping',
        'layout_netlist_after_rf_purge','schematic_after_reader','schematic_after_compare')}
    for n,record in stages.items():
        verify(snapshots/(n+'.inventory.json'));TAP.STAGES.validate_snapshot(record)
    def guard(stage):return [n for n in stages[stage]['inventory']['circuits'][0]['nets'] if n['name'].lower()=='guard']
    require(len(guard('layout_netlist_raw_before_rf_mapping'))==1 and not guard('layout_netlist_after_rf_purge'),'layout guard stage changed')
    require(not guard('layout_netlist_raw_before_rf_mapping')[0]['terminals'],'guard now participates in device graph')
    require(len(guard('schematic_after_reader'))==1 and not guard('schematic_after_compare'),'schematic guard stage changed')
    cdl_path=input_file.with_suffix('.cdl');verify(cdl_path)
    cdl=parse_cdl(cdl_path.read_text());tech=read(source_files[0])['techParams']
    require(cdl['statement'] in source_files[4].read_text(),'leaf CDL statement differs from fixed official library')
    result=evaluate(geometry,stages['layout_netlist_raw_before_rf_mapping'],cdl,tech['grid'],
                    number(tech['ptap1_raspec']),number(tech['ptap1_rpspec']))
    formula_sources={
        str(source_files[1].relative_to(root)):['defA       = Numeric(defL)*Numeric(defW)','defP       = 2*Numeric(defL)+2*Numeric(defW)'],
        str(source_files[2].relative_to(root)):['a = l*w','p = 2.0*(l+w)','result = 1.0/(1.0/(raspec/a) + 1.0/(rpspec/p))'],
        str(source_files[3].relative_to(root)):['lvs_format=', '@w * @l','2 * ( @w + @l )']}
    for rel,fragments in formula_sources.items():
        text=(root/rel).read_text();require(all(f in text for f in fragments),'official formula source changed')
    return {'schema_version':1,'audit_result':'PASS','classification':'physical_perimeter_explained_model_contract_unresolved',
            'run_id':RUN,'tool_version':geometry['tool_version'],'findings':result,
            'geometry_and_device_deck_sources_match_archived_strict_control':True,
            'strict_LVS_status_unchanged':'FAIL','new_LVS_performed':False,'source_pdk_modified':False,
            'source_formula_fragments':formula_sources,'source_sha256':verified,
            'next_gate':'Obtain or reconstruct the intended IO schematic tap A/P convention and unloaded guard boundary semantics; do not change parameters, tolerances, or introduce ntap1 markers solely to force a match.',
            'limitations':['The equivalent-square arithmetic matches but does not prove the original IO generator or designer intent.',
                           'The flat single-leaf geometry probe is independently matched to existing strict deep raw extraction; it is not a parent or full-chip result.',
                           'Guard geometry and a device terminal are different evidence scopes. Original CDL GUARD is a formal with no local device references.',
                           'Numeric-overflow rejection for the already archived reader is a separate future gate; adapter unchanged.',
                           'No new chip PPA, DRC, LVS, silicon resistance, or signoff qualification.']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(ROOT);a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_sha256','source_formula_fragments')},indent=2))

if __name__=='__main__':main()
