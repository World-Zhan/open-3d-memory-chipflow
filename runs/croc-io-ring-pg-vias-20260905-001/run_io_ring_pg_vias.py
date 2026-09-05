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
RUN = ROOT / 'runs/croc-io-ring-pg-vias-20260905-001'
IMAGE = 'sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


RUN.mkdir()
script = STAGE / 'probe_io_ring_pg_vias.py'
ast.parse(script.read_text())
report_script = ROOT / 'reports/bondpad/probe_io_ring_pg_vias.py'
if report_script.exists():
    raise FileExistsError(report_script)
shutil.copy2(script, report_script)
shutil.copy2(script, RUN / script.name)
shutil.copy2(ROOT / 'reports/bondpad/probe_io_ring_pg.py', RUN / 'probe_io_ring_pg.py')
shutil.copy2(Path(__file__), RUN / 'run_io_ring_pg_vias.py')
command = ['docker', 'run', '--rm', '--name', RUN.name, '--cpus', '2', '--memory', '4g',
           '--user', '1000:1000', '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1',
           '--entrypoint', '/usr/bin/timeout', '-v', f'{ROOT}:/work:ro', '-v', f'{RUN}:/output:rw',
           IMAGE, '--signal=TERM', '--kill-after=3s', '180s', 'python3', '/output/probe_io_ring_pg_vias.py']
started = now()
with (RUN / 'tool.log').open('w') as log:
    completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
manifest = {'classification': 'read_only_PG_seeded_metal_via_graph_not_signoff', 'command': command,
            'started_at': started, 'finished_at': now(), 'returncode': completed.returncode,
            'limits': {'cpus': 2, 'memory_gb': 4, 'container_internal_timeout_seconds': 180},
            'artifacts_sha256': {p.name: sha(p) for p in RUN.iterdir() if p.is_file()}}
(RUN / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
print((RUN / 'tool.log').read_text())
print(json.dumps({'run': str(RUN), 'returncode': completed.returncode}))
