#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only reassessment of complete rule execution and isolated fixture DRC."""
import argparse
from collections import Counter
import hashlib,json,re
from pathlib import Path
import xml.etree.ElementTree as ET

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def antenna_categories():
    metals=['Metal1','Metal2','Metal3','Metal4','Metal5','TopMetal1','TopMetal2']
    vias=['Via1','Via2','Via3','Via4','TopVia1','TopVia2']
    return {'Ant.a','Ant.c','Ant.g','Ant.h','Ant.i'} | {f'Ant.{r}_{m}' for r in ('b','e') for m in metals} | {f'Ant.{r}_{v}' for r in ('d','f') for v in vias}
def antenna_complete(log,categories):
    # The pinned antenna deck ends at Ant.i and has no "completed in" log.
    # Require all 31 merged output categories, its final rule and no task error.
    errors=re.search(r'(?im)^(?:ERROR:|Traceback)|generated an exception|CalledProcessError|std::bad_alloc|Killed',log)
    return antenna_categories().issubset(categories) and 'Executing rule Ant.i' in log and not errors
def analyze(root,run):
    path=run/'manifest.json'
    manifest=json.loads(path.read_text())
    for rel,expected in manifest['source_sha256'].items():
        if sha(root/rel)!=expected:raise ValueError('Source hash changed: '+rel)
    result={'schema_version':'1.0.0','source_manifest_sha256':sha(path),'run_id':run.name,
            'classification':'isolated_fixture_drc_not_chip_signoff','raw_manifest_preserved':True,
            'note':'Original runner expected a completion line absent from the pinned antenna deck; verify all 31 categories and terminal Ant.i instead.',
            'public_rule_signoff':False,'full_chip_drc_lvs_performed':False,'arms':[]}
    for arm in manifest['arms']:
        folder=run/arm['name']
        for rel,expected in arm['outputs_sha256'].items():
            if sha(folder/rel)!=expected:raise ValueError('Output hash changed: '+rel)
        reports=list(folder.glob('*_full.lyrdb'))
        if len(reports)!=1:raise ValueError('Exactly one merged full report is required')
        tree=ET.parse(reports[0])
        categories={e.findtext('name'):e.findtext('description','') for e in tree.findall('.//categories/category')}
        counts=Counter((e.findtext('category') or '').strip("'") for e in tree.findall('.//items/item'))
        completion=dict(arm['rule_task_completion'])
        ant=list(folder.glob('*_antenna.log'))
        completion['antenna']=len(ant)==1 and antenna_complete(ant[0].read_text(errors='replace'),categories)
        tool=(folder/'tool.log').read_text(errors='replace')
        errors=re.search(r'(?im)^(?:ERROR:|Traceback)|generated an exception|CalledProcessError|std::bad_alloc|Killed',tool)
        execution=all(completion.values()) and not errors and 'Total DRC Run time:' in tool
        density={name:count for name,count in counts.items() if 'density' in categories.get(name,'').lower()}
        other={name:count for name,count in counts.items() if name not in density}
        result['arms'].append({'name':arm['name'],'runner_returncode':arm['returncode'],
           'rule_execution_complete':bool(execution),'rule_tasks':len(completion),
           'rule_task_completion':completion,'antenna_category_count':len(antenna_categories()&categories.keys()),
           'merged_markers':sum(counts.values()),'merged_marker_counts':dict(sorted(counts.items())),
           'density_markers':sum(density.values()),'density_marker_counts':density,
           'non_density_markers':sum(other.values()),'non_density_marker_counts':other,
           'fixture_drc_passed':bool(execution and not counts and arm['returncode']==0),
           'full_report_sha256':sha(reports[0])})
    result['ppa']={'whole_chip_layout_modified':False,'new_whole_chip_ppa':False,
                   'baseline':'reports/ppa/croc-ppa-rcx-20260905-001.json',
                   'scope':'Fixture density is measured on macro bounding boxes; it is not chip density. No density rule was disabled.'}
    return result
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    data=analyze(args.root.resolve(),args.run.resolve())
    with args.output.open('x') as f:json.dump(data,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({a['name']:{k:a[k] for k in ('rule_execution_complete','rule_tasks','merged_markers','density_markers','non_density_markers','fixture_drc_passed')} for a in data['arms']}))
