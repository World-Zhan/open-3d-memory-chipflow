#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Official IHP IO suite: interface audit, behavioral simulation and tiny STA."""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from audit_croc_placement_structure import groups, attribute
from run_io_ring_floorplan import now, sha, write, IMAGE
from run_io_ring_maximal_diagnostic import observe

SUITE = 'upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io'
TECH = 'upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef'
GATE = 'reports/ppa/ihp-io-suite-candidate-20260910-001.json'
CELLS = ('sg13g2_IOPadIn', 'sg13g2_IOPadOut16mA', 'sg13g2_IOPadInOut30mA')
CORNERS = {'tt': 'typ_1p2V_3p3V_25C', 'ff': 'fast_1p32V_3p6V_m40C', 'ss': 'slow_1p08V_3p0V_125C'}
PG = {'vdd': 'POWER', 'vss': 'GROUND', 'iovdd': 'POWER', 'iovss': 'GROUND'}

TB = r'''`timescale 1ns/1ps
module tb;
  supply1 vdd, iovdd;
  supply0 vss, iovss;
  reg in_value, out_value, core_value, enable, ext_enable, ext_value;
  wire in_core, out_pad, bi_core;
  tri bi_pad;
  assign bi_pad = ext_enable ? ext_value : 1'bz;
  sg13g2_IOPadIn dut_in(.pad(in_value),.p2c(in_core),.vdd(vdd),.vss(vss),.iovdd(iovdd),.iovss(iovss));
  sg13g2_IOPadOut16mA dut_out(.pad(out_pad),.c2p(out_value),.vdd(vdd),.vss(vss),.iovdd(iovdd),.iovss(iovss));
  sg13g2_IOPadInOut30mA dut_bi(.pad(bi_pad),.c2p(core_value),.p2c(bi_core),.c2p_en(enable),.vdd(vdd),.vss(vss),.iovdd(iovdd),.iovss(iovss));
  integer assertions=0, failures=0, i, j, k, l;
  reg expected;
  task check;
    input actual, wanted;
    input [255:0] label;
    begin
      assertions=assertions+1;
      if (actual !== wanted) begin
        failures=failures+1;
        $display("MISMATCH %0s actual=%b expected=%b",label,actual,wanted);
      end
    end
  endtask
  initial begin
    $dumpfile("/output/wave.vcd"); $dumpvars(0,tb);
    enable=0;ext_enable=0;ext_value=0;core_value=0;in_value=0;out_value=0;
    for(i=0;i<4;i=i+1) begin
      case(i) 0:begin in_value=0;out_value=0;end
              1:begin in_value=1;out_value=1;end
              2:begin in_value=1'bx;out_value=1'bx;end
              3:begin in_value=1'bz;out_value=1'bz;end endcase
      #1;check(in_core,in_value,"input four-state transfer");check(out_pad,out_value,"output four-state transfer");
    end
    for(i=0;i<2;i=i+1) for(j=0;j<2;j=j+1) for(k=0;k<2;k=k+1) for(l=0;l<2;l=l+1) begin
      enable=i;core_value=j;ext_enable=k;ext_value=l;
      if(i==0 && k==0) expected=1'bz;
      else if(i==0) expected=l;
      else if(k==0) expected=j;
      else if(j==l) expected=j;
      else expected=1'bx;
      #1;check(bi_pad,expected,"bidirectional resolved pad");check(bi_core,expected,"bidirectional receiver");
      $display("BIDIR en=%b core=%b ext_en=%b ext=%b pad=%b rx=%b expected=%b",enable,core_value,ext_enable,ext_value,bi_pad,bi_core,expected);
    end
    enable=1'bx;ext_enable=0;core_value=1;#1;
    check(bi_pad,1'bx,"unknown enable pad");check(bi_core,1'bx,"unknown enable receiver");
    $display("ASSERTIONS=%0d FAILURES=%0d",assertions,failures);
    if(failures!=0) $fatal(1,"OFFICIAL_IO_BEHAVIOR_FAIL");
    $display("OFFICIAL_IO_BEHAVIOR_PASS");$finish;
  end
endmodule
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def one(pattern, text, flags=0):
    matches = re.findall(pattern, text, flags)
    require(len(matches) == 1, 'Expected exactly one interface block: ' + pattern)
    return matches[0]


def interfaces(root):
    base = root / SUITE
    verilog = (base / 'verilog/sg13g2_io.v').read_text()
    cdl = (base / 'cdl/sg13g2_io.cdl').read_text()
    lef = (base / 'lef/sg13g2_io.lef').read_text()
    libraries = {corner: dict(groups((base / f'lib/sg13g2_io_{file}.lib').read_text(), 'cell')) for corner, file in CORNERS.items()}
    result = {}
    for cell in CELLS:
        module = one(r'\bmodule\s+' + cell + r'\s*\((.*?)\);(.*?)\bendmodule', verilog, re.S)
        vports = [p.strip() for p in module[0].split(',')]
        vdirs = dict((name, direction.upper()) for direction, name in re.findall(r'\b(input|output|inout)\s+(\w+)\s*;', module[1]))
        cports = one(r'^\.SUBCKT\s+' + cell + r'\s+([^\n]+)', cdl, re.M | re.I).split()
        lbody = one(r'^MACRO\s+' + cell + r'\s*\n(.*?)^END\s+' + cell + r'\s*$', lef, re.M | re.S)
        lpins = {}
        for name, body in re.findall(r'^\s*PIN\s+(\w+)\s*\n(.*?)^\s*END\s+\1\s*$', lbody, re.M | re.S):
            require(name not in lpins, 'Duplicate LEF pin')
            lpins[name] = {'direction': one(r'DIRECTION\s+(\w+)\s*;', body), 'use': one(r'USE\s+(\w+)\s*;', body)}
        require(vports == cports, 'CDL and Verilog terminal order differ: ' + cell)
        require(set(vports) == set(vdirs) == set(lpins), 'LEF/Verilog port set differs: ' + cell)
        require(all(lpins[p]['direction'] == vdirs[p] for p in vports), 'LEF/Verilog direction differs: ' + cell)
        per_corner = {}
        for corner, library in libraries.items():
            body = library[cell]
            pins = {name: {key: attribute(payload, key) for key in ('direction', 'function', 'three_state', 'clock', 'max_capacitance', 'related_power_pin', 'related_ground_pin')}
                for name, payload in groups(body, 'pin', direct=True)}
            power = {name: attribute(payload, 'pg_type') for name, payload in groups(body, 'pg_pin', direct=True)}
            require(set(pins) | set(power) == set(vports) and set(power) == set(PG), 'Liberty PG/port mismatch: ' + cell)
            require(all(pins[p]['direction'].upper() == vdirs[p] for p in pins), 'Liberty direction mismatch: ' + cell)
            require(all(lpins[p]['use'] == use and power[p] == ('primary_power' if use == 'POWER' else 'primary_ground') for p, use in PG.items()), 'PG use/type mismatch: ' + cell)
            require(all(p['related_power_pin'] in ('vdd', 'iovdd') and p['related_ground_pin'] in ('vss', 'iovss') for p in pins.values()), 'Unbound signal PG domain')
            per_corner[corner] = {'signals': pins, 'pg_types': power}
        signatures = [{p: {k: v for k, v in desc.items() if k != 'max_capacitance'} for p, desc in view['signals'].items()} for view in per_corner.values()]
        require(signatures[0] == signatures[1] == signatures[2], 'Corner logical interfaces disagree')
        result[cell] = {'ordered_verilog_cdl_ports': vports, 'verilog_directions': vdirs, 'lef': lpins, 'liberty': per_corner}
    return {'result': 'PASS', 'scope': 'interface_and_PG_metadata_only_not_circuit_LVS', 'cells': result}


def tiny_def():
    specs = [
        ('out16', CELLS[1], {'pad': ('out_pad', 'OUTPUT'), 'c2p': ('out_core', 'INPUT')}),
        ('bi_tx', CELLS[2], {'pad': ('bi_tx_pad', 'OUTPUT'), 'c2p': ('bi_tx_core', 'INPUT'), 'p2c': ('bi_tx_rx', 'OUTPUT'), 'c2p_en': ('bi_tx_en', 'INPUT')}),
        ('bi_rx', CELLS[2], {'pad': ('bi_rx_pad', 'INPUT'), 'c2p': ('bi_rx_core', 'INPUT'), 'p2c': ('bi_rx_rx', 'OUTPUT'), 'c2p_en': ('bi_rx_en', 'INPUT')}),
        ('bi_z', CELLS[2], {'pad': ('bi_z_pad', 'OUTPUT'), 'c2p': ('bi_z_core', 'INPUT'), 'p2c': ('bi_z_rx', 'OUTPUT'), 'c2p_en': ('bi_z_en', 'INPUT')}),
        ('in_data', CELLS[0], {'pad': ('in_pad', 'INPUT'), 'p2c': ('in_core', 'OUTPUT')}),
        ('in_clock', CELLS[0], {'pad': ('clk_pad', 'INPUT'), 'p2c': ('clk_core', 'OUTPUT')})]
    components = [f'- {name} {cell} + FIXED ( {i * 100000} 0 ) N ;' for i, (name, cell, _) in enumerate(specs)]
    pins, nets = [], []
    for name, _, mapping in specs:
        for pin, (net, direction) in mapping.items():
            pins.append(f'- {net} + NET {net} + DIRECTION {direction} + USE SIGNAL + PORT + LAYER Metal2 ( 0 0 ) ( 1000 1000 ) + FIXED ( 0 250000 ) N ;')
            nets.append(f'- {net} ( PIN {net} ) ( {name} {pin} ) + USE SIGNAL ;')
    special = []
    for name, use in PG.items():
        pins.append(f'- {name} + NET {name} + DIRECTION INOUT + USE {use} + PORT + LAYER Metal3 ( 0 0 ) ( 1000 1000 ) + FIXED ( 0 260000 ) N ;')
        special.append(f'- {name} ( PIN {name} ) ' + ' '.join(f'( {inst} {name} )' for inst, _, _ in specs) + f' + USE {use} ;')
    return '\n'.join(['VERSION 5.8 ;', 'DIVIDERCHAR "/" ;', 'BUSBITCHARS "[]" ;', 'DESIGN ihp_io_suite_tiny ;',
        'UNITS DISTANCE MICRONS 1000 ;', 'DIEAREA ( 0 0 ) ( 700000 300000 ) ;', f'COMPONENTS {len(components)} ;', *components,
        'END COMPONENTS', f'PINS {len(pins)} ;', *pins, 'END PINS', f'NETS {len(nets)} ;', *nets, 'END NETS',
        f'SPECIALNETS {len(special)} ;', *special, 'END SPECIALNETS', 'END DESIGN', ''])


SDC = '''create_clock -name clk_sys -period 10 [get_ports clk_pad]
set_clock_transition 0.2 [get_clocks clk_sys]
set_clock_uncertainty 0.1 [get_clocks clk_sys]
set_max_transition 1.2 [current_design]
set_input_transition 0.2 [get_ports {out_core bi_tx_core bi_rx_core bi_z_core bi_tx_en bi_rx_en bi_z_en}]
set_driving_cell [get_ports {in_pad bi_rx_pad}] -lib_cell sg13g2_IOPadOut16mA -pin pad
set_load 15 [get_ports {out_pad bi_tx_pad bi_rx_pad bi_z_pad}]
set_load 0.05 [get_ports {in_core clk_core bi_tx_rx bi_rx_rx bi_z_rx}]
set_case_analysis 1 [get_ports bi_tx_en]
set_case_analysis 0 [get_ports {bi_rx_en bi_z_en}]
set_input_delay -min -clock clk_sys 1 [get_ports {out_core bi_tx_core bi_rx_pad in_pad}]
set_input_delay -max -clock clk_sys 3 [get_ports {out_core bi_tx_core bi_rx_pad in_pad}]
set_output_delay -min -clock clk_sys 1 [get_ports {out_pad bi_tx_pad bi_rx_rx in_core}]
set_output_delay -max -clock clk_sys 3 [get_ports {out_pad bi_tx_pad bi_rx_rx in_core}]
'''


def sta_tcl(corner):
    return f'''set_thread_count 2
