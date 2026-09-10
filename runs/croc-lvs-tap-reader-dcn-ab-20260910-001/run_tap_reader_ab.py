#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded exact tap-X reader regression and one optional strict DCN A/B."""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'runs/croc-lvs-leaf-purge-ab-20260905-001'
STAGE = ROOT / 'runs/croc-lvs-dcn-stage-snapshots-20260909-001'
REL = Path('ihp-sg13g2/libs.tech/klayout/tech/lvs')
READER = REL / 'rule_decks/custom_reader.lvs'
IMAGE = 'sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
CELL = 'sg13g2_DCNDiode'
FILES = ('run_tap_reader_ab.py', 'tap_reader_adapter.rb', 'tap_reader_regression.rb')

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def save(p, value): p.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')
def hashes(paths): return {str(p.relative_to(ROOT)): sha(p) for p in paths}
def all_files(p): return sorted(q for q in p.rglob('*') if q.is_file())

def cases():
    def single(line, extra=''):
        return '* tap X reader regression\n'+extra+'.subckt TOP T W Z\n'+line+'\n.ends TOP\n.end\n'
    definitions = [
        ('ptap_si', 'Xone T W ptap1 A=141.253p P=47.54u'),
        ('ntap_mixed', 'Xtwo W T nTaP1 a=2e-12 p=6e-6'),
        ('tap_dimensions', 'Xthree T W PTAP1 W=2u L=3u'),
        ('tap_perim', 'Xfour T W NTAP1 A=6p PERIM=10u'),
        ('tap_r', 'Rfive T W 0 MODEL=PTAP1 A=141.253p P=47.54u'),
        ('ordinary_r', 'Rplain T W 10k R=10k'),
        ('unknown_defined', 'Xchild T W MY_CHILD'),
        ('unknown_near_name', 'Xchild T W PTAP1_EXTRA A=1p P=4u'),
        ('bad_one_terminal', 'Xbad T PTAP1 A=1p P=4u'),
        ('bad_three_terminals', 'Xbad T W Z PTAP1 A=1p P=4u'),
        ('bad_missing_area', 'Xbad T W PTAP1 P=4u'),
        ('bad_missing_perimeter', 'Xbad T W PTAP1 A=1p'),
        ('bad_zero_area', 'Xbad T W PTAP1 A=0 P=4u'),
        ('bad_negative_perimeter', 'Xbad T W PTAP1 A=1p P=-4u'),
        ('bad_non_numeric', 'Xbad T W PTAP1 A=UNKNOWN P=4u'),
        ('bad_multiplier', 'Xbad T W PTAP1 A=1p P=4u M=2'),
        ('bad_model_override', 'Xbad T W PTAP1 A=1p P=4u MODEL=NTAP1'),
        ('bad_incomplete_dimensions', 'Xbad T W PTAP1 W=2u'),
        ('bad_conflicting_perimeter', 'Xbad T W PTAP1 A=1p P=4u PERIM=5u'),
        ('bad_scale', 'Xbad T W PTAP1 A=1p P=4u'),
    ]
    result = []
    for key, line in definitions:
        extra = '.options scale=1e-6\n' if key == 'bad_scale' else ''
        if key == 'unknown_defined':
            extra += '.subckt MY_CHILD A B\nRchild A B 3k R=3k\n.ends MY_CHILD\n'
        result.append({'id': key, 'spice': single(line, extra)})
    return result

def top(record):
    return next(c for c in record['inventory'] if c['name'] == 'TOP')

