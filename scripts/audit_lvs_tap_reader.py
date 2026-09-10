#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit tap-X reader semantics and strict DCN A/B; no EDA execution."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
READER_ID='croc-lvs-tap-reader-regression-20260910-001'
LEAF_ID='croc-lvs-tap-reader-dcn-ab-20260910-001'
XREF_ID='croc-lvs-tap-reader-xref-20260910-001'

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

STAGES=module('stages',ROOT/'scripts/audit_lvs_dcn_stages.py')
READER=module('reader',ROOT/'reports/lvs/run_tap_reader_ab.py')
require=STAGES.require
read=STAGES.read
sha=STAGES.sha

def snapshots(folder):
    return {p.name.removesuffix('.inventory.json'):read(p) for p in folder.glob('*.inventory.json')}

def validate_terminal(execution,actual):
    require(execution.get('terminal_state')==actual,'terminal observation differs')
    require(type(execution.get('returncode')) is int and execution['returncode']==0,'runner exit not zero')
    require(actual.get('Status')=='exited' and actual.get('Running') is False and actual.get('OOMKilled') is False,
            'terminal not healthy')
    require(type(actual.get('ExitCode')) is int and actual['ExitCode']==0 and not actual.get('Error'),'container exit not zero')
    require(not execution.get('outer_timeout') and execution.get('cleanup_returncode')==0,'timeout or incomplete cleanup')
    require(execution.get('inner_timeout_seconds')==60 and execution.get('outer_timeout_seconds')==85,'timeout contract changed')

def tap(circuit):
    result=[d for d in circuit['devices'] if d['class'].lower()=='ptap1']
    require(len(result)==1,'missing or duplicate tap device');return result[0]

def parameters(device):return {p['name']:p['value'] for p in device['parameters']}

def evaluate_leaf(control,candidate):
    STAGES.evaluate_stages(control)
    require(set(candidate)==STAGES.REQUIRED,'missing or unexpected candidate snapshots')
    for stage,record in candidate.items():
        require(record['stage']==stage,'candidate stage/file mismatch');STAGES.validate_snapshot(record)
        if stage.startswith('layout'):
            require(record['inventory']==control[stage]['inventory'],'layout inventory changed at '+stage)
    for stage in ('schematic_after_reader','schematic_after_align','schematic_netlist_after_simplify','schematic_after_compare'):
        c=STAGES.top(candidate,stage);device=tap(c)
        require(not c['subcircuits'],'tap remains empty subcircuit')
        terms={t['name']:t['net_name'] for t in device['terminals']}
        require(terms=={'TIE':'ANODE','WELL':'SUB!'},'tap terminal polarity changed')
        params=parameters(device)
        require(set(params)=={'A','P'} and abs(params['A']-141.253)<1e-9 and abs(params['P']-47.54)<1e-9,
                'schematic tap units or parameters changed')
    before=STAGES.top(candidate,'schematic_netlist_before_simplify')
    after=STAGES.top(candidate,'schematic_after_compare')
    require({p['name'] for p in before['pins']}=={'ANODE','CATHODE','GUARD'},'schematic source ports changed')
    require({p['name'] for p in after['pins']}=={'ANODE','CATHODE'},'anode lost or guard artificially retained')
    layout=STAGES.top(candidate,'layout_after_compare');lp=parameters(tap(layout))
    require(abs(lp['A']-141.2964)<1e-9 and abs(lp['P']-221.76)<1e-9,'layout tap parameters changed')
    require(len(STAGES.net_named(layout,'cathode'))==2,'physical cathode components changed')
    return {'snapshot_count_per_arm':31,'layout_inventory_unchanged_at_all_stages':True,
            'schematic_tap_device_preserved_through_align_simplify_compare':True,
            'schematic_anode_port_preserved':True,'guard_still_removed':True,
            'layout_guard_removal_stage':'RF mapping target_netlist.purge',
            'schematic_guard_removal_stage':'simplify',
            'layout_cathode_components':2,'schematic_cathode_components':1,
            'tap_parameters':{'layout_A_um2':lp['A'],'layout_P_um':lp['P'],
                              'schematic_A_um2':141.253,'schematic_P_um':47.54},
            'tap_parameter_comparison_qualified':False}

