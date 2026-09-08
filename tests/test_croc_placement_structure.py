# SPDX-License-Identifier: Apache-2.0
import copy
import sys
import unittest
from test_contracts import ROOT, load_module
sys.path.insert(0, str(ROOT / 'scripts'))
a = load_module('audit_croc_placement_structure', ROOT / 'scripts/audit_croc_placement_structure.py')


def cell(name, function, inputs=('A', 'B'), output='X', extra=''):
    return 'cell (' + name + ') {' + ''.join('pin (' + p + ') { direction : input; }' for p in inputs) + 'pin (' + output + ') { direction : output; function : "' + function + '"; }' + extra + '}'


def library():
    return a.liberty_logic(cell('and_1', 'A & B') + cell('and_2', 'A & B') + cell('asym', 'A & !B') + cell('sg13g2_buf_1', 'A', ('A',)) + cell('sg13g2_tiehi', '1', (), 'L_HI') + cell('sg13g2_tielo', '0', (), 'L_LO'))


def fixture(master='and_1', swapped=False, buffer=False, tie=None):
    instances, terms = [], []
    def add(name, master, ports):
        instances.append({'name': name, 'master': master, 'type': 'CORE'})
        ports = dict(ports, VDD=('VDD', 'INOUT'), VSS=('VSS', 'INOUT'))
        for pin, (net, direction) in ports.items():
            terms.append({'instance': name, 'pin': pin, 'net': net, 'io_type': direction, 'signal_type': 'POWER' if pin == 'VDD' else 'GROUND' if pin == 'VSS' else 'SIGNAL'})
    one, two = ('b', 'a') if swapped else ('a', 'b')
    if tie:
        add('tie', tie, {a.TIES[tie][0]: (one, 'OUTPUT')})
    if buffer:
        add('buffer', 'sg13g2_buf_1', {'A': (one, 'INPUT'), 'X': ('buffered', 'OUTPUT')})
        one = 'buffered'
    add('gate', master, {'A': (one, 'INPUT'), 'B': (two, 'INPUT'), 'X': ('z', 'OUTPUT')})
    ports = [{'port': n, 'net': n, 'io_type': 'OUTPUT' if n == 'z' else 'INPUT', 'signal_type': 'SIGNAL'} for n in ('a', 'b', 'z') if not (tie and n == 'a')]
    return [instances, terms, ports]


def modify(data, instance, pin, **changes):
    row = next(x for x in data[1] if x['instance'] == instance and x['pin'] == pin)
    row.update(changes)
    return data


