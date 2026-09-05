#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Replay the terminal-crashed maximal DRC task in supported flat mode."""
import argparse,json,os,re,shlex,subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
from run_io_ring_floorplan import IMAGE,sha,now,write


def run(root,rid):
    if not re.fullmatch(r'croc-io-ring-maximal-flat-[a-zA-Z0-9_-]+',rid):raise ValueError('Independent run ID required')
    prior=root/'runs/croc-io-ring-drc-20260905-001'
    pm=json.loads((prior/'manifest.json').read_text())
    if pm['arms'][0]['returncode']!=1:raise ValueError('Expected archived runner failure')
    for rel,v in pm['source_sha256'].items():
        if sha(root/rel)!=v:raise ValueError('Prior source changed')
    logs=prior/'io_ring_sealed/tool.log'
    if sha(logs)!=pm['arms'][0]['outputs_sha256']['tool.log']:raise ValueError('Prior log changed')
    text=logs.read_text()
    matches=re.findall(r"sg13g2_maximal generated an exception: Command '(.*?)' returned non-zero exit status 11\.",text,re.S)
    if len(matches)!=1:raise ValueError('Expected exactly one maximal signal-11 command')
    original=shlex.split(matches[0])
    if original[0]!='klayout' or original[original.index('-r')+1]!='/work/upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_maximal.drc':
        raise ValueError('Unexpected command/deck')
    out=root/'runs'/rid;out.mkdir(exist_ok=False)
    args=[];changes=[]
    for item in original:
        replacement={'threads=4':'threads=1','run_mode=deep':'run_mode=flat',
          'report=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.lyrdb':'report=/output/maximal.lyrdb',
          'log=/output/io_ring_sealed_io_ring_sealed_sg13g2_maximal.log':'log=/output/maximal.log'}.get(item,item)
        if replacement!=item:changes.append([item,replacement])
        args.append(replacement)
    if len(changes)!=4:raise ValueError('Unexpected replay argument modifications')
    command=['docker','run','--rm','--name',rid,'--cpus','2','--memory','8g','--user',f'{os.getuid()}:{os.getgid()}',
       '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/bin/bash','-v',f'{root}:/work:ro','-v',f'{out}:/output:rw',IMAGE,'-lc',
       shlex.join(['timeout','--signal=TERM','--kill-after=15s','600s',*args])]
    m={'run_id':rid,'classification':'single_failed_rule_task_replay_not_full_chip_signoff','started_at':now(),
      'prior_run':prior.name,'source_sha256':dict(pm['source_sha256']),
      'original_command':original,'changed_arguments':changes,'command':command,
      'all_rule_enable_disable_arguments_unchanged':True,'public_rule_signoff':False}
    for p in (prior/'manifest.json',prior/'audit.json',logs,root/'scripts/replay_io_ring_maximal.py',prior/'inputs/io_ring_sealed.gds'):
        m['source_sha256'][str(p.relative_to(root))]=sha(p)
    write(out/'manifest.json',m)
    try:
        with (out/'tool.log').open('x') as f:rc=subprocess.run(command,cwd=root,stdout=f,stderr=subprocess.STDOUT,timeout=640).returncode
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','stop','--time','5',rid],stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=15);rc=124
    markers=None
    if (out/'maximal.lyrdb').exists():markers=len(ET.parse(out/'maximal.lyrdb').findall('.//items/item'))
    log=(out/'tool.log').read_text(errors='replace')
    completed=rc==0 and markers is not None and 'DRC run for maximum ruleSet completed in' in log and not re.search(r'(?m)^ERROR:|Signal number:|Traceback|Killed',log)
    m.update(returncode=rc,status='completed' if completed else 'failed',execution_complete=completed,
       maximal_raw_markers=markers,finished_at=now(),source_hashes_unchanged=all(sha(root/p)==v for p,v in m['source_sha256'].items()),
       outputs_sha256={p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'})
    write(out/'manifest.json',m)
    print(json.dumps({k:m[k] for k in ('run_id','returncode','status','maximal_raw_markers','execution_complete')}),flush=True)
    return 0 if completed else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True)
    a=p.parse_args();raise SystemExit(run(Path(__file__).resolve().parents[1],a.run_id))