def evaluate_reader(control, candidate):
    """Semantic assertions, intentionally independent of tool exit status."""
    expected = {c['id'] for c in cases()}
    if set(control['cases']) != expected or set(candidate['cases']) != expected:
        raise ValueError('missing or unexpected reader cases')
    a, b = control['cases'], candidate['cases']
    passed = []
    def require(condition, message):
        if not condition: raise ValueError(message)
        passed.append(message)
    for case, cls, terms, area, perimeter in [
        ('ptap_si', 'PTAP1', {'TIE':'T','WELL':'W'},141.253,47.54),
        ('ntap_mixed','NTAP1',{'TIE':'W','WELL':'T'},2,6),
        ('tap_dimensions','PTAP1',{'TIE':'T','WELL':'W'},6,10),
        ('tap_perim','NTAP1',{'TIE':'T','WELL':'W'},6,10),
    ]:
        require(b[case]['status']=='read', case+' read')
        c = top(b[case]); require(len(c['devices'])==1 and not c['subcircuits'],case+' single device')
        d = c['devices'][0]
        require(d['class']==cls and d['terminals']==terms,case+' exact class and terminal order')
        require(set(d['parameters'])=={'A','P'} and abs(d['parameters']['A']-area)<1e-9 and
                abs(d['parameters']['P']-perimeter)<1e-9,case+' SI to um units')
        require(a[case]['status']=='read' and not top(a[case])['devices'] and
                len(top(a[case])['subcircuits'])==1,case+' control remains unresolved subcircuit')
    for case in ('tap_r','ordinary_r','unknown_defined','unknown_near_name'):
        require(a[case]['status']=='read' and a[case]==b[case],case+' unchanged')
    require(top(b['ordinary_r'])['devices'][0]['parameters']['R']==10000,'ordinary resistor value 10k preserved')
    tap = top(b['tap_r'])['devices'][0]
    require(tap['terminals']=={'TIE':'T','WELL':'W'} and abs(tap['parameters']['A']-141.253)<1e-9 and
            abs(tap['parameters']['P']-47.54)<1e-9,'existing R tap agrees with X units and polarity')
    require(len(top(b['unknown_defined'])['subcircuits'])==1 and len(b['unknown_defined']['inventory'])==2,
            'unknown defined hierarchy preserved')
    require(len(top(b['unknown_near_name'])['subcircuits'])==1 and not top(b['unknown_near_name'])['devices'],
            'near-name X not captured as tap')
    for case in sorted(expected):
        if case.startswith('bad_'):
            require(b[case]['status']=='rejected',case+' rejected')
    return {'result':'PASS','case_count':len(expected),'semantic_assertions':passed,
            'negative_cases':sum(c.startswith('bad_') for c in expected)}

def run_container(folder, name, args):
    cmd = ['docker','run','--name',name,'--cpus','2','--memory','4g','--user','1000:1000',
           '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/usr/bin/timeout',
           '-v',str(ROOT)+':/work:ro','-v',str(folder)+':/output:rw',IMAGE,
           '--signal=TERM','--kill-after=3s','60s','/bin/bash','-lc','ulimit -c 0\n'+shlex.join(args)]
    record={'command':cmd,'started_at':now(),'inner_timeout_seconds':60,'outer_timeout_seconds':85}
    with (folder/'tool.log').open('x') as log:
        try:
            result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=85)
            record['returncode']=result.returncode
        except subprocess.TimeoutExpired:
            record['returncode']=None;record['outer_timeout']=True
            subprocess.run(['docker','kill',name],stdout=log,stderr=subprocess.STDOUT,timeout=10)
        inspect=subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=10)
        (folder/'terminal_observation.json').write_text(inspect.stdout)
        record['inspect_returncode']=inspect.returncode
        if inspect.returncode==0:
            record['terminal_state']=json.loads(inspect.stdout)[0]['State']
            if not record['terminal_state']['Running']:
                cleanup=subprocess.run(['docker','rm',name],stdout=log,stderr=subprocess.STDOUT,timeout=10)
                record['cleanup_returncode']=cleanup.returncode
    record['finished_at']=now()
    save(folder/'execution.json',record)
    return record

