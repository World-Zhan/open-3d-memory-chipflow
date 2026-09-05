#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read only four small leaf LVSDB results; preserve failures and exact port scope."""
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, '/work/scripts')
from analyze_small_lvsdb import analyze, enforce_size_limit

root = Path('/output')
manifest = json.loads((root/'manifest.json').read_text())
records = {step['name']:step for step in manifest['steps']}
cases = []
for arm in ('control','upstream_purge_fix'):
    for cell in ('sg13g2_DCNDiode','sg13g2_DCPDiode'):
        folder = root/arm/cell
        db = folder/(cell+'.lvsdb')
        raw = folder/(cell+'_extracted.cir')
        log_path = folder/(cell+'.log')
        run = records[arm+'-'+cell]
        result = {'arm':arm,'cell':cell,'runner_returncode':run['returncode']}
        if not all(path.exists() for path in (db,raw,log_path)):
            result.update(status='incomplete',lvs_passed=False)
            cases.append(result); continue
        enforce_size_limit(db, 2*1024*1024)
        xref = analyze(db, 50)
        with (folder/'cross_reference.json').open('x') as f:
            json.dump(xref,f,indent=2,sort_keys=True); f.write('\n')
        netlist = raw.read_text()
        ports = re.search(r'^\.SUBCKT\s+'+cell+r'\s+(.*)$', netlist, re.M | re.I)[1].split()
        log = log_path.read_text()
        circuit_status = xref['summary']['circuit_status_counts']
        strict = 'deep  mode is enabled.' in log and 'strict port mode.' in log and 'flag_missing_ports enabled' in log
        # A new candidate only passes with actual nonempty circuit comparison, exact ports and explicit match output.
        passed = (run['returncode'] == 0 and strict and set(ports) == {'anode','cathode','guard'}
                  and len(ports)==3 and circuit_status == {'Match':1}
                  and "Netlists don't match" not in log and 'Netlists match' in log)
        result.update(status='PASS' if passed else 'FAIL',lvs_passed=passed,
            strict_mode_observed=strict, extracted_ports=ports,
            devices=[line for line in netlist.splitlines() if re.match(r'^[DRMXQ]\S*\s',line)],
            cross_reference_summary=xref['summary'],
            option_evidence_lines=[line for line in log.splitlines() if re.search(r'RF MOS|purge|SIMPLIFY|DISABLE_TAP|IMPLICIT|IGNORE_TOP|flag_missing|strict port|Netlists',line)],
            artifact_sha256={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (db,raw,log_path,folder/'cross_reference.json')})
        cases.append(result)
result={'schema_version':'1.0.0','classification':'two_leaf_strict_lvs_supported_purge_fix_ab_not_chip_signoff',
        'cases':cases,'both_fixed_leaves_pass':all(case['lvs_passed'] for case in cases if case['arm']=='upstream_purge_fix'),
        'pdk_sources_modified':False,'full_chip_lvs_performed':False,'public_rule_signoff':False}
with (root/'analysis/summary.json').open('x') as f:
    json.dump(result,f,indent=2,sort_keys=True); f.write('\n')
print(json.dumps([{'arm':r['arm'],'cell':r['cell'],'status':r['status'],'ports':r.get('extracted_ports')} for r in cases]))
