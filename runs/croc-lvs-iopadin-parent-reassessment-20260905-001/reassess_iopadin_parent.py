#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/home/james_zhan/projects/open-3d-memory-chipflow')
PDK = ROOT/'upstream/ihp-open-pdk'
PIN = '331c00484213b13414777eec1336ef5c29b969bd'
OLD = ROOT/'runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-diagnostic-20260829-001'
CASE = OLD/'sg13g2_IOPadIn'
RUN = ROOT/'runs/croc-lvs-iopadin-parent-reassessment-20260905-001'
IMAGE = 'sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
now = lambda: datetime.now(timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(['git','-C',str(PDK),*args], text=True).strip()


scope_paths = ['ihp-sg13g2/libs.ref/sg13g2_io/gds/sg13g2_io.gds', 'ihp-sg13g2/libs.ref/sg13g2_io/cdl/sg13g2_io.cdl', 'ihp-sg13g2/libs.tech/klayout/tech/lvs']
assert not git('status','--porcelain','--',*scope_paths)
subprocess.run(['git','-C',str(PDK),'diff','--exit-code',PIN,'--',*scope_paths], check=True)
summary = json.loads((OLD/'summary.json').read_text())
case = next(c for c in summary['cases'] if c['top_cell']=='sg13g2_IOPadIn')
assert summary['ihp_pdk_commit']==PIN and summary['container_digest']==IMAGE
assert case['runner_returncode']==0 and case['status']=='FAIL'
assert case['observed_log_options']['strict_port_mode'] and case['observed_log_options']['simplify_enabled']
assert case['requested_options']['run_mode']=='deep' and not case['requested_options']['ignore_top_ports_mismatch']
assert case['requested_options']['implicit_nets'] is None
log = (CASE/'sg13g2_io.log').read_text()
assert "ERROR : Netlists don't match" in log and 'Starting Taps EXTRACTION' in log
assert '--topcell=sg13g2_IOPadIn --run_mode=deep' in (CASE/'command.txt').read_text()
RUN.mkdir()
shutil.copy2(ROOT/'scripts/analyze_small_lvsdb.py', RUN/'analyze_small_lvsdb.py')
shutil.copy2(CASE/'sg13g2_io_extracted.cir', RUN/'historical_iopadin_extracted.cir')
shutil.copy2(CASE/'command.txt', RUN/'historical_command.txt')
shutil.copy2(Path(__file__), RUN/'reassess_iopadin_parent.py')
(RUN/'historical_case.json').write_text(json.dumps(case, indent=2, sort_keys=True)+'\n')
sources = [OLD/'summary.json', CASE/'command.txt', CASE/'sg13g2_io.log', CASE/'runner-console.log', CASE/'sg13g2_io_extracted.cir', CASE/'sg13g2_io.lvsdb', ROOT/'scripts/analyze_small_lvsdb.py']
sources += [PDK/p for p in scope_paths[:2]]
hashes = {str(p.relative_to(ROOT)):sha(p) for p in sources}
objects = {p: git('rev-parse',PIN+':'+p) for p in scope_paths}
command = ['docker','run','--rm','--name',RUN.name,'--cpus','2','--memory','4g','--user','1000:1000',
           '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/usr/bin/timeout','-v',f'{ROOT}:/work:ro','-v',f'{RUN}:/output:rw',IMAGE,
           '--signal=TERM','--kill-after=3s','90s','python3','/output/analyze_small_lvsdb.py','--lvsdb','/work/'+str((CASE/'sg13g2_io.lvsdb').relative_to(ROOT)),
           '--output','/output/cross_reference.json','--max-bytes','4194304','--sample-limit','12']
started = now()
with (RUN/'tool.log').open('w') as stream:
    done = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
manifest = {'classification':'read_only_reassessment_of_existing_identical_strict_parent_LVS', 'new_LVS_execution':False,
            'historical_LVS_run':str(CASE.relative_to(ROOT)), 'historical_LVS_runner_returncode':0,'historical_LVS_result':'FAIL',
            'exact_requested_topcell':'sg13g2_IOPadIn','official_CDL_and_GDS_unchanged_from_pinned_commit':True,
            'pdk_commit':PIN,'pinned_git_objects':objects,'current_PDK_worktree_clean_for_referenced_sources':True,
            'source_sha256':hashes,'source_hashes_unchanged':hashes=={str(p.relative_to(ROOT)):sha(p) for p in sources},
            'command':command,'started_at':started,'finished_at':now(),'returncode':done.returncode,
            'limits':{'cpus':2,'memory_gb':4,'container_internal_timeout_seconds':90},
            'artifacts_sha256':{p.name:sha(p) for p in RUN.iterdir() if p.is_file()}}
(RUN/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
print((RUN/'tool.log').read_text())
if (RUN/'cross_reference.json').exists():
    data = json.loads((RUN/'cross_reference.json').read_text())
    print(json.dumps(data['summary']))
print(json.dumps({'run':str(RUN),'analysis_returncode':done.returncode,'new_LVS_execution':False}))
