#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Apply bounded SRAM output capacitance buffering to the current full CTS candidate."""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from run_io_ring_floorplan import IMAGE, now, sha, write
from run_io_ring_maximal_diagnostic import observe
from run_croc_full_cts import CAPTURE, AFTER


def diagnosis(root, source):
    from audit_croc_placement_structure import groups, attribute
    from validate_croc_clock_eco import clock_properties
    def canonical(name):
        return name.replace('\\[', '[').replace('\\]', ']')
    def read_tsv(name):
        with (source / name).open() as handle:
            return list(csv.DictReader(handle, delimiter='\t'))
    instances = {r['name']: r for r in read_tsv('after_instances.tsv')}
    terms = read_tsv('after_iterms.tsv')
    ports = read_tsv('after_bterms.tsv')
    index = {(canonical(r['instance']), r['pin']): r for r in terms}
    if len(index) != len(terms):
        raise ValueError('Ambiguous escaped terminal names')
    by_net = {}
    for term in terms:
        by_net.setdefault(term['net'], []).append(term)
    cap = (source / 'electrical_violators.rpt').read_text().split('max capacitance\n', 1)[1]
    expected = {(bank, bit) for bank in range(2) for bit in range(32)}
    diagnosed = []
    props, _ = clock_properties((source / 'after.def').read_text())
    lef = root / 'upstream/croc/technology/lef/RM_IHPSG13_1P_512x32_c2_bm_bist.lef'
    lef_text = lef.read_text()
    for line in cap.splitlines():
        if '/A_DOUT[' not in line:
            continue
        match = re.fullmatch(r'(\S+)/A_DOUT\[(\d+)\]\s+(\S+)\s+(\S+)\s+(\S+)\s+\(VIOLATED\)', line)
        if not match:
            raise ValueError('Malformed SRAM violation')
        inst_name, bit, limit, actual, slack = match.groups()
        bank_match = re.fullmatch(r'i_croc_soc/i_croc/gen_sram_bank\[(\d+)\]\.i_sram/gen_512x32xBx1\.i_cut', inst_name)
        if not bank_match:
            raise ValueError('Unexpected SRAM driver')
        bank, bit = int(bank_match[1]), int(bit)
        pin = f'A_DOUT[{bit}]'
        driver = index[inst_name, pin]
        inst = instances[driver['instance']]
        net = driver['net']
        if (inst['type'] != 'BLOCK' or inst['orientation'] != 'R0'
                or inst['master'] != 'RM_IHPSG13_1P_512x32_c2_bm_bist'
                or props.get(net) != ('SIGNAL', None)):
            raise ValueError('Unqualified SRAM placement or net metadata')
        loads = sorted(r['instance'] + '/' + r['pin'] for r in by_net[net] if r['io_type'] == 'INPUT')
        if len(loads) != 4 or len(by_net[net]) != 5 or any(p['net'] == net for p in ports):
            raise ValueError('Require four real input loads and one SRAM driver, no top port')
        match_pin = re.search(r'PIN ' + re.escape(pin) + r'\s+(.*?)END ' + re.escape(pin), lef_text, re.S)
        boxes = re.findall(r'RECT\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*;', match_pin[1] if match_pin else '')
        if len(boxes) != 1 or 'LAYER Metal2' not in match_pin[1]:
            raise ValueError('Require one known Metal2 SRAM pin rectangle')
        x1, y1, x2, y2 = map(float, boxes[0])
        if y1 != 0 or y2 != 0.26 or x1 >= x2:
            raise ValueError('Pin is not on the diagnosed macro bottom edge')
        diagnosed.append({'bank': bank, 'bit': bit, 'instance': driver['instance'], 'pin': pin, 'net': net,
                          'buffer': f'eco_sram_cap_b{bank}_d{bit:02d}', 'loads': loads,
                          'reported_limit_pf': float(limit), 'reported_actual_pf': float(actual),
                          'pin_center_x_dbu': int(inst['xmin']) + round((x1 + x2) * 500),
                          'macro_bottom_y_dbu': int(inst['ymin']), 'pin_local_rectangle_um': [x1, y1, x2, y2]})
    if len(diagnosed) != 64 or {(d['bank'], d['bit']) for d in diagnosed} != expected:
        raise ValueError('Require exactly all 64 diagnosed SRAM outputs')
    limits = {}
    library_files = [lef]
    for corner, std_suffix, sram_suffix in [('tt', 'typ_1p20V_25C', 'typ_1p20V_25C'), ('ff', 'fast_1p32V_m40C', 'fast_1p32V_m55C')]:
        std = root / f'upstream/croc/technology/lib/sg13g2_stdcell_{std_suffix}.lib'
        sram = root / f'upstream/croc/technology/lib/RM_IHPSG13_1P_512x32_c2_bm_bist_{sram_suffix}.lib'
        library_files += [std, sram]
        cells = [body for name, body in groups(std.read_text(), 'cell') if name == 'sg13g2_buf_4']
        pins = {name: body for name, body in groups(cells[0], 'pin', direct=True)}
        buses = [body for name, body in groups(sram.read_text(), 'bus') if name == 'A_DOUT']
        maximum = float(attribute(buses[0], 'max_capacitance'))
        input_max = max(float(attribute(pins['A'], key)) for key in ('capacitance', 'rise_capacitance', 'fall_capacitance'))
        output_max = float(attribute(pins['X'], 'max_capacitance'))
        if (len(cells) != 1 or len(buses) != 1 or maximum != 0.064 or not 0 < input_max < maximum
                or not max(d['reported_actual_pf'] for d in diagnosed) < output_max
                or attribute(pins['X'], 'function') != 'A'):
            raise ValueError('Actual buffer input/output capability or scalar identity unqualified')
        limits[corner] = {'sram_max_cap_pf': maximum, 'buffer_max_input_cap_pf': input_max,
                          'buffer_max_output_cap_pf': output_max, 'buffer_function': 'A',
                          'buffer_area_um2': float(attribute(cells[0], 'area'))}
    return {'branches': sorted(diagnosed, key=lambda d: (d['bank'], d['bit'])), 'buffer_master': 'sg13g2_buf_4',
            'library_limits': limits, 'library_files': [str(p.relative_to(root)) for p in library_files]}