def audit(root):
    runs={key:root/'runs'/value for key,value in [('reader',READER_ID),('leaf',LEAF_ID),('xref',XREF_ID)]}
    manifests={k:read(v/'manifest.json') for k,v in runs.items()}
    verified={}
    def verify(base,mapping):
        for rel,digest in mapping.items():
            path=base/rel;require(path.is_file() and sha(path)==digest,'source/output hash mismatch: '+str(path))
            verified[str(path.relative_to(root))]=digest
    historical=read(root/'runs'/STAGES.CONTROL_ID/'manifest.json')
    for key,manifest in manifests.items():
        verify(root,manifest['source_sha256']);verify(runs[key],manifest['output_sha256'])
        require(manifest.get('source_hashes_unchanged') is True,'source hashes changed')
        if key=='xref':
            validate_terminal(manifest['execution'],read(runs[key]/'terminal_observation.json')[0]['State'])
        else:
            require(manifest['strictness']==historical['strictness'],'strictness changed')
            require(not manifest['source_pdk_modified'] and not manifest['parent_lvs_performed'] and
                    not manifest['full_chip_lvs_performed'],'scope exceeded')
            for arm in ('control','candidate'):
                validate_terminal(manifest[arm],read(runs[key]/arm/'terminal_observation.json')[0]['State'])
                inputs=read(runs[key]/arm/'terminal_observation.json')[0]['HostConfig']
                require(inputs['NanoCpus']==2000000000 and inputs['Memory']==4294967296,'resource cap changed')
    reader_eval=READER.evaluate_reader(*[read(runs['reader']/arm/'results.json') for arm in ('control','candidate')])
    require(reader_eval==manifests['reader']['reader_regression'],'stored reader result differs')
    leaf_snaps={arm:snapshots(runs['leaf']/arm/'snapshots') for arm in ('control','candidate')}
    leaf_eval=evaluate_leaf(leaf_snaps['control'],leaf_snaps['candidate'])
    old=snapshots(root/'runs'/STAGES.RUN_ID/'snapshots')
    require(leaf_snaps['control']==old,'fresh control differs from historical observation')
    # Prove the sole semantic deck change is the already tested appended adapter.
    for key in ('reader','leaf'):
        control=runs[key]/'control/deck';candidate=runs[key]/'candidate/deck'
        paths={p.relative_to(control) for p in control.rglob('*') if p.is_file()}
        require(paths=={p.relative_to(candidate) for p in candidate.rglob('*') if p.is_file()},'deck inventory changed')
        for rel in paths:
            if rel==READER.READER:
                require((candidate/rel).read_text()==(control/rel).read_text()+'\n'+(runs[key]/'tap_reader_adapter.rb').read_text(),
                        'reader contains unreviewed changes')
            else: require(sha(control/rel)==sha(candidate/rel),'non-reader deck differs')
    xref={arm:read(runs['xref']/(arm+'.json')) for arm in ('control','candidate')}
    for arm in ('control','candidate'):
        require(xref[arm]['source_sha256']==sha(runs['leaf']/arm/'result/sg13g2_DCNDiode.lvsdb'),'xref source mismatch')
        summary=xref[arm]['summary']
        require(summary['circuit_status_counts']=={'NoMatch':1},'strict leaf result changed; review required')
        require("ERROR : Netlists don't match" in (runs['leaf']/arm/'tool.log').read_text(),'missing strict failure evidence')
        require(summary['object_pair_status_counts']['device'].get('Match',0)==0,'unexpected device match; review required')
    origin_path=root/'runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260830-rerun-002/summary.json'
    identity_path=root/'runs'/STAGES.CONTROL_ID/'leaf_source_identity.json'
    origin=read(origin_path);identity=read(identity_path)
    for p in (origin_path,identity_path):verified[str(p.relative_to(root))]=sha(p)
    for item in origin['official_inputs'].values():
        verify(root,{item['path']:item['sha256']})
    for item in identity['sources'].values():verify(root,{item['path']:item['sha256']})
    dcn=next(item for item in origin['cases'] if item['cell']=='sg13g2_DCNDiode')
    geometry=next(item for item in identity['targets'] if item['cell']=='sg13g2_DCNDiode')
    require(geometry['geometry_equal'] and geometry['labels_equal'],'historical DCN geometry identity not established')
    require(dcn['gds_input_identity']['run_specific_generated_file']['raw_sha256']==
            sha(runs['leaf']/'control/inputs/sg13g2_DCNDiode.gds'),'origin leaf GDS differs')
    provenance={'kind':'fixed_official_PDK_DCN_leaf_export_reused_not_new_actual_Croc_export',
                'ihp_pdk_commit':origin['ihp_pdk_commit'],'official_inputs':origin['official_inputs'],
                'origin_report':str(origin_path.relative_to(root)),
                'leaf_geometry_and_labels_equal_to_actual_croc_at_verified_source_hashes':True,
                'whole_IO_library_equivalence_proven':False,
                'input_sha256':{ext:sha(runs['leaf']/'control/inputs'/('sg13g2_DCNDiode.'+ext)) for ext in ('gds','cdl')}}
    return {'schema_version':1,'audit_result':'PASS','classification':'reader_repair_proven_strict_leaf_still_FAIL',
            'reader_regression':reader_eval,'strict_leaf_AB':leaf_eval,'input_provenance':provenance,
            'strict_lvs_result':{'control':'FAIL','candidate':'FAIL'},
            'cross_reference_summaries':{a:xref[a]['summary'] for a in xref},
            'fresh_control_identical_to_historical_snapshots':True,
            'source_pdk_modified':False,'parent_lvs_performed':False,'full_chip_lvs_performed':False,
            'verified_source_and_output_file_count':len(verified),'verified_sha256':verified,
            'limitations':['Tap reader repair is not device correspondence or parameter closure.',
                           'No device pairs Match; restored schematic tap increases exposed unpaired devices from 4 to 5.',
                           'Leaf duplicated cathodes depend on real parent metal; no new parent test performed.',
                           'Guard remains isolated in the extracted device graph and removed by the unchanged purge.',
                           'PTAP1 perimeter remains 221.76 um layout versus 47.54 um schematic.',
                           'Nonunit scale, multiplicity and unsupported tap X parameters are explicitly rejected.'],
            'next_gate':'Read-only geometry/model derivation for tap perimeter and supported guard representation, then separately scoped physical parent fixture; no full-chip LVS yet.'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(ROOT)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('verified_sha256','cross_reference_summaries')},indent=2))

if __name__=='__main__':main()
