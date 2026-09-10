#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Final physical audit with exact scope, independent terminal state and corrected label anchors."""
import argparse
import json
import shlex
from pathlib import Path
from audit_ihp_io_physical import audit as original_audit,sha
from probe_ihp_io_physical import CELLS

def exact_scope(arms,geometry,labels):
    if set(arms)!=set(CELLS[:2]) or set(geometry)!=set(CELLS) or set(labels)!=set(CELLS):
        raise ValueError('Require exactly two DRC macros and three geometry/label macros')

def terminal(execution,observation,allowed):
    state=execution.get('terminal_state',{})
    if observation.get('state_returncode')!=0 or state!=observation.get('state'):
        raise ValueError('Independent terminal observation differs')
    rc=execution.get('returncode')
    if rc not in allowed or state.get('ExitCode')!=rc or state.get('Status')!='exited' or state.get('Running') is not False or state.get('OOMKilled') is not False:
        raise ValueError('Terminal execution is not qualified')

def exact_command(command):
    args=shlex.split(command[-1])
    for key,value in {'--mp':'1','--density_thr':'1','--run_mode':'deep'}.items():
        if args.count(key)!=1 or args.index(key)+1>=len(args) or args[args.index(key)+1]!=value:
            raise ValueError('Unexpected DRC argument '+key)
    if args.count('--antenna')!=1 or any(arg.startswith(('--no_','--disable_','--precheck','--density_only','--antenna_only','--drc_json')) or arg=='--table' for arg in args):
        raise ValueError('Disabled or incomplete DRC command')

def audit(root):
    run=root/'runs/ihp-io-physical-20260910-001';labels_run=root/'runs/ihp-io-labels-20260910-001'
    result=original_audit(root,run)
    original=root/'reports/ppa/ihp-io-physical-20260910-001.json'
    if result!=json.loads(original.read_text()):raise ValueError('Original physical audit no longer reproduces')
    m=json.loads((run/'manifest.json').read_text());lm=json.loads((labels_run/'manifest.json').read_text());labels=json.loads((labels_run/'labels.json').read_text())
    exact_scope(m['arms'],result['geometry'],labels['cells'])
    terminal(m['geometry_execution'],json.loads((run/'geometry/terminal_observation.json').read_text()),{0})
    for name,arm in m['arms'].items():
        exact_command(arm['execution']['command'])
        terminal(arm['execution'],json.loads((run/name/'terminal_observation.json').read_text()),{0,1})
    terminal(lm['execution'],json.loads((labels_run/'terminal_observation.json').read_text()),{0})
    hashes=result['evidence_sha256']
    for source in (lm,labels):
        for rel,digest in source['source_sha256'].items():
            if sha(root/rel)!=digest:raise ValueError('Changed label source '+rel)
            hashes[rel]=digest
    for rel,digest in lm['outputs_sha256'].items():
        p=labels_run/rel
        if sha(p)!=digest:raise ValueError('Changed label output '+rel)
        hashes[str(p.relative_to(root))]=digest
    for p in (original,labels_run/'manifest.json',root/'scripts/audit_ihp_io_physical_final.py'):
        hashes[str(p.relative_to(root))]=sha(p)
    if not lm['source_hashes_unchanged'] or labels['result']!='PASS':raise ValueError('Label readback incomplete')
    for name,c in labels['cells'].items():
        required=('all_LEF_pins_have_direct_top_label_in_same_metal_rect','direct_top_texts_equal','recursive_text_names_layers_and_global_positions_equal')
        if any(c[k] is not True for k in required) or c['source_recursive_text_count']<=0 or c['source_recursive_text_count']!=c['export_recursive_text_count']:
            raise ValueError('Label names/positions or pin anchors differ')
        result['geometry'][name]['corrected_label_readback']={k:c[k] for k in (*required,'source_recursive_text_count','export_recursive_text_count','hierarchy_translation_affected_text_count')}
    result['classification']='final_official_IO_physical_audit_with_corrected_labels_not_signoff'
    result['exact_macro_scope_and_independent_terminal_states_verified']=True
    result['canonical_label_coordinates']='runs/ihp-io-labels-20260910-001/labels.json'
    result['superseded_coordinate_metadata']='Original geometry.json preserves a Vector transform that omits child translation. Ignore its position_um label metadata; polygon comparisons and LEF metal coverage were unaffected.'
    result['interpretation']='Isolated macro merged markers: '+json.dumps({n:{'density':a['density_markers'],'other':a['non_density_markers'],'strict_DRC':a['strict_fixture_DRC']} for n,a in result['DRC'].items()},sort_keys=True)+'. No assembled ring/chip or PG/LVS qualification.'
    result['migration_qualified']=False
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(Path(__file__).resolve().parents[1])
    with a.output.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({'audit_result':result['audit_result'],'hashes':len(result['evidence_sha256']),'strict_drc':{n:x['strict_fixture_DRC'] for n,x in result['DRC'].items()},'migration_qualified':False}))
