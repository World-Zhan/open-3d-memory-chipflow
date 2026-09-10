#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded single-factor bondpad direction experiments; analysis views only."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from run_io_ring_floorplan import IMAGE, now, sha, write
from run_io_ring_maximal_diagnostic import observe

SOURCE = 'runs/croc-placement-sta-readback-20260909-001/candidate'
PAD_LEF = 'runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.lef'

TINY_DEF = '''VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN direction_fixture ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 250000 250000 ) ;
COMPONENTS 3 ;
- bond bondpad70_m2_ring + FIXED ( 0 0 ) N ;
- io sg13g2_IOPadIn + FIXED ( 0 75000 ) N ;
- ff sg13g2_dfrbpq_1 + PLACED ( 100000 75000 ) N ;
END COMPONENTS
PINS 4 ;
- clk + NET clk + DIRECTION INPUT + USE SIGNAL
  + PORT + LAYER Metal2 ( 0 0 ) ( 1000 1000 ) + FIXED ( 30000 30000 ) N ;
- d + NET d + DIRECTION INPUT + USE SIGNAL
  + PORT + LAYER Metal2 ( 0 0 ) ( 1000 1000 ) + FIXED ( 120000 75000 ) N ;
- r + NET r + DIRECTION INPUT + USE SIGNAL
  + PORT + LAYER Metal2 ( 0 0 ) ( 1000 1000 ) + FIXED ( 120000 80000 ) N ;
- q + NET q + DIRECTION OUTPUT + USE SIGNAL
  + PORT + LAYER Metal2 ( 0 0 ) ( 1000 1000 ) + FIXED ( 120000 85000 ) N ;
END PINS
NETS 5 ;
- clk ( PIN clk ) ( bond pad ) ( io pad ) + USE CLOCK ;
- coreclk ( io p2c ) ( ff CLK ) + USE CLOCK ;
- d ( PIN d ) ( ff D ) + USE SIGNAL ;
- r ( PIN r ) ( ff RESET_B ) + USE SIGNAL ;
- q ( PIN q ) ( ff Q ) + USE SIGNAL ;
END NETS
END DESIGN
'''

TINY_SDC = '''create_clock -name sys -period 10 [get_ports clk]
set_clock_transition 0.2 [get_clocks sys]
set_input_delay 1 -clock sys [get_ports d]
set_output_delay 1 -clock sys [get_ports q]
set_case_analysis 1 [get_ports r]
set_load 0.01 [get_ports q]
'''

API = r'''
help report_power > /output/power_command_help.rpt
help set_power_activity > /output/activity_command_help.rpt
set f [open /output/activity_command_body.tcl w]
puts $f [info body sta::set_power_activity]
close $f
'''

CAPTURE = r'''
set f [open /output/bondpad_directions.tsv w]
puts $f "instance\tmaster\tpin\tdirection\tnet"
set block [ord::get_db_block]
foreach inst [$block getInsts] {
    if {[[$inst getMaster] getName] eq "bondpad70_m2_ring"} {
        foreach it [$inst getITerms] {
            set mt [$it getMTerm]
            set net [$it getNet]
            set netname ""
            if {$net ne "NULL"} {set netname [$net getName]}
            puts $f "[$inst getName]\tbondpad70_m2_ring\t[$mt getName]\t[$mt getIoType]\t$netname"
        }
    }
}
close $f
write_def /output/readback.def
write_sdc /output/readback.sdc
write_verilog /output/readback.v
report_clock_properties > /output/clocks.rpt
report_power -corner tt -digits 8 > /output/power_tt.rpt
report_activity_annotation -report_annotated > /output/activity_annotation.rpt
'''


def direction_lef(text, direction):
    if direction not in ('INPUT', 'INOUT'):
        raise ValueError('Unsupported analysis direction')
    if text.count('DIRECTION INOUT ;') != 1:
        raise ValueError('Expected precisely one original INOUT declaration')
    return text.replace('DIRECTION INOUT ;', f'DIRECTION {direction} ;')


