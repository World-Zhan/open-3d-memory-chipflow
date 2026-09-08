#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run bounded placement from the verified full Croc floorplan, preserving inputs."""
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


CAPTURE = r'''
proc capture_placement {stage} {
    set block [ord::get_db_block]
    write_def /output/${stage}.def
    write_verilog /output/${stage}.v
    write_sdc /output/${stage}.sdc
    set f [open /output/${stage}_instances.tsv w]
    puts $f "name\tmaster\ttype\torientation\tstatus\txmin\tymin\txmax\tymax"
    set p [open /output/${stage}_iterms.tsv w]
    puts $p "instance\tpin\tnet\tio_type\tsignal_type"
    set areas [dict create]
    foreach inst [$block getInsts] {
        set master [$inst getMaster]
        set box [$inst getBBox]
        puts $f "[$inst getName]\t[$master getName]\t[$master getType]\t[$inst getOrient]\t[$inst getPlacementStatus]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
        set kind [$master getType]
        if {![dict exists $areas $kind]} {dict set areas $kind 0.0}
        dict set areas $kind [expr {[dict get $areas $kind] + [$master getWidth]*double([$master getHeight])/1000000}]
        foreach term [$inst getITerms] {
            set mt [$term getMTerm]
            set net [$term getNet]
            set nn {UNCONNECTED}
            if {$net != "NULL"} {set nn [$net getName]}
            puts $p "[$inst getName]\t[$mt getName]\t$nn\t[$mt getIoType]\t[$mt getSigType]"
        }
    }
    close $f
    close $p
    set f [open /output/${stage}_bterms.tsv w]
    puts $f "port\tnet\tio_type\tsignal_type"
    set p [open /output/${stage}_bpin_boxes.tsv w]
    puts $p "port\tnet\tlayer\txmin\tymin\txmax\tymax\tstatus"
    foreach term [$block getBTerms] {
        set nn [[$term getNet] getName]
        puts $f "[$term getName]\t$nn\t[$term getIoType]\t[$term getSigType]"
        foreach pin [$term getBPins] {
            foreach box [$pin getBoxes] {
                puts $p "[$term getName]\t$nn\t[[$box getTechLayer] getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]\t[$pin getPlacementStatus]"
            }
        }
    }
    close $f
    close $p
    set f [open /output/${stage}_area.tsv w]
    puts $f "type\tarea_um2"
    dict for {kind value} $areas {puts $f "$kind\t$value"}
    close $f
    set f [open /output/${stage}_bounds.tsv w]
    puts $f "region\tbbox_um"
    puts $f "die\t[ord::get_die_area]"
    puts $f "core\t[ord::get_core_area]"
    close $f
}

proc verify_placement_ports {} {
    set block [ord::get_db_block]
    if {[llength [$block getBTerms]] != 52} {error "Expected 52 original ports"}
    foreach {name kind} {VDD POWER VSS GROUND VDDIO POWER VSSIO GROUND} {
        set port [$block findBTerm $name]
        if {$port == "NULL" || [$port getSigType] != $kind || [[$port getNet] getName] != $name || [$port getIoType] != "INOUT"} {
            error "Invalid original PG port: $name"
        }
    }
}
'''