class PlacementStructureTests(unittest.TestCase):
    def test_direct_pins_exclude_nested_scan_test_cell(self):
        lib = a.liberty_logic(cell('normal', 'A', ('A',), extra='test_cell () { pin (A) { direction : input; } pin (X) { direction : output; function : "!A"; } }'))
        self.assertEqual(lib['normal']['pins']['X'][1], 'A')

    def test_duplicate_direct_pin_fails(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate Liberty pin'):
            a.liberty_logic(cell('duplicate', 'A', ('A', 'A')))

    def test_real_function_proves_symmetric_swap(self):
        result = a.compare_logic(fixture(), fixture(swapped=True), library())
        self.assertEqual(result['observed_symmetric_input_permutation_count'], 1)

    def test_asymmetric_input_swap_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Connectivity changed'):
            a.compare_logic(fixture('asym'), fixture('asym', swapped=True), library())

    def test_buffers_on_both_sides_and_resize_preserve_connectivity(self):
        self.assertEqual(a.compare_logic(fixture(buffer=True), fixture('and_2'), library())['result'], 'PASS')

    def test_nontransparent_buffer_model_rejected(self):
        lib = library()
        lib.update(a.liberty_logic(cell('sg13g2_buf_1', '!A', ('A',))))
        with self.assertRaisesRegex(ValueError, 'Buffer/tie function'):
            a.compare_logic(fixture(), fixture(buffer=True), lib)

    def test_tie_replication_is_constant_specific(self):
        before = fixture(tie='sg13g2_tiehi')
        after = copy.deepcopy(before)
        a.compare_logic(before, after, library())
        after = fixture(tie='sg13g2_tielo')
        with self.assertRaisesRegex(ValueError, 'Connectivity changed'):
            a.compare_logic(before, after, library())

    def test_missing_supply_is_rejected(self):
        after = fixture(buffer=True)
        after[1] = [x for x in after[1] if (x['instance'], x['pin']) != ('buffer', 'VSS')]
        with self.assertRaisesRegex(ValueError, 'missing exported supply'):
            a.compare_logic(fixture(), after, library())

    def test_wrong_supply_is_rejected(self):
        after = modify(fixture(buffer=True), 'buffer', 'VDD', net='VSS')
        with self.assertRaisesRegex(ValueError, 'explicit supply'):
            a.compare_logic(fixture(), after, library())

    def test_buffer_output_multiple_driver_rejected(self):
        after = fixture(buffer=True)
        after[2].append({'port': 'bad', 'net': 'buffered', 'io_type': 'INPUT', 'signal_type': 'SIGNAL'})
        with self.assertRaisesRegex(ValueError, 'Multiple/unknown driver'):
            a.compare_logic(fixture(), after, library())

    def test_buffer_self_loop_rejected(self):
        after = modify(fixture(buffer=True), 'buffer', 'A', net='buffered')
        with self.assertRaisesRegex(ValueError, 'self-loop'):
            a.compare_logic(fixture(), after, library())

    def test_input_pin_multiplicity_not_erased(self):
        # Both symmetric inputs on a versus one on a, one on b must remain different.
        after = modify(fixture(), 'gate', 'B', net='a')
        with self.assertRaisesRegex(ValueError, 'Connectivity changed'):
            a.compare_logic(fixture(), after, library())

    def test_missing_signal_pin_is_rejected(self):
        after = fixture()
        after[1] = [x for x in after[1] if x['pin'] != 'B']
        with self.assertRaisesRegex(ValueError, 'signal pin inventory'):
            a.compare_logic(fixture(), after, library())

    def test_unverified_clone_rejected(self):
        after = fixture()
        for rows in after[:2]:
            cloned = copy.deepcopy(rows)
            for row in cloned:
                row['name' if 'name' in row else 'instance'] = 'clone'
            rows.extend(cloned)
        with self.assertRaisesRegex(ValueError, 'add/remove/clone'):
            a.compare_logic(fixture(), after, library())

    def test_ff_signature_includes_reset_behavior(self):
        first = cell('ff1', 'IQ', ('D', 'CLK', 'RESET'), extra='ff (IQ, IQN) { next_state : "D"; clocked_on : "CLK"; clear : "RESET"; }')
        second = first.replace('ff1', 'ff2').replace('clear : "RESET"', 'clear : "!RESET"')
        lib = a.liberty_logic(first + second)
        self.assertNotEqual(lib['ff1']['signature'], lib['ff2']['signature'])
        self.assertEqual(lib['ff1']['symmetric_inputs']['D'], ('D',))

    def test_unsupported_boolean_grammar_cannot_prove_symmetry(self):
        lib = a.liberty_logic(cell('strange', 'A ? B : A'))
        self.assertEqual(lib['strange']['symmetric_inputs'], {'A': ('A',), 'B': ('B',)})

    def test_boolean_precedence_and_postfix_inversion(self):
        self.assertTrue(a.boolean_function("A + B * C'", {'A': False, 'B': True, 'C': False}))
        self.assertFalse(a.boolean_function('!(A ^ B)', {'A': True, 'B': False}))
        with self.assertRaises(ValueError):
            a.boolean_function('A garbage', {'A': True})

    def test_terminal_boolean_zero_not_integer_zero(self):
        manifest = {'status': 'completed', 'returncode': False}
        with self.assertRaises(ValueError): a.terminal_check(manifest, {})

    def test_terminal_oom_running_and_timeout_rejected(self):
        state = {'Status': 'exited', 'ExitCode': 0, 'OOMKilled': False, 'Running': False, 'Error': ''}
        manifest = {'status': 'completed', 'returncode': 0, 'terminal_container_state': state, 'outer_timeout_expired': False}
        observation = {'state_returncode': 0, 'state': state}
        a.terminal_check(manifest, observation)
        for field, value in [('OOMKilled', True), ('Running', True), ('ExitCode', 137)]:
            bad = copy.deepcopy(manifest)
            bad['terminal_container_state'][field] = value
            with self.assertRaises(ValueError): a.terminal_check(bad, {'state_returncode': 0, 'state': bad['terminal_container_state']})
        manifest['outer_timeout_expired'] = True
        with self.assertRaises(ValueError): a.terminal_check(manifest, observation)

    def test_directed_buffer_cycle_is_rejected(self):
        data = fixture(buffer=True)
        data[0].append({'name': 'second', 'master': 'sg13g2_buf_1', 'type': 'CORE'})
        data[1].extend(dict(r, instance='second', net='a' if r['pin'] == 'X' else 'buffered' if r['pin'] == 'A' else r['net']) for r in list(data[1]) if r['instance'] == 'buffer')
        data[2] = [r for r in data[2] if r['port'] != 'a']
        with self.assertRaisesRegex(ValueError, 'cycle'):
            a.normalize(*data, library())


def physical_fixture():
    instances = [{'name': 'fixed' + str(i), 'master': 'macro' if i < 2 else 'pad', 'type': 'BLOCK' if i < 2 else 'PAD', 'orientation': 'R0', 'status': 'FIRM', 'xmin': str(i), 'ymin': '0', 'xmax': str(i + 1), 'ymax': '1'} for i in range(194)]
    ports = [{'port': 'p' + str(i), 'net': 'p' + str(i), 'io_type': 'INPUT', 'signal_type': 'SIGNAL'} for i in range(52)]
    pins = [{'port': 'p' + str(i % 52), 'net': 'p' + str(i % 52), 'layer': 'TopMetal2', 'xmin': str(i), 'ymin': '0', 'xmax': str(i + 1), 'ymax': '1', 'status': 'FIRM'} for i in range(64)]
    text = 'UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 1974000 1974000 ) ;\nROW R site 0 0 N DO 1 BY 1 STEP 1 1 ;\nTRACKS X 0 DO 1 STEP 1 LAYER Metal1 ;\nCOMPONENTS 0 ;\nEND COMPONENTS\nNETS 0 ;\nEND NETS\nSPECIALNETS 1 ;\n- p0 + USE SIGNAL + ROUTED TopMetal2 4200 + SHAPE IOWIRE ( 0 0 ) ( 0 1 ) ;\nEND SPECIALNETS\n'
    return [instances, [], ports], pins, text


class PlacementPhysicalTests(unittest.TestCase):
    def test_fixed_inventory_and_recorded_clock_classification(self):
        data, pins, text = physical_fixture()
        result = a.physical_check(data, data, pins, pins, text, text.replace('USE SIGNAL', 'USE CLOCK'))
        self.assertEqual(result['input_lead_use_changes'], [{'net': 'p0', 'before': 'SIGNAL', 'after': 'CLOCK'}])

    def test_io_macro_geometry_master_orientation_and_status_changes_fail(self):
        data, pins, text = physical_fixture()
        for instance in (0, 193):
            for field in ('xmin', 'master', 'orientation', 'status'):
                after = copy.deepcopy(data)
                after[0][instance][field] = 'CHANGED'
                with self.assertRaisesRegex(ValueError, 'Fixed IO'):
                    a.physical_check(data, after, pins, pins, text, text)

    def test_physical_pin_net_geometry_or_count_change_fails(self):
        data, pins, text = physical_fixture()
        for field in ('net', 'xmin', 'layer', 'status'):
            bad = copy.deepcopy(pins)
            bad[0][field] = 'CHANGED'
            with self.assertRaisesRegex(ValueError, 'physical top pin'):
                a.physical_check(data, data, pins, bad, text, text)
        with self.assertRaises(ValueError):
            a.physical_check(data, data, pins, pins[:-1], text, text)

    def test_die_rows_tracks_and_wire_width_change_fail(self):
        data, pins, text = physical_fixture()
        for before, after in [('1974000', '1975000'), ('STEP 1', 'STEP 2'), ('TopMetal2 4200', 'TopMetal2 4201')]:
            with self.assertRaises(ValueError):
                a.physical_check(data, data, pins, pins, text, text.replace(before, after))

    def test_port_direction_change_fails(self):
        data, pins, text = physical_fixture()
        after = copy.deepcopy(data)
        after[2][0]['io_type'] = 'OUTPUT'
        with self.assertRaisesRegex(ValueError, 'top port'):
            a.physical_check(data, after, pins, pins, text, text)

    def test_def_wildcard_requires_actual_power_terminal_not_implicit_net(self):
        data = [[{'name': 'one', 'master': 'dummy'}], [{'instance': 'one', 'pin': 'VDD', 'net': 'VDD', 'io_type': 'INOUT', 'signal_type': 'POWER'}], []]
        text = 'UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 1 1 ) ;\nCOMPONENTS 1 ;\n- one dummy ;\nEND COMPONENTS\nNETS 0 ;\nEND NETS\nSPECIALNETS 1 ;\n- VDD ( * VDD ) + USE POWER ;\nEND SPECIALNETS\n'
        self.assertEqual(a.def_export_check(*data, text)['actual_exported_pg_terminals_expanded_from_def_wildcards'], 1)
        bad = copy.deepcopy(data)
        bad[1][0]['net'] = 'VSS'
        with self.assertRaises(ValueError): a.def_export_check(*bad, text)
        with self.assertRaises(ValueError): a.def_export_check(*data, text.replace('( * VDD )', '( * arbitrary )'))


if __name__ == '__main__':
    unittest.main()
