#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Integrate the verified IO-ring geometry into an independent full floorplan."""
import argparse
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import zipfile
from collections import Counter
from pathlib import Path

from audit_io_ring_plan import placed_pitch
from run_io_ring_floorplan import IMAGE, now, sha, write

SNAPSHOT = r'''
# Snapshot functional connectivity before any new physical cells are added.
set initial_masters [dict create]
set initial_signal_pins [dict create]
set initial_ports [dict create]
set block [ord::get_db_block]
foreach inst [$block getInsts] {
    dict set initial_masters [$inst getName] [[$inst getMaster] getName]
    foreach term [$inst getITerms] {
        set mt [$term getMTerm]
        if {[$mt getSigType] in {POWER GROUND}} {continue}
        set net [$term getNet]
        set net_name {UNCONNECTED}
        if {$net != "NULL"} {set net_name [$net getName]}
        dict set initial_signal_pins [list [$inst getName] [$mt getName]] $net_name
    }
}
foreach port [$block getBTerms] {
    dict set initial_ports [$port getName] [list [[$port getNet] getName] [$port getIoType] [$port getSigType]]
}
'''

VERIFY = r'''
set block [ord::get_db_block]
dict for {name master} $initial_masters {
    set inst [$block findInst $name]
    if {$inst == "NULL" || [[$inst getMaster] getName] != $master} {error "Original functional instance changed: $name"}
}
dict for {key expected} $initial_signal_pins {
    lassign $key inst_name pin_name
    set term [[$block findInst $inst_name] findITerm $pin_name]
    if {$term == "NULL"} {error "Original pin missing: $key"}
    set net [$term getNet]
    set actual {UNCONNECTED}
    if {$net != "NULL"} {set actual [$net getName]}
    if {$actual != $expected} {error "Original signal connection changed: $key"}
}
dict for {name expected} $initial_ports {
    set port [$block findBTerm $name]
    if {$port == "NULL"} {error "Original top port missing: $name"}
    set actual [list [[$port getNet] getName] [$port getIoType] [$port getSigType]]
    if {$actual != $expected} {error "Original port changed: $name"}
}
set added [dict create]
set pg_count 0
foreach inst [$block getInsts] {
    set name [$inst getName]
    set master [[$inst getMaster] getName]
    if {![dict exists $initial_masters $name]} {
        if {$master != "bondpad70_m2_ring" && $master != "sg13g2_Corner" && ![string match sg13g2_Filler* $master]} {
            error "Unexpected added functional instance: $name $master"
        }
        dict incr added $master
    }
    foreach term [$inst getITerms] {
        set pin [[$term getMTerm] getName]
        set expected {}
        switch -- $pin {
            VDD - VDD! - VDDARRAY - VDDARRAY! - vdd {set expected VDD}
            VSS - VSS! - vss {set expected VSS}
            iovdd {set expected VDDIO}
            iovss {set expected VSSIO}
        }
        if {$expected != {}} {
            set net [$term getNet]
            if {$net == "NULL" || [$net getName] != $expected} {error "Missing or wrong explicit PG: $name $pin"}
            incr pg_count
        }
    }
}
set f [open /output/structural_summary.tsv w]
puts $f "metric\tvalue"
puts $f "original_instances\t[dict size $initial_masters]"
puts $f "original_signal_pins\t[dict size $initial_signal_pins]"
puts $f "original_top_ports\t[dict size $initial_ports]"
puts $f "explicit_pg_pins\t$pg_count"
puts $f "core_bbox_um\t[ord::get_core_area]"
puts $f "functional_connectivity_preserved\ttrue"
close $f
set f [open /output/io_instances.tsv w]
puts $f "name\tmaster\torientation\txmin\tymin\txmax\tymax"
set counts [dict create]
foreach inst [$block getInsts] {
    set master [[$inst getMaster] getName]
    dict incr counts $master
    if {[string match sg13g2_IOPad* $master] || [string match sg13g2_Filler* $master] || $master in {sg13g2_Corner bondpad70_m2_ring}} {
        set b [$inst getBBox]
        puts $f "[$inst getName]\t$master\t[$inst getOrient]\t[$b xMin]\t[$b yMin]\t[$b xMax]\t[$b yMax]"
    }
}
close $f
set f [open /output/master_areas.tsv w]
puts $f "master\ttype\tarea_um2\tcandidate_count"
foreach lib [[ord::get_db] getLibs] {
    foreach master [$lib getMasters] {
        set name [$master getName]
        set count 0
        if {[dict exists $counts $name]} {set count [dict get $counts $name]}
        puts $f "$name\t[$master getType]\t[expr {[$master getWidth]*double([$master getHeight])/1000000}]\t$count"
    }
}
close $f
puts {FULL_IO_FLOORPLAN_STRUCTURAL_CHECK_COMPLETE}
'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Unexpected pinned source: ' + old[:70])
    return text.replace(old, new)


def run(root, run_id):
    if not re.fullmatch(r'croc-full-io-floorplan-[a-zA-Z0-9_-]+', run_id):
        raise ValueError('Independent run ID required')
    geometry_path = root/'runs/croc-io-ring-physical-20260905-002/geometry_audit.json'
    pg_path = root/'reports/bondpad/io-ring-pg-vias-20260905-001.json'
    geometry = json.loads(geometry_path.read_text())
    pg = json.loads(pg_path.read_text())
    if geometry['geometry_contract_passed'] is not True or pg['overall_metal_via_connectivity_result'] != 'PASS':
        raise ValueError('IO-only geometry/PG prerequisites not met')
    for data in (geometry, pg):
        for rel, digest in data['source_sha256'].items():
            if sha(root/rel) != digest:
                raise ValueError('Prerequisite source changed: ' + rel)
    original = root/'upstream/croc/openroad'
    baseline = root/'runs/croc-sg13g2-baseline-20260827-001'
    source_netlist = baseline/'artifacts/netlist-sim/upstream/croc/yosys/out/croc_yosys.v'
    source_checkpoint = baseline/'artifacts/pnr/upstream/croc/openroad/save/01_croc.floorplan.zip'
    dest = root/'runs'/run_id
    dest.mkdir(exist_ok=False)
    work = dest/'work/openroad'
    (work/'scripts').mkdir(parents=True)
    (work/'src').mkdir()
    inputs = dest/'inputs'
    inputs.mkdir()
    shutil.copyfile(source_netlist, inputs/'croc_yosys.v')
    with zipfile.ZipFile(source_checkpoint) as archive:
        (inputs/'baseline_floorplan.def').write_bytes(archive.read('01_croc.floorplan.def'))
    files = [source_netlist, source_checkpoint, geometry_path, pg_path,
        root/'scripts/run_croc_io_floorplan_headless.py', root/'scripts/add_io_ring_connected_leads.tcl',
        root/'runs/croc-io-ring-floorplan-20260905-001/padring_candidate.tcl',
        root/'runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.lef', root/'upstream/croc/env.sh']
    for folder in ('scripts', 'src'):
        for source in sorted((original/folder).glob('*')):
            if source.is_file():
                shutil.copyfile(source, work/folder/source.name)
                files.append(source)
    startup = work/'scripts/startup.tcl'
    startup.write_text(replace_once(startup.read_text(), 'set netlist "../yosys/out/${proj_name}_yosys.v"', 'set netlist /output/inputs/croc_yosys.v'))
    shutil.copyfile(root/'runs/croc-io-ring-floorplan-20260905-001/padring_candidate.tcl', work/'src/padring.tcl')
    floorplan = work/'scripts/01_floorplan.tcl'
    text = floorplan.read_text()
    text = replace_once(text, 'source scripts/startup.tcl', 'source scripts/startup.tcl\nset_thread_count 2\nread_lef /reference/bondpad70_m2_ring.lef\nset bondPadCell bondpad70_m2_ring')
    text = replace_once(text, 'link_design $top_design', 'link_design $top_design\n'+SNAPSHOT)
    for old, new in [('set chipH    1916;', 'set chipH    1974;'), ('set chipW    1916;', 'set chipW    1974;'), ('set padBond    70;', 'set padBond    92;')]:
        text = replace_once(text, old, new)
    text = replace_once(text, '# Save checkpoint\nsave_checkpoint', 'source /output/add_full_io_leads.tcl\n'+VERIFY+'\n# Save checkpoint\nsave_checkpoint')
    floorplan.write_text(text)
    leads = (root/'scripts/add_io_ring_connected_leads.tcl').read_text()
    leads = replace_once(leads, 'read_db /input/io_ring.odb\n', '')
    leads = replace_once(leads, 'write_db /output/io_ring.odb\nwrite_def /output/io_ring.def\n', '')
    leads = replace_once(leads, 'IO_RING_LEADS_COMPLETE: 64 leads across six metal layers; core routing absent', 'FULL_IO_LEADS_COMPLETE: 64 leads across six layers; full core floorplan present, signal placement/routing not run')
    (dest/'add_full_io_leads.tcl').write_text(leads)
    files += sorted((root/'upstream/croc/technology/lef').glob('*.lef'))
    files += sorted((root/'upstream/croc/technology/lib').glob('*.lib'))
    command = ['docker', 'run', '--rm', '--ulimit', 'core=0', '--name', run_id, '--cpus', '2', '--memory', '4g', '--user', f'{os.getuid()}:{os.getgid()}',
        '-e', 'HOME=/tmp', '-e', 'QT_QPA_PLATFORM=offscreen', '-e', 'CROC_PDK=sg13g2', '-e', 'CROC_SKIP_TECH_SETUP=1', '--entrypoint', '/bin/bash',
        '-v', f'{root}:/work:ro', '-v', f'{dest}:/output:rw',
        '-v', f'{root}/runs/croc-bondpad-io-ab-20260905-001/inputs:/reference:ro',
        '-w', '/output/work/openroad', IMAGE, '-lc',
        'source /work/upstream/croc/env.sh && timeout --verbose --signal=TERM --kill-after=10s 180s openroad -exit scripts/01_floorplan.tcl']
    generated = [p for p in dest.rglob('*') if p.is_file()]
    manifest = {'schema_version': '1.0.0', 'run_id': run_id, 'started_at': now(), 'status': 'running',
        'classification': 'full_functional_design_floorplan_and_pdn_candidate_not_route_or_signoff',
        'headless_gui_platform': 'offscreen', 'supersedes_failed_run': 'croc-full-io-floorplan-20260905-001',
        'command': command, 'source_sha256': {str(p.relative_to(root)): sha(p) for p in files},
        'generated_inputs_sha256': {str(p.relative_to(dest)): sha(p) for p in generated},
        'core_logic_included': True, 'original_layout_modified': False,
        'signal_placement_performed': False, 'signal_routing_performed': False, 'public_rule_signoff': False,
        'drc_lvs_performed': False, 'inherited_cts_eco': False,
        'parameters': {'electrical_die_um': [1974,1974], 'io_offset_um': 92, 'io_pitch_um': 90, 'bondpad_gap_um': 4.2,
            'power_ring_reservation_um': 80, 'io_load_constraint_unchanged': True}}
    write(dest/'manifest.json', manifest)
    try:
        with (dest/'tool.log').open('x') as log:
            rc = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=215).returncode
    except subprocess.TimeoutExpired:
        subprocess.run(['docker', 'stop', '--time', '5', run_id], capture_output=True, timeout=15)
        rc = 124
    log = (dest/'tool.log').read_text(errors='replace')
    complete = rc == 0 and 'FULL_IO_FLOORPLAN_STRUCTURAL_CHECK_COMPLETE' in log and 'Stage 01 complete: Checkpoint saved' in log
    manifest.update(returncode=rc, finished_at=now(), status='completed' if complete else 'failed',
        execution_complete=complete, source_hashes_unchanged=all(sha(root/p)==v for p,v in manifest['source_sha256'].items()),
        outputs_sha256={str(p.relative_to(dest)): sha(p) for p in dest.rglob('*') if p.is_file() and p.name != 'manifest.json'})
    write(dest/'manifest.json', manifest)
    if complete:
        with (dest/'io_instances.tsv').open() as handle:
            rows = list(csv.DictReader(handle, delimiter='\t'))
        edges = placed_pitch(rows)
        with (dest/'structural_summary.tsv').open() as handle:
            facts = {r['metric']: r['value'] for r in csv.DictReader(handle, delimiter='\t')}
        with (dest/'master_areas.tsv').open() as handle:
            masters = {r['master']: r for r in csv.DictReader(handle, delimiter='\t')}
        body = re.search(r'^COMPONENTS\s+\d+\s*;(.*?)^END COMPONENTS', (inputs/'baseline_floorplan.def').read_text(), re.M|re.S)[1]
        baseline_counts = Counter()
        for record in body.split(';'):
            match = re.match(r'\s*-\s+\S+\s+(\S+)', record)
            if match:
                baseline_counts[match[1]] += 1
        def areas(counts):
            by_type = Counter()
            for master, count in counts.items():
                by_type[masters[master]['type']] += count*float(masters[master]['area_um2'])
            return dict(sorted(by_type.items()))
        candidate_counts = {name: int(info['candidate_count']) for name, info in masters.items() if int(info['candidate_count'])}
        core = [float(v) for v in facts['core_bbox_um'].split()]
        summary = {'classification': 'full_floorplan_structural_and_area_evidence_not_signoff', 'run_id': run_id,
            'structural_checks': facts, 'io_edges': edges, 'io_only_instance_count': len(rows),
            'baseline_floorplan_area_um2_by_master_type': areas(baseline_counts),
            'candidate_floorplan_area_um2_by_master_type': areas(candidate_counts),
            'baseline_floorplan_instance_count': sum(baseline_counts.values()),
            'candidate_floorplan_instance_count': sum(candidate_counts.values()),
            'candidate_core_bbox_um': core, 'candidate_core_area_mm2': (core[2]-core[0])*(core[3]-core[1])/1e6,
            'candidate_electrical_area_mm2': 1.974**2, 'planned_sealed_area_mm2': 2.058**2,
            'new_power_mw': None, 'new_fmax_mhz': None, 'placement_routing_sta_drc_lvs': 'not_run',
            'pdn_geometry_created': True, 'physical_core_pdn_connectivity_proven': False, 'public_rule_signoff': False,
            'source_sha256': {str(p.relative_to(root)): sha(p) for p in (dest/'manifest.json', dest/'master_areas.tsv',
                dest/'structural_summary.tsv', dest/'io_instances.tsv', inputs/'baseline_floorplan.def')}}
        write(dest/'summary.json', summary)
        print(json.dumps(summary), flush=True)
    else:
        print(log[-5000:], flush=True)
    return 0 if complete else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id))