def require_terminal(record):
    state=record.get('terminal_state',{})
    if record.get('returncode')!=0 or state.get('Running') is not False or state.get('ExitCode')!=0 or state.get('OOMKilled') is not False:
        raise ValueError('unhealthy terminal execution')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['reader','leaf'],required=True)
    parser.add_argument('--run-id',required=True);parser.add_argument('--reader-run')
    args=parser.parse_args()
    if '/' in args.run_id or not args.run_id.startswith('croc-lvs-tap-reader-'):
        raise ValueError('invalid run ID')
    run=ROOT/'runs'/args.run_id;run.mkdir()
    tools_dir=ROOT/'reports/lvs'
    for file in FILES: shutil.copyfile(tools_dir/file,run/file)
    sources=[tools_dir/file for file in FILES]
    if args.phase=='reader':
        deck_source=SOURCE/'decks/control'
        sources += all_files(deck_source)
    else:
        if not args.reader_run: raise ValueError('reader run required')
        reader=ROOT/'runs'/args.reader_run
        gate=json.loads((reader/'manifest.json').read_text())
        if gate.get('reader_regression',{}).get('result')!='PASS' or gate.get('source_hashes_unchanged') is not True:
            raise ValueError('reader gate absent')
        for rel,digest in gate['output_sha256'].items():
            if sha(reader/rel)!=digest: raise ValueError('reader gate output hash changed')
        for rel,digest in gate['source_sha256'].items():
            if sha(ROOT/rel)!=digest: raise ValueError('reader gate source hash changed')
        if sha(reader/'tap_reader_adapter.rb')!=sha(tools_dir/'tap_reader_adapter.rb'):
            raise ValueError('adapter differs from reader gate')
        sources += [reader/'manifest.json']
        deck_source=STAGE/'deck'
        sources += all_files(deck_source)+all_files(STAGE/'inputs')
    source_hashes=hashes(sources)
    manifest={'schema_version':1,'run_id':args.run_id,'phase':args.phase,'image':IMAGE,
              'classification':'reader_adapter_regression_not_chip_signoff' if args.phase=='reader' else 'strict_single_DCN_reader_adapter_AB_not_signoff',
              'source_sha256':source_hashes,'started_at':now(),
              'source_pdk_modified':False,'parent_lvs_performed':False,'full_chip_lvs_performed':False,
              'strictness':json.loads((SOURCE/'manifest.json').read_text())['strictness']}
    save(run/'manifest.json',manifest)
    for arm in ('control','candidate'):
        out=run/arm;out.mkdir();shutil.copytree(deck_source,out/'deck')
        if arm=='candidate':
            reader=out/'deck'/READER;before=reader.read_text()
            after=before+'\n'+(tools_dir/'tap_reader_adapter.rb').read_text()
            reader.write_text(after)
            patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                         fromfile='a/'+str(READER),tofile='b/'+str(READER)))
            (run/'tap_reader_adapter.patch').write_text(patch)
        if args.phase=='reader':
            (out/'inputs').mkdir();(out/'results').mkdir();save(out/'cases.json',cases())
            shutil.copyfile(tools_dir/'tap_reader_regression.rb',out/'regression.rb')
            command=['klayout','-b','-r','/output/regression.rb']
        else:
            shutil.copytree(STAGE/'inputs',out/'inputs');(out/'snapshots').mkdir();(out/'result').mkdir()
            command=['python3','/output/deck/'+str(REL/'run_lvs.py'),
                     '--layout=/output/inputs/'+CELL+'.gds','--netlist=/output/inputs/'+CELL+'.cdl',
                     '--run_dir=/output/result','--topcell='+CELL,'--run_mode=deep']
        manifest[arm]=run_container(out,args.run_id+'-'+arm,command)
        manifest['output_sha256']={str(p.relative_to(run)):sha(p) for p in all_files(run) if p.name!='manifest.json'}
        save(run/'manifest.json',manifest)
        require_terminal(manifest[arm])
    if args.phase=='reader':
        manifest['reader_regression']=evaluate_reader(*[json.loads((run/a/'results.json').read_text()) for a in ('control','candidate')])
    else:
        manifest['reader_gate_run']=args.reader_run
    manifest['source_hashes_unchanged']=all(sha(ROOT/p)==h for p,h in source_hashes.items())
    if not manifest['source_hashes_unchanged']: raise ValueError('source hash changed')
    manifest['finished_at']=now()
    save(run/'manifest.json',manifest)
    print(json.dumps({'run':str(run),'phase':args.phase,'source_hashes_unchanged':True,
                      'reader_regression':manifest.get('reader_regression')},indent=2))

if __name__=='__main__':main()
