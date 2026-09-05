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
STAGE = Path('/mnt/c/Users/James Zhan/.codex/visualizations/2026/09/05/01a06f53-62f0-7bb1-93a3-51fd2e527fa7')
RUN = ROOT/'runs/croc-lvs-electrode-parent-geometry-20260905-001'
IMAGE = 'sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
now = lambda: datetime.now(timezone.utc).isoformat()
RUN.mkdir()
script = STAGE/'probe_iopadin_electrodes.py'
ast.parse(script.read_text())
target = ROOT/'reports/lvs/probe_iopadin_electrodes.py'
if target.exists():
    raise FileExistsError(target)
shutil.copy2(script, target)
shutil.copy2(script, RUN/script.name)
for name in ('probe_io_ring_pg.py', 'probe_io_ring_pg_vias.py'):
    shutil.copy2(ROOT/'reports/bondpad'/name, RUN/name)
shutil.copy2(Path(__file__), RUN/'run_iopadin_electrodes.py')
pdk = ROOT/'upstream/ihp-open-pdk/ihp-sg13g2'
sources = [ROOT/'upstream/croc/technology/gds/sg13g2_io.gds', pdk/'libs.ref/sg13g2_io/gds/sg13g2_io.gds', pdk/'libs.ref/sg13g2_io/cdl/sg13g2_io.cdl', target]
sources += list((pdk/'libs.tech/klayout/tech/lvs').glob('*.lvs'))
sources += list((pdk/'libs.tech/klayout/tech/lvs/rule_decks').glob('*.lvs'))
before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
command = ['docker','run','--rm','--name',RUN.name,'--cpus','2','--memory','4g','--user','1000:1000',
           '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/usr/bin/timeout',
           '-v',f'{ROOT}:/work:ro','-v',f'{RUN}:/output:rw',IMAGE,'--signal=TERM','--kill-after=3s','180s',
           'python3','/output/probe_iopadin_electrodes.py']
manifest = {'classification':'readonly_parent_electrode_and_guard_geometry_not_LVS', 'run_id':RUN.name,
            'repo_head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
            'command':command,'started_at':now(),'source_sha256':before,
            'limits':{'cpus':2,'memory_gb':4,'container_internal_timeout_seconds':180}}
(RUN/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
with (RUN/'tool.log').open('w') as log:
    done = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
manifest.update(returncode=done.returncode,finished_at=now(),source_hashes_unchanged=before=={str(p.relative_to(ROOT)):sha(p) for p in sources},
                artifacts_sha256={p.name:sha(p) for p in RUN.iterdir() if p.is_file() and p.name!='manifest.json'})
(RUN/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
print((RUN/'tool.log').read_text())
print(json.dumps({'run':str(RUN),'returncode':done.returncode,'source_hashes_unchanged':manifest['source_hashes_unchanged']}))
