#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pure-read audit of the strict DCN LVS stage observations; never runs EDA."""
import argparse
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path

REL = Path('ihp-sg13g2/libs.tech/klayout/tech/lvs')
RUN_ID = 'croc-lvs-dcn-stage-snapshots-20260909-001'
CHECK_ID = 'croc-lvs-dcn-stage-control-check-20260909-001'
CONTROL_ID = 'croc-lvs-leaf-purge-ab-20260905-001'
OPERATIONS = ['simplify','make_top_level_pins','combine_devices','purge','purge_nets']
REQUIRED = {'schematic_after_reader', 'layout_before_align', 'schematic_before_align',
            'layout_after_align', 'schematic_after_align','layout_after_compare','schematic_after_compare'}
REQUIRED |= {'layout_netlist_'+s for s in ('raw_before_rf_mapping','after_rf_mapping','after_rf_purge_devices','after_rf_purge')}
REQUIRED |= {side+'_'+when+'_'+op for side in ('layout_netlist','schematic_netlist')
             for when in ('before','after') for op in OPERATIONS}

def require(condition, message):
    if not condition: raise ValueError(message)

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())

def validate_snapshot(record):
    require(record.get('observation_preserved_inventory') is True, 'observation changed inventory')
    require(record.get('before_sha256') == record.get('after_sha256'), 'observation inventory hashes differ')
    content = json.dumps(record['inventory'], ensure_ascii=False, separators=(',',':'))
    require(hashlib.sha256(content.encode()).hexdigest() == record['before_sha256'], 'inventory hash does not match contents')
    for circuit in record['inventory']['circuits']:
        require(all(k in circuit for k in ('nets','pins','devices','subcircuits')), 'incomplete circuit inventory')
        require([n['ordinal'] for n in circuit['nets']] == list(range(len(circuit['nets']))), 'incomplete net ordinals')
        for net in circuit['nets']:
            require(all(k in net for k in ('pins','terminals','subcircuit_pins')), 'incomplete net membership inventory')

def top(snapshots, stage):
    circuits = snapshots[stage]['inventory']['circuits']
    matches = [c for c in circuits if c['name'].lower() == 'sg13g2_dcndiode']
    require(len(matches)==1, 'missing or duplicate DCN circuit at '+stage)
    return matches[0]

def net_named(circuit, name):
    return [n for n in circuit['nets'] if n['name'].lower()==name.lower()]