def power_groups(text):
    groups = {}
    for line in text.splitlines():
        match = re.fullmatch(r'(Sequential|Combinational|Clock|Macro|Pad|Total)\s+(.+?)\s+\d+(?:\.\d+)?%', line.strip())
        if match:
            values = [float(x) for x in match[2].split()]
            if len(values) == 4:
                groups[match[1]] = dict(zip(('internal_w', 'switching_w', 'leakage_w', 'total_w'), values))
    return groups


def prepare(root, dest, mode, direction):
    output = dest / direction.lower()
    output.mkdir()
    (output / 'bondpad.lef').write_text(direction_lef((root / PAD_LEF).read_text(), direction))
    sources = {PAD_LEF: sha(root / PAD_LEF), 'upstream/croc/env.sh': sha(root / 'upstream/croc/env.sh')}
    if mode == 'tiny':
        (output / 'input.def').write_text(TINY_DEF)
        (output / 'input.sdc').write_text(TINY_SDC)
        prefix = '''set_thread_count 2
define_corners tt
read_liberty -corner tt /work/upstream/croc/technology/lib/sg13g2_stdcell_typ_1p20V_25C.lib
read_liberty -corner tt /work/upstream/croc/technology/lib/sg13g2_io_typ_1p2V_3p3V_25C.lib
read_lef /work/upstream/croc/technology/lef/sg13g2_tech.lef
read_lef /work/upstream/croc/technology/lef/sg13g2_stdcell.lef
read_lef /work/upstream/croc/technology/lef/sg13g2_io.lef
read_lef /output/bondpad.lef
read_def /output/input.def
read_sdc /output/input.sdc
'''
        for name in ('lib/sg13g2_stdcell_typ_1p20V_25C.lib', 'lib/sg13g2_io_typ_1p2V_3p3V_25C.lib', 'lef/sg13g2_tech.lef', 'lef/sg13g2_stdcell.lef', 'lef/sg13g2_io.lef'):
            path = 'upstream/croc/technology/' + name
            sources[path] = sha(root / path)
        suffix = '''report_power -instances [get_cells ff] -corner tt -digits 8 > /output/ff_power_tt.rpt
puts POWER_DIRECTION_AB_COMPLETE
'''
        cwd = '/output'
    else:
        source = root / SOURCE
        work = output / 'work/openroad'
        work.mkdir(parents=True)
        shutil.copytree(source / 'work/openroad/scripts', work / 'scripts')
        for path in sorted((source / 'work/openroad/scripts').glob('*.tcl')):
            sources[str(path.relative_to(root))] = sha(path)
        for rel in ('inputs/02_croc.placed.def', 'inputs/02_croc.placed.sdc'):
            sources[SOURCE + '/' + rel] = sha(source / rel)
        for kind in ('lib', 'lef'):
            for path in sorted((root / 'upstream/croc/technology' / kind).glob('*')):
                if path.is_file():
                    sources[str(path.relative_to(root))] = sha(path)
        prefix = '''source scripts/startup.tcl
set_thread_count 2
read_lef /output/bondpad.lef
read_def /work/''' + SOURCE + '''/inputs/02_croc.placed.def
read_sdc /work/''' + SOURCE + '''/inputs/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
estimate_parasitics -placement
'''
        suffix = '''set srams [get_cells -quiet -filter {ref_name == RM_IHPSG13_1P_512x32_c2_bm_bist} *]
report_power -instances $srams -corner tt -digits 8 > /output/sram_power_tt.rpt
report_power -corner ff -digits 8 > /output/power_ff.rpt
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical_violators.rpt
puts POWER_DIRECTION_AB_COMPLETE
'''
        cwd = '/output/work/openroad'
    (output / 'probe.tcl').write_text(prefix + API + CAPTURE + suffix)
    return output, cwd, sources