EDIT = r"""# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
source /output/capture_placement.tcl
read_db /output/inputs/cts.odb
read_sdc /output/inputs/cts.sdc
setDefaultParasitics
set_propagated_clock [all_clocks]
estimate_parasitics -placement
verify_placement_ports
capture_placement before
report_metrics before_cts
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/before_electrical_violators.rpt
set block [ord::get_db_block]
set master [[ord::get_db] findMaster sg13g2_buf_4]
if {$master eq "NULL"} {error "Missing actual buffer master"}
# Freeze original standard-cell geometry only during legalization; restore each
# exact placement status in the fresh checker before final evidence capture.
set original [open /output/original_core_status.tsv w]
puts $original "instance\tstatus"
foreach inst [$block getInsts] {
    if {[[$inst getMaster] getType] eq "CORE"} {
        puts $original "[$inst getName]\t[$inst getPlacementStatus]"
        $inst setPlacementStatus FIRM
    }
}
close $original
set planned [open /output/planned_branches.tsv r]
gets $planned header
set moved [open /output/eco_loads.tsv w]
puts $moved "buffer\toriginal_net\tload_pin"
set made 0
while {[gets $planned line] >= 0} {
    lassign [split $line \t] instance pin net_name name xcenter bottom
    set inst [$block findInst $instance]
    if {$inst eq "NULL"} {error "Missing original SRAM instance"}
    set driver [$inst findITerm $pin]
    if {$driver eq "NULL" || [$driver getIoType] ne "OUTPUT"} {error "Invalid SRAM driver"}
    set net [$driver getNet]
    if {$net eq "NULL" || [$net getName] ne $net_name || [$net getSigType] ne "SIGNAL" || [$net getNonDefaultRule] ne "NULL"} {error "SRAM net metadata changed"}
    set loads {}
    foreach term [$net getITerms] {
        if {[$term getIoType] eq "INPUT"} {lappend loads $term}
    }
    if {[llength $loads] != 4 || [llength [$net getITerms]] != 5 || [llength [$net getBTerms]] != 0} {error "SRAM fanout changed"}
    if {[$block findInst $name] ne "NULL" || [$block findNet $name] ne "NULL"} {error "ECO identity collision"}
    set buf [odb::dbInst_create $block $master $name]
    $buf setLocation [expr {int($xcenter - [$master getWidth]/2)}] [expr {int($bottom - 2*[$master getHeight])}]
    $buf setPlacementStatus PLACED
    set output [odb::dbNet_create $block $name]
    $output setSigType SIGNAL
    [$buf findITerm A] connect $net
    [$buf findITerm X] connect $output
    foreach term $loads {
        set identity "[[$term getInst] getName]/[[$term getMTerm] getName]"
        $term disconnect
        $term connect $output
        puts $moved "$name\t$net_name\t$identity"
    }
    foreach pg {VDD VSS} {
        set term [$buf findITerm $pg]
        set supply [$block findNet $pg]
        if {$term eq "NULL" || $supply eq "NULL"} {error "Missing explicit buffer supply"}
        $term connect $supply
    }
    incr made
}
close $planned
close $moved
if {$made != 64} {error "Expected exactly 64 SRAM output buffers"}
write_db /output/eco_unplaced.odb
puts {SRAM_CAP_EDIT_COMPLETE}
"""

