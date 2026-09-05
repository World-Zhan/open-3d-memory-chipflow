#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read a saved full floorplan and inspect physical top pins and static PG."""
import argparse
import csv
import json
import os
import re
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
from run_io_ring_floorplan import IMAGE, now, sha, write

TCL = r'''
set_thread_count 2
read_db /output/inputs/01_croc.floorplan.odb
help check_power_grid
set block [ord::get_db_block]
set f [open /output/top_pin_boxes.tsv w]
puts $f "port\tnet\tio_type\tsignal_type\tlayer\txmin\tymin\txmax\tymax\tplacement_status"
foreach port [$block getBTerms] {
    foreach pin [$port getBPins] {
        foreach box [$pin getBoxes] {
            puts $f "[$port getName]\t[[$port getNet] getName]\t[$port getIoType]\t[$port getSigType]\t[[$box getTechLayer] getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]\t[$pin getPlacementStatus]"
        }
    }
}
close $f
set f [open /output/bondpad_boxes.tsv w]
puts $f "instance\tnet\txmin\tymin\txmax\tymax"
foreach inst [$block getInsts] {
    if {[[$inst getMaster] getName] != "bondpad70_m2_ring"} {continue}
    set box [$inst getBBox]
    set net [[ $inst findITerm pad ] getNet]
    if {$net == "NULL"} {error "Unconnected actual bondpad"}
    puts $f "[$inst getName]\t[$net getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
}
close $f
set f [open /output/pg_checks.tsv w]
puts $f "net\ttcl_catch_code\tmessage"
foreach net {VDD VSS} {
    puts "STATIC_PG_CHECK_BEGIN $net"
    set code [catch {check_power_grid -net $net -floorplanning -error_file /output/pg_errors_${net}.rpt} message]
    puts $f "$net\t$code\t[string map [list \n { } \t { }] $message]"
    puts "STATIC_PG_CHECK_END $net catch=$code"
}
close $f
puts {FULL_FLOORPLAN_READBACK_COMPLETE}
'''


def pin_signatures(text):
    body = re.search(r'^PINS\s+\d+\s*;(.*?)^END PINS', text, re.M|re.S)
    if not body:
        raise ValueError('Missing DEF pins')
    result = {}
    for record in body[1].split(';'):
        name = re.match(r'\s*-\s+(\S+)', record)
        if not name:
            continue
        result[name[1]] = tuple(re.search(r'\+\s+'+key+r'\s+(\S+)', record)[1] for key in ('NET','DIRECTION','USE'))
    return result


def run(root, run_id, source_run):
    if not re.fullmatch(r'croc-full-io-floorplan-readback-[a-zA-Z0-9_-]+', run_id):
        raise ValueError('Independent readback ID required')
    source = root/'runs'/source_run
    original = json.loads((source/'manifest.json').read_text())
    if original['status'] != 'completed' or original['returncode'] != 0:
        raise ValueError('Completed source required')
    for rel, digest in original['source_sha256'].items():
        if sha(root/rel) != digest:
            raise ValueError('Source changed: ' + rel)
    for rel, digest in original['outputs_sha256'].items():
        if sha(source/rel) != digest:
            raise ValueError('Source output changed: ' + rel)
    dest = root/'runs'/run_id
    (dest/'inputs').mkdir(parents=True, exist_ok=False)
    archive_path = source/'work/openroad/save/01_croc.floorplan.zip'
    with zipfile.ZipFile(archive_path) as archive:
        for suffix in ('odb','def'):
            name = '01_croc.floorplan.'+suffix
            (dest/'inputs'/name).write_bytes(archive.read(name))
    (dest/'readback.tcl').write_text(TCL)
    command = ['docker', 'run', '--rm', '--name', run_id, '--cpus', '2', '--memory', '4g', '--ulimit', 'core=0',
        '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp', '--entrypoint', '/bin/bash',
        '-v', f'{dest}:/output:rw', IMAGE, '-lc',
        'timeout --verbose --signal=TERM --kill-after=10s 120s openroad -exit /output/readback.tcl']
    files = [source/'manifest.json', archive_path, source/'io_instances.tsv',
        source/'inputs/baseline_floorplan.def', root/'scripts/check_full_io_floorplan.py']
    manifest = {'run_id': run_id, 'source_run': source_run, 'started_at': now(), 'status': 'running', 'command': command,
        'source_sha256': {str(p.relative_to(root)): sha(p) for p in files},
        'input_sha256': {str(p.relative_to(dest)): sha(p) for p in (dest/'inputs').iterdir()},
        'readback_tcl_sha256': sha(dest/'readback.tcl'), 'public_rule_signoff': False}
    write(dest/'manifest.json', manifest)
    try:
        with (dest/'tool.log').open('x') as log:
            rc = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=150).returncode
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','stop','--time','5',run_id], capture_output=True, timeout=15)
        rc = 124
    text = (dest/'tool.log').read_text(errors='replace')
    complete = rc == 0 and 'FULL_FLOORPLAN_READBACK_COMPLETE' in text
    manifest.update(returncode=rc, finished_at=now(), status='completed' if complete else 'failed',
        outputs_sha256={str(p.relative_to(dest)): sha(p) for p in dest.rglob('*') if p.is_file() and p.name != 'manifest.json'})
    write(dest/'manifest.json', manifest)
    if not complete:
        print(text[-4500:]); return 1
    def rows(name):
        with (dest/name).open() as handle:
            return list(csv.DictReader(handle, delimiter='\t'))
    pins = rows('top_pin_boxes.tsv')
    bonds = rows('bondpad_boxes.tsv')
    pg_checks = rows('pg_checks.tsv')
    key = lambda row: (row['net'], *(int(row[field]) for field in ('xmin','ymin','xmax','ymax')))
    boxes_equal = Counter(map(key,pins)) == Counter(map(key,bonds))
    old_signatures = pin_signatures((source/'inputs/baseline_floorplan.def').read_text())
    new_signatures = pin_signatures((dest/'inputs/01_croc.floorplan.def').read_text())
    signatures_equal = old_signatures == new_signatures
    geometry_pass = (len(pins)==64 and len(bonds)==64 and boxes_equal and signatures_equal
        and len(new_signatures)==52 and {p['layer'] for p in pins}=={'TopMetal2'}
        and all(p['placement_status'] in ('FIRM','LOCKED') for p in pins))
    summary = {'classification': 'full_floorplan_physical_terminal_and_static_pg_readback_not_signoff', 'run_id': run_id,
        'source_run': source_run, 'physical_top_pin_boxes': len(pins), 'bondpad_boxes': len(bonds),
        'physical_top_ports': len({p['port'] for p in pins}), 'top_port_signatures_match_original_floorplan': signatures_equal,
        'each_top_pin_box_matches_actual_bondpad_metal_bbox': boxes_equal,
        'top_pin_geometry_contract_passed': geometry_pass,
        'pg_checks': pg_checks, 'pg_interpretation': 'Retain raw command output. floorplanning-mode checks are not placed standard-cell connectivity, IR/EM, or LVS.',
        'public_rule_signoff': False, 'new_power_mw': None, 'new_fmax_mhz': None,
        'source_sha256': {str(p.relative_to(root)): sha(p) for p in (dest/'manifest.json', dest/'top_pin_boxes.tsv', dest/'bondpad_boxes.tsv', dest/'pg_checks.tsv')}}
    write(dest/'summary.json', summary)
    print(json.dumps(summary), flush=True)
    return 0 if geometry_pass else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--source-run', required=True)
    args = parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id, args.source_run))
