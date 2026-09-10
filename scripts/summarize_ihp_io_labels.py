#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pure-read validation and compact publication summary of label readback."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/ihp-io-labels-20260910-001'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def main():
    m=read(RUN/'manifest.json');r=read(RUN/'labels.json');actual=read(RUN/'terminal_observation.json')['state']
    e=m['execution']
    if e['terminal_state']!=actual or type(e['returncode']) is not int or e['returncode']!=0:
        raise ValueError('runner/independent terminal observation differs or failed')
    if actual['Status']!='exited' or actual['Running'] is not False or actual['OOMKilled'] is not False or actual['ExitCode']!=0 or actual['Error']:
        raise ValueError('unhealthy actual terminal')
    if e['inner_timeout_seconds']!=60 or e['outer_timeout_seconds']!=85 or e['container_cleanup_returncode']!=0:
        raise ValueError('limits or cleanup differ')
    verified={}
    for base,mapping in ((ROOT,m['source_sha256']),(RUN,m['outputs_sha256'])):
        for rel,h in mapping.items():
            p=base/rel
            if sha(p)!=h:raise ValueError('hash changed: '+str(p))
            verified[str(p.relative_to(ROOT))]=h
    for p in (Path(__file__),RUN/'manifest.json'):verified[str(p.relative_to(ROOT))]=sha(p)
    required={'sg13g2_IOPadOut16mA','sg13g2_IOPadInOut30mA','sg13g2_IOPadIn'}
    if not m['source_hashes_unchanged'] or r['result']!='PASS' or set(r['cells'])!=required:
        raise ValueError('incomplete labels result')
    summary={}
    for name,c in r['cells'].items():
        if not all(c[k] for k in ('recursive_text_names_layers_and_global_positions_equal','direct_top_texts_equal',
                    'all_LEF_pins_have_direct_top_label_in_same_metal_rect','legacy_wrong_coordinate_behavior_reproduced')):
            raise ValueError('label verification failed')
        if c['recursive_missing_from_export'] or c['recursive_added_in_export']:raise ValueError('text export differs')
        summary[name]={k:c[k] for k in ('recursive_text_names_layers_and_global_positions_equal','direct_top_texts_equal',
                'source_recursive_text_count','export_recursive_text_count','hierarchy_translation_affected_text_count',
                'all_LEF_pins_have_direct_top_label_in_same_metal_rect','legacy_wrong_coordinate_behavior_reproduced')}
        summary[name]['direct_top_text_count']=len(c['correct_direct_top_labels'])
        summary[name]['LEF_pin_count']=len(c['direct_pin_checks'])
        summary[name]['direct_pin_checks']=c['direct_pin_checks']
    report={'schema_version':1,'result':'PASS','classification':'corrected_label_anchor_readback_not_connectivity_or_signoff',
            'run_id':RUN.name,'raw_report':str((RUN/'labels.json').relative_to(ROOT)),
            'coordinate_method':r['coordinate_method'],'dbu_um':r['dbu_um'],'cells':summary,
            'source_sha256':verified,'execution_healthy':True,'source_hashes_unchanged':True,
            'old_geometry_json_modified':False,'new_DRC_or_LVS_performed':False,'public_rule_signoff':False,
            'superseded_metadata':{'file':'runs/ihp-io-physical-20260910-001/geometry/geometry.json',
                'field':'cells.*.official_gds_pin_labels[*].position_um',
                'reason':'Historical Vector transform omits hierarchy translation. Use corrected Point-transform anchors in raw_report; original bytes retained.'},
            'scope':'Every LEF pin has at least one same-metal datatype-25 direct top-level text anchor inside its pin rectangle. Child aliases cannot satisfy this check; conductor connectivity, PG and strict LVS remain unproven.'}
    dest=ROOT/'reports/ppa/ihp-io-labels-20260910-001.json'
    if dest.exists():raise ValueError('summary already exists')
    dest.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    files=[ROOT/'scripts/probe_ihp_io_labels.py',Path(__file__),dest]+list(RUN.iterdir())
    entries=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files) if p.is_file()]
    inventory={'schema_version':1,'files':entries,'file_count':len(entries),'total_bytes':sum(e['bytes'] for e in entries),
               'whitelist_self_included':False,'raw_evidence_preserve_bytes':True,'staging_performed':False}
    inv=ROOT/'reports/ppa/ihp-io-labels-publication-inventory-20260910-001.json'
    inv.write_text(json.dumps(inventory,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'summary':str(dest),'inventory':str(inv),'files':len(entries),'bytes':inventory['total_bytes']}))

if __name__=='__main__':main()
