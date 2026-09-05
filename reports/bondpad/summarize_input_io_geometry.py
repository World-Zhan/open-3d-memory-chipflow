#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Derive reproducible local pad/IO movement constraints from a pinned geometry run."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive(root):
    run = root / 'runs/bondpad-input-neighborhood-20260905-004'
    geometry = json.loads((run / 'geometry.json').read_text())
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['returncode'] == 0
    for name, expected in manifest['artifact_sha256'].items():
        assert digest(run / name) == expected, name
    lef_path = root / 'upstream/croc/technology/lef/sg13g2_io.lef'
    lef = lef_path.read_text()
    macro = re.search(r'^MACRO sg13g2_IOPadIn\s*$(.*?)^END sg13g2_IOPadIn\s*$', lef, re.M | re.S)[1]
    lef_pins = re.findall(r'^\s*PIN\s+(\S+)', macro, re.M)
    def_path = root / 'runs/croc-sg13g2-baseline-20260827-001/artifacts/pnr/upstream/croc/openroad/out/croc.def'
    def_text = def_path.read_text()
    signal_interfaces = []
    for section, net in [('NETS', 'soc_jtag_tdi_i'), ('SPECIALNETS', 'jtag_tdi_i')]:
        section_text = re.search(r'^' + section + r'\s+\d+\s*;(.*?)^END ' + section, def_text, re.M | re.S)[1]
        records = [record for record in section_text.split(';') if re.match(r'\s*-\s+' + net + r'\s', record)]
        assert len(records) == 1
        signal_interfaces.append({'net': net, 'section': section,
                                  'connections': re.findall(r'\(\s*(\S+)\s+(\S+)\s*\)', records[0].partition('+')[0])})
    connected_io_pins = {pin for entry in geometry['interfaces'] for inst, pin in entry['local_connections'] if inst == 'pad_jtag_tdi_i'}
    distances = geometry['distance_brackets_um']
    active_gap = Decimal(str(distances['opening_to_active']['lower_um']))
    seal_gap = Decimal(str(distances['opening_to_edge_seal_active_not_recog']['lower_um']))
    assert active_gap == Decimal('8.135') and seal_gap == Decimal('7.735')
    assert geometry['layer_presence_in_gds']['Recog'] is False
    variants = []
    for name, enclosure in [('original_croc_square70', Decimal('2.135')),
                            ('official_m2_square70', Decimal('2.1'))]:
        active = active_gap + enclosure - Decimal('2.135')
        seal = seal_gap + enclosure - Decimal('2.135')
        min_pad = Decimal('25') - seal
        min_gap_for_active = Decimal('11.2') - active
        min_relative_io = max(min_gap_for_active, Decimal('7') - Decimal('3'))
        variants.append({'macro': name, 'passiv_enclosure_um': float(enclosure),
                         'unshifted_active_gap_um': float(active), 'unshifted_seal_gap_um': float(seal),
                         'min_pad_inward_shift_fixed_seal_um': float(min_pad),
                         'min_io_minus_pad_shift_for_active_um': float(min_gap_for_active),
                         'min_io_minus_pad_shift_for_7um_exit_um': 4.0,
                         'min_io_minus_pad_shift_combined_um': float(min_relative_io),
                         'min_io_inward_shift_at_min_pad_um': float(min_pad + min_relative_io),
                         'predicted_active_gap_at_boundary_um': float(active + min_relative_io),
                         'predicted_seal_gap_at_boundary_um': 25.0,
                         'predicted_exit_length_at_boundary_um': 7.0,
                         'scope': 'Necessary local rigid-body constraints with a new continuous lead; all relevant inner Active must follow IO shift. Not full-neighborhood sufficiency or DRC.'})
    sources = [run / 'geometry.json', run / 'manifest.json', run / 'executed_probe.py',
               root / 'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_maximal.drc',
               root / 'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/beol/6_9_pad.drc',
               root / 'runs/bondpad-geometry-20260905-003/official_m2_square70.gds',
               root / 'reports/bondpad/input-io-cell-comparison-20260905-001.json',
               root / 'reports/bondpad/summarize_input_io_geometry.py']
    return {
        'schema_version': '1.0.0', 'classification': 'read_only_geometry_and_analytical_constraints_not_signoff',
        'geometry_run': str(run.relative_to(root)), 'geometry_returncode': 0,
        'actual_pure_input_instances': geometry['actual_pure_input_instances'],
        'requested_bottom_input_instance_exists': False,
        'selection': geometry['selected'], 'gds_io_bbox_um': geometry['selected_io_bbox_gds_um'],
        'lef_io_bbox_um': geometry['selected_io_bbox_def_um'],
        'canonical_frame': geometry['canonical_bottom_frame'],
        'local_extraction': {'sealed_roi_dbu': [12000, 530000, 322000, 670000],
                             'dbu_um': 0.001, 'normalization': 'k.Trans(k.Trans.M45, -560000, -112000)',
                             'api': '(k.Region(sealed.begin_shapes_rec_touching(layer_index, roi)) & k.Region(roi)).transformed(normal).merged()',
                             'outward_direction': 'negative canonical v',
                             'edge_seal_layer': '39/0', 'active_layer': '1/0', 'recog_layer': '99/0 absent in source GDS',
                             'local_edge_seal_bbox_um': geometry['regions']['EdgeSeal']['bbox_local_um'],
                             'caution': 'A clipped seal segment has artificial ends. Include its complete layer stack for any fixture DRC and report cut-boundary effects separately.'},
        'measured_distance_brackets_um': distances, 'existing_exit_strip': geometry['exit_strip'],
        'movement_model': {'positive_direction': 'inward canonical v',
                           'variables': {'P': 'pad inward translation', 'I': 'all relevant inner Active / IO inward translation', 'S': 'seal inward translation'},
                           'inequalities_um': ['old_seal_gap + P - S >= 25', 'old_active_gap + I - P >= 11.2', '3 + I - P >= 7'],
                           'assumptions': ['Parallel nearest edges remain relevant; no rotation or tangential shift.',
                                           'Add a continuous lead across the pad-to-IO gap, aligned to the six actual pad-pin metal layers.',
                                           'Neighbor Active, PG rails, corners, routing, density and package geometry require independent validation.'],
                           'variants': variants},
        'measured_analytical_translation': geometry['analytical_official_candidate'],
        'neighbor_constraint': {'single_io_shift_is_sufficient': False, 'reason': 'At pad +17.4 and selected IO +21.5, unchanged neighboring Active at u=0/80 gives only 7.1 um separation; moving just this IO does not pass Pad.d1R.'},
        'affected_interfaces': {'signal_connections_from_def': signal_interfaces,
                                'local_connections_from_def': geometry['interfaces'],
                                'all_lef_pin_names': lef_pins,
                                'lef_pins_without_selected_instance_connection_in_def': sorted(set(lef_pins) - connected_io_pins),
                                'required_revalidation': ['jtag_tdi_i package pin and bondpad-to-IO pad lead', 'soc_jtag_tdi_i p2c route to existing core pins', 'IO supply rail continuity and neighboring IO abutment', 'All LEF power/ground pins including those not observed as explicit selected-instance DEF connections']},
        'history': [{'run': 'bondpad-input-neighborhood-20260905-001', 'returncode': 1, 'reason': 'GDS physical bbox extends 0.62 um beyond each LEF width side; original bbox selection assertion failed'},
                    {'run': 'bondpad-input-neighborhood-20260905-002', 'returncode': 0, 'reason': 'Measured original selected neighborhood'},
                    {'run': 'bondpad-input-neighborhood-20260905-003', 'returncode': 1, 'reason': 'Recog99/0 does not exist in GDS; initial missing-layer handling failed'},
                    {'run': 'bondpad-input-neighborhood-20260905-004', 'returncode': 0, 'reason': 'Completed exact Recog exclusion and analytical neighbor translation checks'}],
        'source_sha256': {str(path.relative_to(root)): digest(path) for path in sources},
        'changes_to_source_layout': False, 'full_chip_drc_lvs_performed': False,
        'ppa': {'new_chip_candidate': False, 'new_chip_area_power_timing_result': False}
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = derive(args.root.resolve())
    with args.output.open('x') as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write('\n')
    print(json.dumps({'variants': result['movement_model']['variants'],
                      'lef_pins': result['affected_interfaces']['all_lef_pin_names'],
                      'unobserved_pins': result['affected_interfaces']['lef_pins_without_selected_instance_connection_in_def']}, indent=2))