def evaluate_stages(snapshots):
    require(set(snapshots)==REQUIRED, 'missing or unexpected snapshots')
    for stage,record in snapshots.items():
        require(record['stage']==stage, 'snapshot stage/file mismatch')
        validate_snapshot(record)
    stages = ['layout_netlist_raw_before_rf_mapping','layout_netlist_after_rf_mapping',
              'layout_netlist_after_rf_purge_devices','layout_netlist_after_rf_purge']
    for stage in stages[:3]:
        guards=net_named(top(snapshots,stage),'guard')
        require(len(guards)==1, 'guard absent before RF purge')
        require(not any(guards[0][k] for k in ('pins','terminals','subcircuit_pins')), 'guard is not isolated')
    require(not net_named(top(snapshots,stages[3]),'guard'), 'guard not removed at RF purge')
    for side in ('layout_netlist','schematic_netlist'):
        for op in OPERATIONS[1:]:
            require(snapshots[side+'_before_'+op]['inventory'] == snapshots[side+'_after_'+op]['inventory'],
                    'explicit skipped operation changed inventory: '+side+'/'+op)
    raw=top(snapshots,stages[0])
    require(Counter(d['class'] for d in raw['devices'])=={'dantenna':2,'ptap1':1}, 'raw layout devices changed')
    require(len(net_named(raw,'cathode'))==2, 'raw duplicate cathodes changed')
    reader=top(snapshots,'schematic_after_reader')
    require(len(reader['subcircuits'])==1 and reader['subcircuits'][0]['circuit_ref'].startswith('PTAP1('), 'reader tap stub changed')
    tapname=reader['subcircuits'][0]['circuit_ref']
    tap=[c for c in snapshots['schematic_after_reader']['inventory']['circuits'] if c['name']==tapname]
    require(len(tap)==1 and not tap[0]['devices'] and not tap[0]['subcircuits'], 'reader tap is not an empty stub')
    require(not top(snapshots,'schematic_after_align')['subcircuits'], 'tap stub not removed during align')
    require(len(snapshots['schematic_after_align']['inventory']['circuits'])==1, 'tap circuit remains after align')
    before=top(snapshots,'schematic_netlist_before_simplify')
    after=top(snapshots,'schematic_netlist_after_simplify')
    require(Counter(d['class'] for d in before['devices'])=={'DANTENNA':2}, 'schematic before simplify devices changed')
    require(Counter(d['class'] for d in after['devices'])=={'DANTENNA':1}, 'schematic diode combination changed')
    require({p['name'] for p in before['pins']}=={'ANODE','CATHODE','GUARD'}, 'schematic pre-simplify ports changed')
    require({p['name'] for p in after['pins']}=={'CATHODE'}, 'schematic simplify port removal changed')
    return {'layout_guard_first_present':'raw_extracted_inventory',
            'layout_guard_first_removed':'rfmos_model_mapping.target_netlist.purge',
            'layout_guard_before_removal':{'nets':1,'pins':0,'device_terminals':0,'subcircuit_pins':0},
            'layout_raw_device_counts':{'dantenna':2,'ptap1':1},
            'layout_raw_cathode_components':2,
            'schematic_tap_after_reader':'empty_parameterized_PTAP1_subcircuit',
            'schematic_tap_removed':'align',
            'schematic_anode_guard_ports_removed':'simplify',
            'schematic_parallel_diodes_combined':'simplify_2_to_1',
            'all_explicit_skipped_cleanup_operations_leave_inventory_unchanged':True,
            'all_observers_leave_inventory_unchanged':True,'snapshot_count':len(snapshots)}

