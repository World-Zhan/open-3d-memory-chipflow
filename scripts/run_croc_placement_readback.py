#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read original/new placed ODB in independent STA processes with identical setup."""
import argparse
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from run_io_ring_floorplan import IMAGE, now, sha, write
from run_io_ring_maximal_diagnostic import observe
from collect_croc_ppa import parse_area, parse_power, parse_clocks
from collect_croc_evidence import final_timing, timing_checks

TCL=r'''
source scripts/startup.tcl
set_thread_count 2
read_db /output/inputs/02_croc.placed.odb
read_sdc /output/inputs/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
estimate_parasitics -placement
check_placement -verbose
check_setup -verbose > /output/constraints.rpt
help report_power > /output/power_command_help.rpt
report_metrics fresh_placed
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical_violators.rpt
report_checks -path_delay min -slack_max 0 -format full_clock_expanded -fields {slew cap fanout} > /output/hold_violators.rpt
write_sdc /output/readback.sdc
set f [open /output/core_pg.tsv w]
puts $f "net\ttcl_catch_code\tmessage"
foreach net {VDD VSS} {
    puts "FRESH_PLACED_PG_BEGIN $net"
    set code [catch {check_power_grid -net $net -error_file /output/pg_errors_${net}.rpt} message]
    puts $f "$net\t$code\t[string map [list \n { } \t { }] $message]"
    puts "FRESH_PLACED_PG_END $net catch=$code result=$message"
}
close $f
puts {FRESH_PLACED_READBACK_COMPLETE}
'''


def run(root,run_id):
    if not re.fullmatch(r'croc-placement-sta-readback-[a-zA-Z0-9_-]+',run_id):
        raise ValueError('Independent readback run ID required')
    placement=root/'runs/croc-full-io-placement-20260905-001'
    pm=json.loads((placement/'manifest.json').read_text())
    if type(pm.get('returncode')) is not int or pm['returncode']!=0 or pm['status']!='completed':
        raise ValueError('Completed source placement required')
    for rel,digest in pm['source_sha256'].items():
        if sha(root/rel)!=digest: raise ValueError('Placement source changed: '+rel)
    for rel,digest in pm['outputs_sha256'].items():
        if sha(placement/rel)!=digest: raise ValueError('Placement output changed: '+rel)
    dest=root/'runs'/run_id
    dest.mkdir(exist_ok=False)
    source_scripts=placement/'work/openroad/scripts'
    original=root/'runs/croc-sg13g2-baseline-20260827-001/artifacts/pnr/upstream/croc/openroad'
    sources={str((placement/'manifest.json').relative_to(root)):sha(placement/'manifest.json')}
    for name in ('run_croc_placement_readback.py','run_io_ring_floorplan.py','run_io_ring_maximal_diagnostic.py','collect_croc_ppa.py','collect_croc_evidence.py'):
        sources['scripts/'+name]=sha(root/'scripts'/name)
    for rel in pm['source_sha256']:
        if rel.startswith('upstream/croc/'):
            sources[rel]=sha(root/rel)
    sources['upstream/croc/env.sh']=sha(root/'upstream/croc/env.sh')
    arms={}
    for arm,archive_path in [('baseline',original/'save/02_croc.placed.zip'),('candidate',placement/'work/openroad/save/02_croc.placed.zip')]:
        output=dest/arm
        (output/'inputs').mkdir(parents=True)
        (output/'work/openroad/scripts').mkdir(parents=True)
        for source in sorted(source_scripts.iterdir()):
            if source.is_file():
                shutil.copyfile(source,output/'work/openroad/scripts'/source.name)
                sources[str(source.relative_to(root))]=sha(source)
        with zipfile.ZipFile(archive_path) as archive:
            for suffix in ('odb','sdc','def'):
                name='02_croc.placed.'+suffix
                (output/'inputs'/name).write_bytes(archive.read(name))
        sources[str(archive_path.relative_to(root))]=sha(archive_path)
        (output/'readback.tcl').write_text(TCL)
        container=run_id+'-'+arm
        command=['docker','run','--name',container,'--cpus','2','--memory','4g','--ulimit','core=0',
            '--user',f'{os.getuid()}:{os.getgid()}','-e','HOME=/tmp','-e','CROC_PDK=sg13g2','-e','CROC_SKIP_TECH_SETUP=1',
            '--entrypoint','/bin/bash','-v',f'{root}:/work:ro','-v',f'{output}:/output:rw',
            '-w','/output/work/openroad',IMAGE,'-lc',
            'source /work/upstream/croc/env.sh && timeout --verbose --signal=TERM --kill-after=10s 180s openroad -exit /output/readback.tcl']
        arms[arm]={'command':command,'container':container,'status':'pending',
            'generated_input_sha256':{str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file()}}
    manifest={'schema_version':'1.0.0','run_id':run_id,'started_at':now(),'status':'running',
        'classification':'fresh_process_same_stage_STA_power_diagnostic_not_route_or_signoff',
        'source_sha256':sources,'arms':arms,'original_layout_modified':False,
        'activity':'tool_default_no_workload','parasitics':'placement_Metal3_estimate',
        'public_rule_signoff':False,'limits_per_arm':{'cpus':2,'memory_gb':4,'inner_seconds':180,'outer_seconds':215}}
    write(dest/'manifest.json',manifest)
    for arm,data in arms.items():
        output=dest/arm
        start=time.monotonic()
        with (output/'tool.log').open('x') as log:
            try: rc=subprocess.run(data['command'],cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=215).returncode
            except subprocess.TimeoutExpired:
                subprocess.run(['docker','stop','--time','5',data['container']],capture_output=True,timeout=15)
                rc=124
        observation=observe(data['container'])
        write(output/'terminal_observation.json',observation)
        state=observation.get('state',{})
        text=(output/'tool.log').read_text(errors='replace')
        complete=bool(rc==0 and state.get('Status')=='exited' and state.get('ExitCode')==0 and state.get('OOMKilled') is False
            and 'FRESH_PLACED_READBACK_COMPLETE' in text)
        data.update(returncode=rc,status='completed' if complete else 'failed',elapsed_seconds=time.monotonic()-start,terminal_container_state=state)
        if state.get('Status')=='exited' and state.get('Running') is False:
            data['cleanup_returncode']=subprocess.run(['docker','rm',data['container']],capture_output=True,timeout=15).returncode
        data['outputs_sha256']={str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file()}
        report=output/'work/openroad/reports/fresh_placed.rpt'
        if complete:
            data['timing']=final_timing(report)
            data['electrical_checks']=timing_checks(data['timing'])
            data['electrical_acceptance_passed']=all(data['electrical_checks'].values())
            report_text=report.read_text()
            data['area']=parse_area(report_text)
            data['power']=parse_power(report_text)
            data['clocks']=parse_clocks((output/'readback.sdc').read_text())
        write(dest/'manifest.json',manifest)
        print(json.dumps({'arm':arm,'status':data['status'],'returncode':rc,'timing':data.get('timing'),'power':data.get('power')}),flush=True)
    complete=all(data['status']=='completed' for data in arms.values())
    manifest.update(status='completed' if complete else 'failed',finished_at=now(),
        source_hashes_unchanged=all(sha(root/p)==digest for p,digest in sources.items()))
    write(dest/'manifest.json',manifest)
    return 0 if complete else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    args=parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1],args.run_id))
