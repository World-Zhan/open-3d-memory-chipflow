#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit saved full-floorplan evidence without running EDA; requires local inputs."""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from run_io_ring_floorplan import sha, write


def pin_signatures(text):
    match = re.search(r'^PINS\s+(\d+)\s*;(.*?)^END PINS', text, re.M | re.S)
    if not match:
        raise ValueError('Missing DEF PINS section')
    result = {}
    for record in match[2].split(';'):
        name = re.match(r'\s*-\s+(\S+)', record)
        if not name:
            continue
        if name[1] in result:
            raise ValueError('Duplicate DEF port')
        values = [re.search(r'\+\s+' + key + r'\s+(\S+)', record)
                  for key in ('NET', 'DIRECTION', 'USE')]
        if not all(values):
            raise ValueError('Missing DEF port signature field')
        result[name[1]] = tuple(item[1] for item in values)
    if len(result) != int(match[1]):
        raise ValueError('DEF port count mismatch')
    return result


def check_terminals(pins, bonds, original, candidate):
    if len(original) != 52 or original != candidate:
        raise ValueError('Original 52 top port signatures must be preserved')
    if len(pins) != 64 or len(bonds) != 64:
        raise ValueError('Require 64 top pin and bondpad boxes')
    if len({b['instance'] for b in bonds}) != 64:
        raise ValueError('Duplicate bondpad instance')
    if {p['port'] for p in pins} != set(candidate):
        raise ValueError('Each top port needs physical geometry')
    for pin in pins:
        sig = (pin['net'], pin['io_type'], pin['signal_type'])
        if sig != candidate[pin['port']]:
            raise ValueError('Physical pin port-to-net/type binding mismatch')
        if pin['layer'] != 'TopMetal2' or pin['placement_status'] not in ('FIRM', 'LOCKED'):
            raise ValueError('Wrong physical pin layer or status')
    def box(row):
        coords = tuple(int(row[k]) for k in ('xmin', 'ymin', 'xmax', 'ymax'))
        if coords[2] <= coords[0] or coords[3] <= coords[1]:
            raise ValueError('Nonpositive pin/bondpad box')
        return (row['net'], *coords)
    if Counter(map(box, pins)) != Counter(map(box, bonds)):
        raise ValueError('Pin and bondpad net/geometry mismatch')
    return True


def check_pg(rows, log, tcl):
    if len(rows) != 2 or {r['net'] for r in rows} != {'VDD', 'VSS'}:
        raise ValueError('Missing or duplicate core supply checks')
    if 'check_power_grid -net $net -floorplanning' not in tcl:
        raise ValueError('Unexpected PG check scope')
    if re.search(r'\[ERROR|Signal\s+\d+|Segmentation fault|timeout: sending signal', log, re.I):
        raise ValueError('Tool error in readback log')
    for row in rows:
        net = row['net']
        if row['tcl_catch_code'] != '0' or row['message'] != '1':
            raise ValueError('PG command did not return observed success')
        block = re.search(r'STATIC_PG_CHECK_BEGIN ' + net + r'\n(.*?)STATIC_PG_CHECK_END ' + net + r' catch=0', log, re.S)
        if not block or f'[INFO PSM-0040] All shapes on net {net} are connected.' not in block[1]:
            raise ValueError('Missing positive physical PG message')
    if 'FULL_FLOORPLAN_READBACK_COMPLETE' not in log:
        raise ValueError('Readback incomplete')
    return True


def audit(root, source_run, readback_run):
    source, readback = (root / 'runs' / item for item in (source_run, readback_run))
    checked = {}
    def verify(path, expected=None):
        digest = sha(path)
        if expected is not None and digest != expected:
            raise ValueError('Evidence hash mismatch: ' + str(path))
        checked[str(path.relative_to(root))] = digest
    def load_manifest(folder):
        path = folder / 'manifest.json'
        data = json.loads(path.read_text())
        verify(path)
        if type(data.get('returncode')) is not int or data['returncode'] != 0 or data['status'] != 'completed':
            raise ValueError('Completed real integer exit 0 required')
        for rel, digest in data['source_sha256'].items():
            verify(root / rel, digest)
        for field in ('generated_inputs_sha256', 'input_sha256', 'outputs_sha256'):
            for rel, digest in data.get(field, {}).items():
                verify(folder / rel, digest)
        return data
    original_manifest = load_manifest(source)
    replay_manifest = load_manifest(readback)
    if replay_manifest['source_run'] != source_run:
        raise ValueError('Wrong readback source run')
    if original_manifest['source_hashes_unchanged'] is not True:
        raise ValueError('Original sources changed during execution')
    verify(readback / 'readback.tcl', replay_manifest['readback_tcl_sha256'])
    def rows(name):
        with (readback / name).open() as handle:
            return list(csv.DictReader(handle, delimiter='\t'))
    original = pin_signatures((source / 'inputs/baseline_floorplan.def').read_text())
    candidate = pin_signatures((readback / 'inputs/01_croc.floorplan.def').read_text())
    check_terminals(rows('top_pin_boxes.tsv'), rows('bondpad_boxes.tsv'), original, candidate)
    check_pg(rows('pg_checks.tsv'), (readback / 'tool.log').read_text(), (readback / 'readback.tcl').read_text())
    verify(root / 'scripts/audit_full_io_floorplan.py')
    return {'classification': 'full_floorplan_terminal_and_floorplanning_pg_evidence_not_signoff',
            'source_run': source_run, 'readback_run': readback_run,
            'source_sha256': checked, 'unique_files_hash_verified': len(checked),
            'physical_top_ports': 52, 'physical_pin_boxes': 64,
            'top_pin_geometry_and_binding_result': 'PASS',
            'static_core_pg_floorplanning_result': 'PASS', 'core_supply_nets': ['VDD', 'VSS'],
            'stdcell_supply_connectivity_after_placement': 'not_run',
            'ir_em_result': 'not_run', 'new_full_chip_drc_lvs': 'not_run',
            'public_rule_signoff': False, 'foundry_signoff': False,
            'fresh_checkout_limitation': 'Full hash replay requires local large DEF/ODB/ZIP/PDK inputs; small archived evidence supports unit tests only.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True)
    parser.add_argument('--readback-run', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / args.output
    if output.exists():
        raise ValueError('Independent output required; preserve old evidence')
    result = audit(root, args.source_run, args.readback_run)
    output.parent.mkdir(parents=True, exist_ok=True)
    write(output, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'source_sha256'}, indent=2))
