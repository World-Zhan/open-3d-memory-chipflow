#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independent three-corner continuation using fixed, supported report APIs."""
import argparse
import json
import re
from pathlib import Path
import run_ihp_io_suite_digital_sta as base
from run_io_ring_floorplan import IMAGE, now, sha, write

SOURCE = 'runs/ihp_io_suite-digital-sta-20260910-001'


def tcl():
    header = 'set_thread_count 2\ndefine_corners tt ff ss\n'
    for corner, file in base.CORNERS.items():
        header += f'read_liberty -corner {corner} /work/{base.SUITE}/lib/sg13g2_io_{file}.lib\n'
    header += f'read_lef /work/{base.TECH}\nread_lef /work/{base.SUITE}/lef/sg13g2_io.lef\nread_def /output/input.def\nread_sdc /output/input.sdc\n'
    pieces = []
    for corner in base.CORNERS:
        commands = base.sta_tcl(corner).split('help report_check_types', 1)[1]
        commands = 'help report_check_types' + commands
        commands = commands.replace('report_case_analysis > /output/case_analysis.rpt', '# Mode evidence is preserved by write_sdc below; report_case_analysis is absent in this fixed binary.')
        commands = commands.replace('report_check_types -max_', f'report_check_types -corner {corner} -max_')
        commands = commands.replace('report_checks -from', f'report_checks -corner {corner} -from')
        commands = commands.replace('/output/', f'/output/{corner}/')
        commands = commands.replace('puts IHP_IO_SUITE_STA_COMPLETE', f'puts IHP_IO_SUITE_CORNER_COMPLETE_{corner}')
        pieces.append(commands)
    return header + '\n'.join(pieces) + '''
set f [open /output/combined_counts.tsv w]
puts $f "check\tcount\tscope"
puts $f "max_slew\t[sta::max_slew_violation_count]\taggregate_tt_ff_ss"
puts $f "max_capacitance\t[sta::max_capacitance_violation_count]\taggregate_tt_ff_ss"
puts $f "max_fanout\t[sta::max_fanout_violation_count]\taggregate_tt_ff_ss"
puts $f "setup\t[sta::endpoint_violation_count max]\ttiny_paths_only"
puts $f "hold\t[sta::endpoint_violation_count min]\ttiny_paths_only"
close $f
puts IHP_IO_SUITE_STA_COMPLETE
'''


def run(root, run_id):
    base.require(re.fullmatch(r'ihp_io_suite-sta-readback-[A-Za-z0-9_-]+', run_id), 'Independent continuation ID required')
    source = root / SOURCE
    previous = json.loads((source / 'manifest.json').read_text())
    sim = previous['runs']['simulation']
    base.require(sim['execution_complete'] and sim['returncode'] == 0, 'Prior completed simulation required')
    for rel, digest in previous['source_sha256'].items():
        base.require(sha(root / rel) == digest, 'Previous sources changed')
    for arm, record in previous['runs'].items():
        for rel, digest in record['output_sha256'].items():
            base.require(sha(source / arm / rel) == digest, 'Prior output changed')
    # This help was produced by the actual failed TT process before its later API failure.
    help_text = (source / 'tt/check_help.rpt').read_text()
    base.require('[-corner corner]' in help_text, 'No fixed runtime proof of corner reports')
    run_dir = root / 'runs' / run_id
    run_dir.mkdir(exist_ok=False)
    output = run_dir / 'multicorner'
    output.mkdir()
    for corner in base.CORNERS:
        (output / corner).mkdir()
    (output / 'input.def').write_bytes((source / 'tt/input.def').read_bytes())
    (output / 'input.sdc').write_bytes((source / 'tt/input.sdc').read_bytes())
    (output / 'run.tcl').write_text(tcl())
    sources = dict(previous['source_sha256'])
    for path in (Path(__file__), source / 'manifest.json', source / 'tt/check_help.rpt', source / 'tt/input.def', source / 'tt/input.sdc',
                 root / 'runs/croc-placement-sta-readback-20260909-001/candidate/work/openroad/scripts/reports.tcl'):
        sources[str(path.relative_to(root))] = sha(path)
    manifest = {'schema_version': '1.0.0', 'run_id': run_id, 'started_at': now(), 'status': 'running',
        'fixed_image': IMAGE, 'fixed_pdk_commit': previous['fixed_pdk_commit'], 'source_sha256': sources,
        'prior_run': SOURCE, 'classification': 'matched_official_IO_local_three_corner_STA_not_signoff',
        'source_pdk_modified': False, 'main_design_modified': False, 'old_gds_or_liberty_used': False,
        'bondpad_in_fixture': False, 'public_rule_signoff': False, 'workload_power_w': None,
        'load_pf': 15.0, 'explicit_max_transition_ns': 1.2, 'core_receiver_load_pf': 0.05,
        'mode_implementation': 'simultaneous_independent_output_input_highz_instances_with_explicit_top_port_directions_and_enable_case_constraints',
        'parasitics': 'pin_caps_and_explicit_lumped_loads_no_route_or_placement_RC',
        'limits': {'cpus': 2, 'memory_gb': 4, 'inner_seconds': 60, 'outer_seconds': 85}}
    write(run_dir / 'manifest.json', manifest)
    execution = base.execute(root, output, run_id + '-multicorner', 'openroad -exit /output/run.tcl')
    manifest.update(execution=execution, finished_at=now(), status=execution['status'],
        source_hashes_unchanged=all(sha(root / p) == h for p, h in sources.items()))
    write(run_dir / 'manifest.json', manifest)
    print(json.dumps({'status': manifest['status'], 'elapsed_seconds': execution['elapsed_seconds'], 'returncode': execution['returncode']}))
    return 0 if execution['execution_complete'] else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-id', required=True)
    args = ap.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id))
