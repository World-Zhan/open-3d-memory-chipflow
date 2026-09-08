#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path('/home/james_zhan/projects/open-3d-memory-chipflow')
STAGE=Path('/mnt/c/Users/James Zhan/.codex/visualizations/2026/09/05/01a06f53-62f0-7bb1-93a3-51fd2e527fa7')
RUN=ROOT/'runs/croc-lvs-dcn-stage-control-check-20260909-001'
IMAGE='sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
RUN.mkdir()
for n in ('check_lvs_stage_control.py','run_lvs_stage_control_check.py'):
    shutil.copyfile(STAGE/n,RUN/n)
    shutil.copyfile(STAGE/n,ROOT/'reports/lvs'/n)
cmd=['docker','run','--rm','--name',RUN.name,'--cpus','1','--memory','1g','--user','1000:1000',
     '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/usr/bin/timeout',
     '-v',str(ROOT)+':/work:ro','-v',str(RUN)+':/output:rw',IMAGE,'--kill-after=3s','30s',
     '/bin/bash','-lc','python3 /output/check_lvs_stage_control.py']
m={'command':cmd,'started_at':datetime.now(timezone.utc).isoformat(),'classification':'read_only_lvsdb_audit_no_eda',
   'script_sha256':{n:sha(RUN/n) for n in ('check_lvs_stage_control.py','run_lvs_stage_control_check.py')},
   'analyzer_sha256':sha(ROOT/'scripts/analyze_small_lvsdb.py')}
with (RUN/'tool.log').open('x') as log:
    try: m['returncode']=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=50).returncode
    except subprocess.TimeoutExpired:
        m['returncode']=None;m['outer_timeout']=True
        subprocess.run(['docker','kill',RUN.name],stdout=log,stderr=subprocess.STDOUT,timeout=10)
m['finished_at']=datetime.now(timezone.utc).isoformat()
m['output_sha256']={p.name:sha(p) for p in RUN.iterdir() if p.is_file()}
(RUN/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
print((RUN/'tool.log').read_text())