def run(root, run_id, mode):
    if not re.fullmatch(r'croc-power-direction-' + mode + r'-[A-Za-z0-9_-]+', run_id):
        raise ValueError('Unique mode-specific run ID required')
    dest = root / 'runs' / run_id
    dest.mkdir(exist_ok=False)
    inner = 30 if mode == 'tiny' else 180
    manifest = {'schema_version': '1.0.0', 'run_id': run_id, 'mode': mode, 'started_at': now(),
        'classification': 'single_factor_direction_analysis_not_design_fix_or_workload_power',
        'status': 'preparing', 'source_sha256': {'scripts/run_croc_power_direction_ab.py': sha(Path(__file__))},
        'arms': {}, 'fixed_image': IMAGE, 'fixed_tool_expected': 'v2.0-27244-gfecb04286',
        'original_layout_modified': False, 'source_pdk_modified': False,
        'activity': 'tool_default_no_workload', 'workload_power_w': None, 'public_rule_signoff': False,
        'limits_per_arm': {'cpus': 2, 'memory_gb': 4, 'inner_seconds': inner, 'outer_seconds': inner + 35}}
    for direction in ('INOUT', 'INPUT'):
        output, cwd, sources = prepare(root, dest, mode, direction)
        manifest['source_sha256'].update(sources)
        container = run_id + '-' + direction.lower()
        command = ['docker', 'run', '--name', container, '--cpus', '2', '--memory', '4g', '--ulimit', 'core=0',
            '--user', '1000:1000', '-e', 'HOME=/tmp', '-e', 'CROC_PDK=sg13g2', '-e', 'CROC_SKIP_TECH_SETUP=1',
            '--entrypoint', '/bin/bash', '-v', f'{root}:/work:ro', '-v', f'{output}:/output:rw', '-w', cwd, IMAGE,
            '-lc', f'source /work/upstream/croc/env.sh && timeout --verbose --signal=TERM --kill-after=10s {inner}s openroad -exit /output/probe.tcl']
        manifest['arms'][direction.lower()] = {'container': container, 'command': command, 'status': 'pending',
            'generated_input_sha256': {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}}
    manifest['status'] = 'running'
    write(dest / 'manifest.json', manifest)
    for name, arm in manifest['arms'].items():
        output = dest / name
        start = time.monotonic()
        with (output / 'tool.log').open('x') as log:
            proc = subprocess.Popen(arm['command'], stdout=log, stderr=subprocess.STDOUT)
            try:
                rc = proc.wait(timeout=inner + 35)
                outer = False
            except subprocess.TimeoutExpired:
                outer = True
                subprocess.run(['docker', 'stop', '-t', '10', arm['container']], capture_output=True, timeout=20)
                rc = proc.wait(timeout=20)
        observation = observe(arm['container'])
        write(output / 'terminal_observation.json', observation)
        state = observation.get('state', {})
        text = (output / 'tool.log').read_text(errors='replace')
        complete = bool(rc == 0 and not outer and state.get('Status') == 'exited' and state.get('ExitCode') == 0
            and state.get('Running') is False and state.get('OOMKilled') is False and 'POWER_DIRECTION_AB_COMPLETE' in text)
        arm.update(returncode=rc, outer_timeout_expired=outer, terminal_container_state=state,
            elapsed_seconds=time.monotonic() - start, execution_complete=complete,
            status='completed' if complete else 'failed')
        if state.get('Status') == 'exited' and state.get('Running') is False:
            arm['cleanup_returncode'] = subprocess.run(['docker', 'rm', arm['container']], capture_output=True, timeout=15).returncode
        arm['outputs_sha256'] = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
        for corner in ('tt', 'ff'):
            path = output / f'power_{corner}.rpt'
            if path.exists():
                arm['raw_power_' + corner] = power_groups(path.read_text())
        write(dest / 'manifest.json', manifest)
        print(json.dumps({'arm': name, 'status': arm['status'], 'elapsed_seconds': arm['elapsed_seconds'], 'raw_power_tt': arm.get('raw_power_tt')}), flush=True)
        if not complete:
            # Do not spend a second EDA process on an invalid fixture.
            break
    complete = all(a.get('execution_complete') for a in manifest['arms'].values())
    manifest.update(finished_at=now(), status='completed' if complete else 'failed',
        source_hashes_unchanged=all(sha(root / p) == h for p, h in manifest['source_sha256'].items()))
    write(dest / 'manifest.json', manifest)
    return 0 if complete else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=('tiny', 'full'), required=True)
    args = parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id, args.mode))