AFTER = r'''
# Bind PG on cells added by the original repair operations.
global_connect
verify_placement_ports
capture_placement after
set f [open /output/placement_checks.tsv w]
puts $f "check\ttcl_catch_code\tmessage"
puts {PLACEMENT_LEGALITY_BEGIN}
set code [catch {check_placement -verbose} message]
puts $f "check_placement\t$code\t[string map [list \n { } \t { }] $message]"
puts "PLACEMENT_LEGALITY_END catch=$code result=$message"
foreach net {VDD VSS} {
    puts "PLACED_PG_CHECK_BEGIN $net"
    set code [catch {check_power_grid -net $net -error_file /output/pg_errors_${net}.rpt} message]
    puts $f "check_power_grid_$net\t$code\t[string map [list \n { } \t { }] $message]"
    puts "PLACED_PG_CHECK_END $net catch=$code result=$message"
}
close $f
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical_violators.rpt
puts {FULL_PLACEMENT_EVIDENCE_CAPTURE_COMPLETE}
'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Pinned source changed: '+old)
    return text.replace(old,new)


def run(root, run_id):
    if not re.fullmatch(r'croc-full-io-placement-[a-zA-Z0-9_-]+',run_id):
        raise ValueError('Independent placement run ID required')
    source=root/'runs/croc-full-io-floorplan-20260905-005'
    gate_path=root/'reports/floorplan/full-io-readback-audit-20260905-001.json'
    gate=json.loads(gate_path.read_text())
    if gate['top_pin_geometry_and_binding_result'] != 'PASS' or gate['static_core_pg_floorplanning_result'] != 'PASS':
        raise ValueError('Floorplan prerequisite failed')
    for rel,digest in gate['source_sha256'].items():
        if sha(root/rel)!=digest:
            raise ValueError('Prerequisite evidence changed: '+rel)
    dest=root/'runs'/run_id
    dest.mkdir(exist_ok=False)
    work=dest/'work/openroad'
    for folder in ('scripts','src','save'):
        (work/folder).mkdir(parents=True,exist_ok=True)
    (dest/'inputs').mkdir()
    sources={str(gate_path.relative_to(root)):sha(gate_path)}
    def copy(path,target):
        shutil.copyfile(path,target)
        sources[str(path.relative_to(root))]=sha(path)
    for folder in ('scripts','src'):
        for path in sorted((source/'work/openroad'/folder).iterdir()):
            if path.is_file(): copy(path,work/folder/path.name)
    copy(source/'work/openroad/save/01_croc.floorplan.zip',work/'save/01_croc.floorplan.zip')
    copy(source/'inputs/croc_yosys.v',dest/'inputs/croc_yosys.v')
    copy(source/'manifest.json',dest/'inputs/source_manifest.json')
    original=root/'runs/croc-sg13g2-baseline-20260827-001/artifacts/pnr/upstream/croc/openroad'
    copy(original/'reports/02_croc.placed.rpt',dest/'inputs/baseline_placed.rpt')
    with zipfile.ZipFile(original/'save/02_croc.placed.zip') as archive:
        (dest/'inputs/baseline_placed.def').write_bytes(archive.read('02_croc.placed.def'))
    sources[str((original/'save/02_croc.placed.zip').relative_to(root))]=sha(original/'save/02_croc.placed.zip')
    for path in [root/'scripts/run_croc_full_placement.py',root/'scripts/run_io_ring_maximal_diagnostic.py',root/'scripts/run_io_ring_floorplan.py',root/'upstream/croc/env.sh']:
        sources[str(path.relative_to(root))]=sha(path)
    for folder in ('lef','lib'):
        for path in sorted((root/'upstream/croc/technology'/folder).glob('*')):
            if path.is_file(): sources[str(path.relative_to(root))]=sha(path)
    (dest/'capture_placement.tcl').write_text(CAPTURE)
    (dest/'after_placement.tcl').write_text(AFTER)
    stage=work/'scripts/02_placement.tcl'
    text=stage.read_text()
    text=replace_once(text,'load_checkpoint 01_${proj_name}.floorplan','load_checkpoint 01_${proj_name}.floorplan\nset_thread_count 2\nsource /output/capture_placement.tcl\nverify_placement_ports\ncapture_placement before\ncheck_setup > /output/input_constraints.rpt')
    text=replace_once(text,'set_thread_count 8','set_thread_count 2')
    text=replace_once(text,'report_metrics "02_${proj_name}.placed"','source /output/after_placement.tcl\nreport_metrics "02_${proj_name}.placed"')
    stage.write_text(text)
    command=['docker','run','--name',run_id,'--cpus','2','--memory','8g','--ulimit','core=0',
        '--user',f'{os.getuid()}:{os.getgid()}','-e','HOME=/tmp','-e','QT_QPA_PLATFORM=offscreen',
        '-e','CROC_PDK=sg13g2','-e','CROC_SKIP_TECH_SETUP=1','--entrypoint','/bin/bash',
        '-v',f'{root}:/work:ro','-v',f'{dest}:/output:rw','-w','/output/work/openroad',IMAGE,'-lc',
        'source /work/upstream/croc/env.sh && timeout --verbose --signal=TERM --kill-after=15s 900s openroad -exit scripts/02_placement.tcl']
    manifest={'schema_version':'1.0.0','run_id':run_id,'source_run':source.name,'started_at':now(),'status':'running',
        'classification':'full_functional_placement_candidate_not_route_or_signoff','command':command,'source_sha256':sources,
        'generated_inputs_sha256':{str(p.relative_to(dest)):sha(p) for p in dest.rglob('*') if p.is_file()},
        'original_stage_operations_preserved':True,'thread_limit':2,'io_load_constraint_unchanged':True,
        'inherited_cts_eco':False,'original_layout_modified':False,'public_rule_signoff':False,
        'limits':{'cpus':2,'memory_gb':8,'inner_seconds':900,'kill_grace_seconds':15,'outer_seconds':945}}
    write(dest/'manifest.json',manifest)
    start=time.monotonic()
    samples=[]
    outer_expired=False
    print(json.dumps({'run_id':run_id,'status':'starting','input_checkpoint_sha256':sha(work/'save/01_croc.floorplan.zip')}),flush=True)
    with (dest/'tool.log').open('x') as log:
        process=subprocess.Popen(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
        while process.poll() is None:
            if time.monotonic()-start>945:
                outer_expired=True
                stop=subprocess.run(['docker','stop','--time','5',run_id],capture_output=True,text=True,timeout=15)
                manifest['outer_stop_returncode']=stop.returncode
                break
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                sample=observe(run_id)
                samples.append(sample)
                write(dest/'resource_samples.json',samples)
                print(json.dumps({'run_id':run_id,'elapsed_seconds':round(time.monotonic()-start,1),
                    'container_status':sample.get('state',{}).get('Status'),'memory':sample.get('resources',{}).get('MemUsage')}),flush=True)
        try: returncode=process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            returncode=process.wait(timeout=10)
    terminal=observe(run_id)
    write(dest/'terminal_observation.json',terminal)
    write(dest/'resource_samples.json',samples)
    state=terminal.get('state',{})
    log=(dest/'tool.log').read_text(errors='replace')
    complete=bool(returncode==0 and state.get('Status')=='exited' and state.get('ExitCode')==0
        and state.get('OOMKilled') is False and not outer_expired
        and 'FULL_PLACEMENT_EVIDENCE_CAPTURE_COMPLETE' in log and 'Stage 02 complete:' in log
        and (work/'save/02_croc.placed.zip').is_file())
    manifest.update(returncode=returncode,status='completed' if complete else 'failed',execution_complete=complete,
        finished_at=now(),elapsed_seconds=time.monotonic()-start,outer_timeout_expired=outer_expired,
        terminal_container_state=state,source_hashes_unchanged=all(sha(root/p)==v for p,v in sources.items()),
        design_checks_require_independent_audit=True)
    if state.get('Status')=='exited' and state.get('Running') is False:
        manifest['cleanup_returncode']=subprocess.run(['docker','rm',run_id],capture_output=True,text=True,timeout=15).returncode
    else: manifest['cleanup_returncode']=None
    manifest['outputs_sha256']={str(p.relative_to(dest)):sha(p) for p in dest.rglob('*') if p.is_file() and p.name!='manifest.json'}
    write(dest/'manifest.json',manifest)
    print(json.dumps({key:manifest[key] for key in ('run_id','status','returncode','elapsed_seconds','terminal_container_state')}),flush=True)
    return 0 if complete else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    args=parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1],args.run_id))
