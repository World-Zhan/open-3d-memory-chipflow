#!/usr/bin/env python3
"""Second bounded INPUT arm; omits unsafe no-Liberty pin STA properties."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/home/james_zhan/projects/open-3d-memory-chipflow')
IMAGE = 'sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521'
SOURCE = ROOT / 'runs/croc-placement-sta-readback-20260909-001/candidate'

TCL = r'''
source scripts/startup.tcl
set_thread_count 2
read_db /source/inputs/02_croc.placed.odb
set af [open /output/api_inventory.txt w]
foreach pattern {sta::*activity* sta::*power* sta::*debug* utl::*debug* sta::*clock*} {
    puts $af "$pattern [lsort [info commands $pattern]]"
}
foreach proc {sta::report_power sta::report_activity_annotation sta::set_debug_level utl::set_debug_level} {
    if {[llength [info procs $proc]]} {puts $af "$proc\n[info body $proc]"}
}
close $af
set mf [open /output/bondpad_master_directions.tsv w]
puts $mf "master\tpin\tio_type\tsignal_type"
foreach lib [[ord::get_db] getLibs] {
    foreach name {bondpad_70x70 bondpad70_m2_ring} {
        set master [$lib findMaster $name]
        if {$master != "NULL"} {
            foreach mt [$master getMTerms] {
                puts $mf "$name\t[$mt getName]\t[$mt getIoType]\t[$mt getSigType]"
            }
        }
    }
}
close $mf
set cf [open /output/direction_change.tsv w]
puts $cf "master\tpin\tbefore\tafter"
@@DIRECTION_CHANGE@@
close $cf
read_sdc /source/inputs/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
estimate_parasitics -placement
report_clock_properties > /output/clocks.rpt
report_power -corner tt -digits 8 > /output/power_tt.rpt
report_power -corner ff -digits 8 > /output/power_ff.rpt
set srams [get_cells -quiet -filter {ref_name == RM_IHPSG13_1P_512x32_c2_bm_bist} *]
report_power -instances $srams -corner tt -digits 8 > /output/sram_power_tt.rpt
if {[llength [info commands sta::report_activity_annotation]]} {
    catch {report_activity_annotation > /output/activity_annotation.rpt} activity_message
}
write_sdc /output/readback.sdc
puts POWER_DIRECTION_PROBE_COMPLETE
'''

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', choices=['observe', 'input_analysis'], required=True)
    args = ap.parse_args()
    run_id = f'croc-power-direction-{args.arm}-20260909-001'
    out = ROOT / 'runs' / run_id
    out.mkdir(exist_ok=False)
    work = out / 'work/openroad'
    work.mkdir(parents=True)
    shutil.copytree(SOURCE / 'work/openroad/scripts', work / 'scripts')
    (work / 'reports').mkdir()
    change = ''
    if args.arm == 'input_analysis':
        change = r'''foreach lib [[ord::get_db] getLibs] {
    set master [$lib findMaster bondpad70_m2_ring]
    if {$master != "NULL"} {
        set mt [$master findMTerm pad]
        set before [$mt getIoType]
        if {$before != "INOUT"} {error "Expected original INOUT pad"}
        $mt setIoType INPUT
        puts $cf "bondpad70_m2_ring\tpad\t$before\t[$mt getIoType]"
    }
}'''
    (out / 'probe.tcl').write_text(TCL.replace('@@DIRECTION_CHANGE@@', change))
    sources = [SOURCE / 'inputs/02_croc.placed.odb', SOURCE / 'inputs/02_croc.placed.sdc', ROOT / 'upstream/croc/env.sh', Path(__file__)]
    sources += sorted((SOURCE / 'work/openroad/scripts').glob('*.tcl'))
    sources += sorted((ROOT / 'upstream/croc/technology/lib').glob('*.lib'))
    source_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    command = ['docker','run','--name',run_id,'--cpus','2','--memory','4g','--ulimit','core=0','--user','1000:1000','-e','HOME=/tmp','-e','CROC_PDK=sg13g2','-e','CROC_SKIP_TECH_SETUP=1','--entrypoint','/bin/bash','-v',f'{ROOT}:/work:ro','-v',f'{SOURCE}:/source:ro','-v',f'{out}:/output:rw','-w','/output/work/openroad',IMAGE,'-lc','source /work/upstream/croc/env.sh && timeout --verbose --signal=TERM --kill-after=10s 180s openroad -exit /output/probe.tcl']
    manifest = {'schema_version':'1.0.0','run_id':run_id,'arm':args.arm,'classification':'observation_only' if args.arm=='observe' else 'analysis_only_direction_override_not_design_fix','source_sha256':source_hashes,'command':command,'started_at':utc(),'limits':{'cpus':2,'memory_gb':4,'inner_seconds':180,'kill_grace_seconds':10,'outer_seconds':205},'source_odb_modified':False,'design_fix':False,'public_rule_signoff':False,'activity':'tool_default_no_workload','status':'running'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    start=time.monotonic()
    with (out/'tool.log').open('w') as log:
        proc = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        try:
            rc=proc.wait(timeout=205)
            outer=False
        except subprocess.TimeoutExpired:
            outer=True
            subprocess.run(['docker','stop','-t','10',run_id],capture_output=True,timeout=20)
            rc=proc.wait(timeout=20)
    inspect = subprocess.run(['docker','inspect',run_id],capture_output=True,text=True,timeout=20)
    (out/'terminal_observation.json').write_text(inspect.stdout)
    state=json.loads(inspect.stdout)[0]['State'] if inspect.returncode==0 else None
    manifest.update(returncode=rc,outer_timeout_expired=outer,terminal_container_state=state,elapsed_seconds=time.monotonic()-start,finished_at=utc(),source_hashes_unchanged=all(sha(ROOT/p)==h for p,h in source_hashes.items()))
    manifest['execution_complete'] = rc==0 and state is not None and state['ExitCode']==0 and not state['Running'] and not state['OOMKilled'] and not outer and 'POWER_DIRECTION_PROBE_COMPLETE' in (out/'tool.log').read_text()
    manifest['status']='completed' if manifest['execution_complete'] else 'failed'
    if state is not None and not state['Running']:
        cleanup=subprocess.run(['docker','rm',run_id],capture_output=True,text=True,timeout=20)
        manifest['cleanup_returncode']=cleanup.returncode
    manifest['outputs_sha256']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'run_id':run_id,'returncode':rc,'execution_complete':manifest['execution_complete'],'elapsed_seconds':manifest['elapsed_seconds'],'terminal_state':state},indent=2))
    return 0 if manifest['execution_complete'] else 1

if __name__=='__main__':
    raise SystemExit(main())

