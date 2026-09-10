#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read sequential main/density/antenna/maximal evidence without rerunning DRC."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from audit_bondpad_drc import antenna_complete,antenna_categories

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def completion(main,density,antenna,maximal,tool,categories,state,rc):
    switches=('FEOL','BEOL','OFFGRID','ANGLE','PIN','FORBIDDEN','RECOMMENDED','CONNECTIVITY_RULES')
    checks={key:bool(re.search(r'\b'+key+r' enabled: true\b',main)) for key in switches}
    checks['full_main']=bool(re.search(r"tables 'main' completed in [\d.]+ seconds",main)) and 'PreCheck DRC enabled: false' in main
    checks['density']=bool(re.search(r'run for density table completed in [\d.]+ seconds',density))
    checks['antenna']=bool(antenna_complete(antenna,categories))
    checks['maximal']=bool(re.search(r'run for maximum ruleSet completed in [\d.]+ seconds',maximal))
    checks['all_tasks_joined']='Total DRC Run time:' in tool
    checks['no_tool_exception']=not bool(re.search(r'(?im)^ERROR:|Traceback|generated an exception|CalledProcessError|std::bad_alloc|Signal number:|core dumped',main+'\n'+density+'\n'+antenna+'\n'+maximal+'\n'+tool))
    checks['terminal']=state.get('Status')=='exited' and state.get('Running') is False and state.get('OOMKilled') is False and state.get('ExitCode')==rc and rc in (0,1)
    return checks

def command_is_strict(cmd):
    command=cmd[-1]
    forbidden=('--no_','--disable_','--precheck','--density_only','--antenna_only','--table','--drc_json')
    return not any(x in command for x in forbidden) and all(x in command for x in ('--mp 1','--run_mode deep','--density_thr 1','--antenna'))

def audit(root,run):
    manifest=run/'manifest.json';m=json.loads(manifest.read_text());verified={}
    def verify(path,expected=None):
        digest=sha(path)
        if expected is not None and digest!=expected:raise ValueError('Evidence changed '+str(path))
        verified[str(path.relative_to(root))]=digest
    verify(manifest)
    for rel,digest in m['source_sha256'].items():verify(root/rel,digest)
    for rel,digest in m['outputs_sha256'].items():verify(run/rel,digest)
    if not m['source_hashes_unchanged']:raise ValueError('Sources changed during execution')
    verify(root/'scripts/audit_ihp_io_physical.py');verify(root/'scripts/audit_bondpad_drc.py')
    g=json.loads((run/'geometry/geometry.json').read_text())
    ge=m['geometry_execution'];state=ge['terminal_state']
    if ge['returncode']!=0 or state.get('ExitCode')!=0 or state.get('OOMKilled') is not False:raise ValueError('Geometry execution unqualified')
    if set(g['cells'])!={'sg13g2_IOPadOut16mA','sg13g2_IOPadInOut30mA','sg13g2_IOPadIn'}:raise ValueError('Missing macro geometry')
    arms={}
    for name,arm in m['arms'].items():
        folder=run/name
        def log(kind):
            return (folder/(name+'_'+name+'_'+kind+'.log')).read_text()
        reports=list(folder.glob('*_full.lyrdb'))
        if len(reports)!=1:raise ValueError('Missing/duplicate full report')
        tree=ET.parse(reports[0]);entries=tree.findall('.//categories/category')
        categories={x.findtext('name'):x.findtext('description','') for x in entries}
        counts=dict(sorted(Counter((x.findtext('category') or '').strip("'") for x in tree.findall('.//items/item')).items()))
        if not all(x in categories for x in counts):raise ValueError('Unknown marker category')
        execution=arm['execution']
        checks=completion(log('main'),log('density'),log('antenna'),log('sg13g2_maximal'),(folder/'tool.log').read_text(),categories,execution['terminal_state'],execution['returncode'])
        checks['strict_command']=command_is_strict(execution['command'])
        density={n:v for n,v in counts.items() if 'density' in categories[n].lower()}
        nondensity={n:v for n,v in counts.items() if n not in density}
        complete=all(checks.values())
        arms[name]={'execution_complete':complete,'execution_checks':checks,'exit_code':execution['returncode'],
            'category_count':len(categories),'antenna_category_count':len(antenna_categories()&categories.keys()),
            'merged_markers':sum(counts.values()),'merged_marker_counts':counts,
            'density_markers':sum(density.values()),'density_marker_descriptions':{n:categories[n] for n in density},
            'non_density_markers':sum(nondensity.values()),'non_density_marker_counts':nondensity,
            'raw_maximal_markers':None,'raw_maximal_count_unavailable_reason':'Pinned upstream sequential runner removes individual reports after merging; no raw count inferred.',
            'strict_fixture_DRC':'PASS' if complete and not counts and execution['returncode']==0 else 'FAIL' if complete else 'INCOMPLETE',
            'whole_chip_signoff':False}
    geometry={}
    for name,c in g['cells'].items():
        if not c['official_pin_metal_checks']:raise ValueError('No pin shape checks')
        covered=all(x['covered'] and x['uncovered_um2']==0 for x in c['official_pin_metal_checks'])
        geometry[name]={'pin_rectangles':len(c['official_pin_metal_checks']),'all_pin_rectangles_covered':covered,
            'pin_label_names_complete':c['pin_label_names_complete'],'same_lef_size':c['same_lef_size'],
            'same_lef_pin_shapes':c['same_lef_pin_shapes'],'changed_polygon_layers':len(c['changed_polygon_layers']),
            'export_geometry_equal':c['export_geometry_equal'],'PG_connectivity':'NOT_PROVEN_by_overlap',
            'label_position_scope':'Macro pin label names only; label coordinates are not used as connectivity proof.'}
    return {'schema_version':'1.0.0','classification':'official_IO_physical_fixture_audit_not_signoff','run_id':run.name,
        'audit_result':'PASS' if all(a['execution_complete'] for a in arms.values()) and all(g['all_pin_rectangles_covered'] and g['pin_label_names_complete'] and g['export_geometry_equal'] for g in geometry.values()) else 'FAIL',
        'evidence_sha256':verified,'raw_manifest_preserved':True,
        'raw_manifest_parser_limitation':'Runner expected parallel per-table files; actual --mp 1 executes one main plus density/antenna/maximal. Independent audit checks all switches, completion, antenna categories and terminal state.',
        'geometry':geometry,'DRC':arms,'strict_LVS':'NOT_RUN_unresolved_lower_leaf_gate',
        'current_chip_modified':False,'source_pdk_modified':False,'public_rule_signoff':False,'foundry_signoff':False,
        'interpretation':'All six isolated-macro markers are retained global density failures; zero other merged markers does not prove assembled ring/chip DRC or PG/LVS.',
        'migration_qualified':False}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];report=audit(root,root/'runs'/a.run_id)
    with a.output.open('x') as f:json.dump(report,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('evidence_sha256','DRC','geometry')},indent=2))