def audit(root):
    run=root/'runs'/RUN_ID; check=root/'runs'/CHECK_ID; control=root/'runs'/CONTROL_ID
    m=read(run/'manifest.json'); cm=read(check/'manifest.json')
    verified={}
    def verify(base,mapping):
        for rel,expected in mapping.items():
            path=base/rel
            require(path.is_file() and sha(path)==expected, 'hash mismatch: '+str(path))
            verified[str(path.relative_to(root))]=expected
    for key in ('source_sha256',):verify(root,m[key])
    for key in ('input_and_deck_sha256','script_sha256','output_sha256'):verify(run,m[key])
    verify(check,cm['script_sha256']);verify(check,cm['output_sha256'])
    require(sha(root/'scripts/analyze_small_lvsdb.py')==cm['analyzer_sha256'],'analyzer hash mismatch')
    require(m['source_hashes_unchanged'] is True,'source mutation')
    require(type(m['runner_returncode']) is int and m['runner_returncode']==0,'runner not terminal zero')
    terminal=read(run/'terminal_observation.json')[0]['State']
    require(terminal==m['terminal_state'],'terminal state disagreement')
    require(terminal['Status']=='exited' and terminal['Running'] is False and terminal['OOMKilled'] is False,
            'container not cleanly terminal')
    require(type(terminal['ExitCode']) is int and terminal['ExitCode']==0 and not terminal['Error'],'container failure')
    require(not m.get('outer_timeout') and m['inner_timeout_seconds']==60 and m['outer_timeout_seconds']==85,'timeout contract changed')
    require(m['strictness']==read(control/'manifest.json')['strictness'],'strict options differ from historical control')
    require(m['strictness']['run_mode']=='deep' and m['strictness']['flag_missing_ports'] is True and
            m['strictness']['implicit_nets'] is False and m['strictness']['tap_extraction_enabled'] is True and
            m['strictness']['simplify_enabled'] is True, 'strictness weakened')
    original=control/'decks/control'; candidate=run/'deck'
    before_paths={str(p.relative_to(original)) for p in original.rglob('*') if p.is_file()}
    after_paths={str(p.relative_to(candidate)) for p in candidate.rglob('*') if p.is_file()}
    require(after_paths-before_paths=={str(REL/'rule_decks/stage_observer.lvs')},'unexpected added deck')
    require(not before_paths-after_paths,'deleted deck')
    changes=[]
    for rel in sorted(before_paths):
        if (original/rel).read_bytes()==(candidate/rel).read_bytes():continue
        changes.append(rel)
        before=(original/rel).read_text().splitlines(True);after=(candidate/rel).read_text().splitlines(True)
        for tag,i,j,a,b in difflib.SequenceMatcher(a=before,b=after,autojunk=False).get_opcodes():
            if tag=='equal':continue
            require(tag=='insert','observation patch replaces/removes original statement')
            for line in after[a:b]:
                stripped=line.strip()
                require(not stripped or stripped.startswith('stage_snapshot.call(') or
                        stripped=='# %include rule_decks/stage_observer.lvs','unexpected added rule operation')
    require(set(changes)=={str(REL/'sg13g2.lvs'),str(REL/'rule_decks/rfmos_model_mapping.lvs')},'unexpected changed deck')
    require(sha(candidate/REL/'rule_decks/stage_observer.lvs')==sha(run/'lvs_stage_observer.rb'),'observer source mismatch')
    snapshots={p.name.removesuffix('.inventory.json'):read(p) for p in (run/'snapshots').glob('*.inventory.json')}
    findings=evaluate_stages(snapshots)
    require(type(cm['returncode']) is int and cm['returncode']==0 and not cm.get('outer_timeout'),'control check failed')
    comparison=read(check/'cross_reference.json');verify(root,comparison['source_sha256'])
    require(comparison['control']==comparison['observed'],'control/observed cross reference differs')
    require(comparison['control']==read(control/'control/sg13g2_DCNDiode/cross_reference.json'),'historical/reloaded control differs')
    require(comparison['observed']['summary']['circuit_status_counts']=={'NoMatch':1},'unexpected strict final result')
    for side in ('layout','schematic'):
        require((check/('control_'+side+'.txt')).read_bytes()==(check/('observed_'+side+'.txt')).read_bytes(),'final serialized netlists differ')
    log=(run/'result/sg13g2_DCNDiode.log').read_text()
    require("ERROR : Netlists don't match" in log and 'Comparison in strict port mode.' in log and
            'flag_missing_ports enabled' in log,'missing strict FAIL log evidence')
    for side in ('layout_netlist','schematic_netlist'):
        require(f'[{side}] simplify: ENABLED' in log,'simplify disabled')
        for op in OPERATIONS[1:]:require(f'[{side}] {op}: SKIPPED' in log,'unexpected explicit option execution')
    return {'schema_version':1,'classification':'strict_DCN_leaf_observational_root_cause_not_chip_signoff',
            'run_id':RUN_ID,'control_check_run':CHECK_ID,'source_control_run':CONTROL_ID,
            'result':'FAIL','strict_leaf_lvs_passed':False,'full_chip_lvs_performed':False,
            'parent_lvs_performed':False,'source_pdk_modified':False,'audit_passed':True,
            'findings':findings,'historical_control_cross_reference_and_final_netlists_identical':True,
            'strict_result':comparison['observed']['summary'],
            'verified_unique_files':len(verified),'source_sha256':dict(sorted(verified.items())),
            'limitations':['guard has no connected device terminal at leaf; ordinary physical ntap is not an ntap1 device',
              'leaf duplicated cathodes require actual parent metal connection; no implicit connection is added',
              'ptap geometry parameter matching is still unresolved after reader support is corrected',
              'unchanged observational final result is an experiment validity check, not LVS PASS']}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=audit(args.root)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({'audit_passed':result['audit_passed'],'result':result['result'],
                      'verified_unique_files':result['verified_unique_files'],'findings':result['findings']},indent=2))

if __name__=='__main__':main()
