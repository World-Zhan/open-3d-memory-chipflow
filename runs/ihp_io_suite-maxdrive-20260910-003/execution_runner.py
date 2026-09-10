#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Final bounded Out16-to-Out30 single-master experiment with fixed constraints."""
import argparse
import json
import re
from pathlib import Path
import run_ihp_io_suite_digital_sta as base
import run_ihp_io_suite_sta_readback as continuation
from run_io_ring_floorplan import IMAGE, now, sha, write

SOURCE = 'runs/ihp_io_suite-sta-readback-20260910-002'


def out30_interface(root):
    # Extend only the local parser's exact cell allowlist for this additional macro;
    # restore it before generating/reading the existing six-instance fixture.
    original = base.CELLS
    try:
        base.CELLS = (*original, 'sg13g2_IOPadOut30mA')
        result = base.interfaces(root)
    finally:
        base.CELLS = original
    old = result['cells']['sg13g2_IOPadOut16mA']
    new = result['cells']['sg13g2_IOPadOut30mA']
    base.require(old['ordered_verilog_cdl_ports'] == new['ordered_verilog_cdl_ports']
        and old['verilog_directions'] == new['verilog_directions'], 'Out30 interface differs')
    for corner in base.CORNERS:
        a, b = old['liberty'][corner], new['liberty'][corner]
        base.require(a['pg_types'] == b['pg_types'], 'Out30 PG differs')
        for pin in a['signals']:
            base.require({k:v for k,v in a['signals'][pin].items() if k != 'max_capacitance'} ==
                {k:v for k,v in b['signals'][pin].items() if k != 'max_capacitance'}, 'Out30 logical pin differs')
    return {'result': 'PASS', 'scope': 'cross_view_Out30_interface_not_new_digital_simulation_or_LVS',
        'cell': 'sg13g2_IOPadOut30mA', 'view': new}


def run(root, run_id):
    base.require(re.fullmatch(r'ihp_io_suite-maxdrive-[A-Za-z0-9_-]+', run_id), 'Unique maxdrive run ID required')
    source = root / SOURCE
    old = json.loads((source / 'manifest.json').read_text())
    base.require(old['status'] == 'completed' and old['execution']['execution_complete'], 'Completed baseline required')
    for rel, h in old['source_sha256'].items():
        base.require(sha(root / rel) == h, 'Baseline source changed')
    for rel, h in old['execution']['output_sha256'].items():
        base.require(sha(source / 'multicorner' / rel) == h, 'Baseline output changed')
    run_dir = root / 'runs' / run_id
    run_dir.mkdir(exist_ok=False)
    write(run_dir / 'out30_interface_audit.json', out30_interface(root))
    output = run_dir / 'multicorner'
    output.mkdir()
    for corner in base.CORNERS:
        (output / corner).mkdir()
    original = (source / 'multicorner/input.def').read_text()
    needle = '- out16 sg13g2_IOPadOut16mA '
    base.require(original.count(needle) == 1, 'Exactly one output master expected')
    (output / 'input.def').write_text(original.replace(needle, '- out16 sg13g2_IOPadOut30mA '))
    (output / 'input.sdc').write_bytes((source / 'multicorner/input.sdc').read_bytes())
    (output / 'run.tcl').write_text(continuation.tcl())
    sources = dict(old['source_sha256'])
    for p in (Path(__file__), source / 'manifest.json', source / 'multicorner/input.def', source / 'multicorner/input.sdc'):
        sources[str(p.relative_to(root))] = sha(p)
    manifest = {'schema_version': '1.0.0', 'run_id': run_id, 'started_at': now(), 'status': 'running',
        'classification': 'Out30_single_master_local_STA_not_integrated_or_signoff', 'fixed_image': IMAGE,
        'fixed_pdk_commit': old['fixed_pdk_commit'], 'source_sha256': sources,
        'baseline_run': SOURCE, 'changed_master': {'instance': 'out16', 'from': 'sg13g2_IOPadOut16mA', 'to': 'sg13g2_IOPadOut30mA'},
        'instance_name_note': 'out16 retained to preserve every original net/endpoint; actual candidate master is Out30.',
        'same_sdc': True, 'load_pf': 15, 'explicit_max_transition_ns': 1.2,
        'external_bidir_input_driver': 'sg13g2_IOPadOut16mA preserved to keep one-factor test',
        'source_pdk_modified': False, 'main_design_modified': False, 'old_gds_or_liberty_used': False,
        'public_rule_signoff': False, 'workload_power_w': None,
        'limits': {'cpus': 2, 'memory_gb': 4, 'inner_seconds': 60, 'outer_seconds': 85}}
    write(run_dir / 'manifest.json', manifest)
    record = base.execute(root, output, run_id + '-multicorner', 'openroad -exit /output/run.tcl')
    manifest.update(execution=record, status=record['status'], finished_at=now(),
        source_hashes_unchanged=all(sha(root / p) == h for p, h in sources.items()))
    write(run_dir / 'manifest.json', manifest)
    print(json.dumps({'status': manifest['status'], 'returncode': record['returncode'], 'elapsed_seconds': record['elapsed_seconds']}))
    return 0 if record['execution_complete'] else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-id', required=True)
    args = ap.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[1], args.run_id))