define_corners {corner}
read_liberty -corner {corner} /work/{SUITE}/lib/sg13g2_io_{CORNERS[corner]}.lib
read_lef /work/{TECH}
read_lef /work/{SUITE}/lef/sg13g2_io.lef
read_def /output/input.def
read_sdc /output/input.sdc
help report_check_types > /output/check_help.rpt
report_check_types -max_slew -max_capacitance -max_fanout -digits 8 > /output/electrical_all.rpt
report_check_types -max_slew -max_capacitance -max_fanout -violators -digits 8 > /output/electrical_violators.rpt
report_checks -from [get_ports out_core] -to [get_ports out_pad] -path_delay min_max -format full_clock_expanded -fields {{slew cap fanout}} -digits 8 > /output/out16_path.rpt
report_checks -from [get_ports bi_tx_core] -to [get_ports bi_tx_pad] -path_delay min_max -format full_clock_expanded -fields {{slew cap fanout}} -digits 8 > /output/bidir_tx_path.rpt
report_checks -from [get_ports bi_rx_pad] -to [get_ports bi_rx_rx] -path_delay min_max -format full_clock_expanded -fields {{slew cap fanout}} -digits 8 > /output/bidir_rx_path.rpt
report_checks -from [get_ports in_pad] -to [get_ports in_core] -path_delay min_max -format full_clock_expanded -fields {{slew cap fanout}} -digits 8 > /output/input_path.rpt
report_checks -from [get_ports bi_z_core] -to [get_ports bi_z_pad] -unconstrained -path_delay min_max -fields {{slew cap fanout}} -digits 8 > /output/bidir_highz_path.rpt
report_clock_properties > /output/clocks.rpt
report_case_analysis > /output/case_analysis.rpt
check_setup -verbose > /output/constraints.rpt
report_power -corner {corner} -digits 8 > /output/raw_default_power.rpt
write_sdc /output/readback.sdc
write_def /output/readback.def
set f [open /output/actual_terms.tsv w]
puts $f "instance\tmaster\tpin\tdirection\tsignal_type\tnet"
foreach inst [[ord::get_db_block] getInsts] {{
    foreach it [$inst getITerms] {{
        set mt [$it getMTerm]
        set net [$it getNet]
        set netname ""
        if {{$net ne "NULL"}} {{set netname [$net getName]}}
        puts $f "[$inst getName]\t[[$inst getMaster] getName]\t[$mt getName]\t[$mt getIoType]\t[$mt getSigType]\t$netname"
    }}
}}
close $f
puts IHP_IO_SUITE_STA_COMPLETE
'''


def execute(root, output, container, shell):
    command = ['docker', 'run', '--name', container, '--cpus', '2', '--memory', '4g', '--ulimit', 'core=0',
        '--user', '1000:1000', '-e', 'HOME=/tmp', '--entrypoint', '/bin/bash', '-v', f'{root}:/work:ro',
        '-v', f'{output}:/output:rw', '-w', '/output', IMAGE, '-lc',
        'timeout --verbose --signal=TERM --kill-after=5s 60s /bin/bash -lc ' + shlex.quote(shell)]
    generated = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    start = time.monotonic()
    with (output / 'tool.log').open('x') as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait(timeout=85)
            outer = False
        except subprocess.TimeoutExpired:
            outer = True
            subprocess.run(['docker', 'stop', '-t', '5', container], capture_output=True, timeout=15)
            rc = proc.wait(timeout=15)
    observation = observe(container)
    write(output / 'terminal_observation.json', observation)
    state = observation.get('state', {})
    text = (output / 'tool.log').read_text(errors='replace')
    sentinel = 'OFFICIAL_IO_BEHAVIOR_PASS' if output.name == 'simulation' else 'IHP_IO_SUITE_STA_COMPLETE'
    complete = bool(rc == 0 and not outer and state.get('Status') == 'exited' and state.get('ExitCode') == 0
        and state.get('Running') is False and state.get('OOMKilled') is False and sentinel in text)
    record = {'command': command, 'returncode': rc, 'execution_complete': complete, 'status': 'completed' if complete else 'failed',
        'outer_timeout': outer, 'elapsed_seconds': time.monotonic() - start, 'terminal_container_state': state,
        'generated_input_sha256': generated}
    if state.get('Status') == 'exited' and state.get('Running') is False:
        record['cleanup_returncode'] = subprocess.run(['docker', 'rm', container], capture_output=True, timeout=15).returncode
    record['output_sha256'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    write(output / 'execution.json', record)
    return record


def run(root, run_id):
    require(re.fullmatch(r'ihp_io_suite-digital-sta-[A-Za-z0-9_-]+', run_id), 'Independent run ID required')
    run_dir = root / 'runs' / run_id
    run_dir.mkdir(exist_ok=False)
    gate = json.loads((root / GATE).read_text())
    for rel, digest in gate['source_sha256'].items():
        require(sha(root / rel) == digest, 'Pinned suite changed: ' + rel)
    view_report = interfaces(root)
    write(run_dir / 'interface_audit.json', view_report)
    source_paths = [root / GATE, Path(__file__), root / 'scripts/audit_croc_placement_structure.py', root / TECH]
    source_paths += [root / SUITE / (kind + '/sg13g2_io.' + suffix) for kind, suffix in (('lef','lef'),('cdl','cdl'),('gds','gds'),('verilog','v'))]
    source_paths += [root / SUITE / f'lib/sg13g2_io_{file}.lib' for file in CORNERS.values()]
    sources = {str(p.relative_to(root)): sha(p) for p in source_paths}
    manifest = {'schema_version': '1.0.0', 'run_id': run_id, 'started_at': now(), 'status': 'running',
        'fixed_pdk_commit': gate['fixed_pdk_commit'], 'fixed_image': IMAGE, 'source_sha256': sources, 'runs': {},
        'limits_per_process': {'cpus': 2, 'memory_gb': 4, 'inner_seconds': 60, 'outer_seconds': 85},
        'classification': 'matched_official_IO_digital_and_local_STA_not_physical_signoff',
        'load_pf': 15.0, 'explicit_max_transition_ns': 1.2, 'core_receiver_load_pf': 0.05,
        'gds_used_by_sta': False, 'new_liberty_applied_to_old_layout': False, 'bondpad_in_fixture': False,
        'main_design_modified': False, 'source_pdk_modified': False, 'public_rule_signoff': False,
        'parasitics': 'no_route_or_placement_RC_only_pin_caps_and_explicit_lumped_loads',
        'workload_power_w': None}
    write(run_dir / 'manifest.json', manifest)
    for arm in ('simulation', *CORNERS):
        output = run_dir / arm
        output.mkdir()
        if arm == 'simulation':
            (output / 'tb.sv').write_text(TB)
            shell = f'iverilog -V > /output/compiler_version.txt 2>&1 && iverilog -g2012 -s tb -o /output/sim.vvp /work/{SUITE}/verilog/sg13g2_io.v /output/tb.sv && vvp /output/sim.vvp'
        else:
            (output / 'input.def').write_text(tiny_def())
            (output / 'input.sdc').write_text(SDC)
            (output / 'run.tcl').write_text(sta_tcl(arm))
            shell = 'openroad -exit /output/run.tcl'
        manifest['runs'][arm] = execute(root, output, run_id + '-' + arm, shell)
        write(run_dir / 'manifest.json', manifest)
        print(json.dumps({'arm': arm, 'status': manifest['runs'][arm]['status'], 'elapsed_seconds': manifest['runs'][arm]['elapsed_seconds']}), flush=True)
        if not manifest['runs'][arm]['execution_complete']:
            # Preserve failure; unexecuted arms stay absent and must be reported NOT_RUN.
            break
    manifest.update(finished_at=now(), status='completed' if len(manifest['runs']) == 4 and all(r['execution_complete'] for r in manifest['runs'].values()) else 'failed',
        source_hashes_unchanged=all(sha(root / p) == h for p, h in sources.items()))
    write(run_dir / 'manifest.json', manifest)
    return 0 if manifest['status'] == 'completed' else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-id', required=True)
    args = ap.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id))