def run(root, run_id):
    if not re.fullmatch(r'croc-full-io-sram-cap-[a-zA-Z0-9_-]+', run_id):
        raise ValueError('Independent SRAM cap run ID required')
    source = root / 'runs/croc-full-io-cts-fanout-20260910-001'
    gate_path = root / 'reports/placement/full-io-cts-fanout-audit-20260910-001.json'
    gate = json.loads(gate_path.read_text())
    if gate.get('overall_result') != 'PASS' or gate.get('run_id') != source.name:
        raise ValueError('Current source CTS structural prerequisite failed')
    for rel, digest in gate['source_sha256'].items():
        if sha(root / rel) != digest:
            raise ValueError('Prerequisite evidence changed: ' + rel)
    diagnosed = diagnosis(root, source)
    dest = root / 'runs' / run_id
    dest.mkdir(exist_ok=False)
    work = dest / 'work/openroad'
    (work / 'scripts').mkdir(parents=True)
    (dest / 'inputs').mkdir()
    sources = {str(gate_path.relative_to(root)): sha(gate_path)}
    def copy(path, target):
        shutil.copyfile(path, target)
        sources[str(path.relative_to(root))] = sha(path)
    for path in sorted((source / 'work/openroad/scripts').iterdir()):
        if path.is_file():
            copy(path, work / 'scripts' / path.name)
    copy(source / 'cts.odb', dest / 'inputs/cts.odb')
    copy(source / 'after.sdc', dest / 'inputs/cts.sdc')
    for name in ('manifest.json', 'electrical_violators.rpt', 'after_iterms.tsv'):
        sources[str((source / name).relative_to(root))] = sha(source / name)
    for name in ('scripts/run_croc_sram_cap.py', 'scripts/run_croc_full_cts.py',
                 'scripts/audit_croc_placement_structure.py', 'scripts/validate_croc_clock_eco.py', 'scripts/run_io_ring_floorplan.py',
                 'scripts/run_io_ring_maximal_diagnostic.py', 'upstream/croc/env.sh'):
        sources[name] = sha(root / name)
    for folder in ('lef', 'lib'):
        for path in sorted((root / 'upstream/croc/technology' / folder).glob('*')):
            if path.is_file():
                sources[str(path.relative_to(root))] = sha(path)
    write(dest / 'diagnosed_branches.json', diagnosed)
    (dest / 'capture_placement.tcl').write_text(CAPTURE)
    (dest / 'after_placement.tcl').write_text(AFTER)
    (dest / 'edit.tcl').write_text(EDIT)
    with (dest / 'planned_branches.tsv').open('x') as handle:
        handle.write('instance\tpin\tnet\tbuffer\tpin_center_x_dbu\tmacro_bottom_y_dbu\n')
        for row in diagnosed['branches']:
            handle.write('\t'.join(str(row[key]) for key in ('instance', 'pin', 'net', 'buffer', 'pin_center_x_dbu', 'macro_bottom_y_dbu')) + '\n')
    check = '''# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
source /output/capture_placement.tcl
read_db /output/eco_unplaced.odb
read_sdc /output/inputs/cts.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
set_propagated_clock [all_clocks]
detailed_placement
set original [open /output/original_core_status.tsv r]
gets $original header
set block [ord::get_db_block]
while {[gets $original line] >= 0} {
    lassign [split $line \t] name status
    set inst [$block findInst $name]
    if {$inst eq "NULL"} {error "Original CORE disappeared"}
    $inst setPlacementStatus $status
}
close $original
estimate_parasitics -placement
source /output/after_placement.tcl
report_metrics after_cts
write_db /output/cts.odb
puts {FULL_SRAM_CAP_ECO_COMPLETE}
'''
    (dest / 'check.tcl').write_text(check)
    (dest / 'execute.sh').write_text('set -e\nsource /work/upstream/croc/env.sh\nopenroad -exit /output/edit.tcl\nopenroad -exit /output/check.tcl\n')
    command = ['docker', 'run', '--name', run_id, '--cpus', '2', '--memory', '6g', '--ulimit', 'core=0',
               '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp', '-e', 'QT_QPA_PLATFORM=offscreen',
               '-e', 'CROC_PDK=sg13g2', '-e', 'CROC_SKIP_TECH_SETUP=1', '--entrypoint', '/bin/bash',
               '-v', f'{root}:/work:ro', '-v', f'{dest}:/output:rw', '-w', '/output/work/openroad', IMAGE,
               '-lc', 'timeout --verbose --signal=TERM --kill-after=15s 180s /bin/bash /output/execute.sh']
    manifest = {'schema_version': '1.0.0', 'run_id': run_id, 'source_run': source.name, 'started_at': now(),
                'status': 'running', 'classification': 'sram_output_cap_eco_candidate_not_route_or_signoff',
                'source_sha256': sources, 'command': command,
                'generated_inputs_sha256': {str(p.relative_to(dest)): sha(p) for p in dest.rglob('*') if p.is_file()},
                'limits': {'cpus': 2, 'memory_gb': 6, 'inner_seconds': 180, 'kill_grace_seconds': 15, 'outer_seconds': 215},
                'io_load_constraint_unchanged': True, 'original_layout_modified': False,
                'route_performed': False, 'public_rule_signoff': False, 'routing_ndr_policy_qualification': 'UNVERIFIED'}
    write(dest / 'manifest.json', manifest)
    start = time.monotonic()
    samples, outer_expired = [], False
    print(json.dumps({'run_id': run_id, 'status': 'starting', 'diagnosed_branches': len(diagnosed['branches'])}), flush=True)
    with (dest / 'tool.log').open('x') as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if time.monotonic() - start > 215:
                outer_expired = True
                stop = subprocess.run(['docker', 'stop', '--time', '5', run_id], capture_output=True, text=True, timeout=15)
                manifest['outer_stop_returncode'] = stop.returncode
                break
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                samples.append(observe(run_id))
                write(dest / 'resource_samples.json', samples)
                print(json.dumps({'run_id': run_id, 'elapsed_seconds': round(time.monotonic() - start, 1)}), flush=True)
        try:
            returncode = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            returncode = process.wait(timeout=10)
    terminal = observe(run_id)
    write(dest / 'terminal_observation.json', terminal)
    write(dest / 'resource_samples.json', samples)
    state = terminal.get('state', {})
    log = (dest / 'tool.log').read_text(errors='replace')
    complete = bool(returncode == 0 and state.get('Status') == 'exited' and state.get('ExitCode') == 0
                    and state.get('OOMKilled') is False and not outer_expired
                    and 'FULL_SRAM_CAP_ECO_COMPLETE' in log and (dest / 'cts.odb').is_file())
    manifest.update(returncode=returncode, status='completed' if complete else 'failed', execution_complete=complete,
                    finished_at=now(), elapsed_seconds=time.monotonic() - start, outer_timeout_expired=outer_expired,
                    terminal_container_state=state, source_hashes_unchanged=all(sha(root / p) == v for p, v in sources.items()),
                    design_checks_require_independent_audit=True)
    if state.get('Status') == 'exited' and state.get('Running') is False:
        manifest['cleanup_returncode'] = subprocess.run(['docker', 'rm', run_id], capture_output=True, text=True, timeout=15).returncode
    else:
        manifest['cleanup_returncode'] = None
    manifest['outputs_sha256'] = {str(p.relative_to(dest)): sha(p) for p in dest.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    write(dest / 'manifest.json', manifest)
    print(json.dumps({key: manifest[key] for key in ('run_id', 'status', 'returncode', 'elapsed_seconds', 'terminal_container_state')}), flush=True)
    return 0 if complete else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id))
