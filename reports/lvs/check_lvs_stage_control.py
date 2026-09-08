#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only bounded LVSDB comparison against the historical DCN control."""
import importlib.util
import json
from pathlib import Path
import pya

root = Path('/work')
observed = root/'runs/croc-lvs-dcn-stage-snapshots-20260909-001'
control = root/'runs/croc-lvs-leaf-purge-ab-20260905-001/control/sg13g2_DCNDiode'
spec = importlib.util.spec_from_file_location('analyze', root/'scripts/analyze_small_lvsdb.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
paths = {'control':control/'sg13g2_DCNDiode.lvsdb','observed':observed/'result/sg13g2_DCNDiode.lvsdb'}
records = {}
netlists = {}
for label, path in paths.items():
    module.enforce_size_limit(path, 1024*1024)
    records[label] = module.analyze(path, 100)
    database = pya.LayoutVsSchematic(); database.read(str(path))
    netlists[label] = {'layout':database.netlist().to_s(), 'schematic':database.reference.to_s()}
    for side, data in netlists[label].items():
        Path('/output/'+label+'_'+side+'.txt').write_text(data)
report = {'schema_version':1, 'read_only':True, 'max_lvsdb_bytes':1024*1024,
          'source_sha256':{str(p.relative_to(root)):module.sha256_file(p) for p in paths.values()},
          'cross_reference_identical':records['control']==records['observed'],
          'final_netlists_identical':netlists['control']==netlists['observed'],
          'control':records['control'], 'observed':records['observed'],
          'historical_json_matches_reloaded_control':records['control']==json.loads((control/'cross_reference.json').read_text()),
          'result':'FAIL'}
Path('/output/cross_reference.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('control','observed')},indent=2))
assert report['cross_reference_identical'] and report['final_netlists_identical']
assert report['historical_json_matches_reloaded_control']
assert records['observed']['summary']['circuit_status_counts'] == {'NoMatch':1}
