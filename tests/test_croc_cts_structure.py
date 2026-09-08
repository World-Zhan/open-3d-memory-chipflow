# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from test_contracts import ROOT, load_module
from test_croc_placement_structure import a as base, cell, fixture, library, modify
cts = load_module('audit_croc_cts_structure', ROOT / 'scripts/audit_croc_cts_structure.py')


def definition(data, ndr=''):
    nets = {}
    for row in data[1]:
        if row['net'] not in base.FLOATING:
            nets.setdefault(row['net'], []).append((row['instance'], row['pin']))
    for row in data[2]:
        nets.setdefault(row['net'], []).append(('PIN', row['port']))
    text = ['UNITS DISTANCE MICRONS 1000 ;', 'DIEAREA ( 0 0 ) ( 1 1 ) ;', 'COMPONENTS ' + str(len(data[0])) + ' ;']
    text += ['- ' + row['name'] + ' ' + row['master'] + ' ;' for row in data[0]]
    text += ['END COMPONENTS', 'NETS ' + str(len(nets)) + ' ;']
    text += ['- ' + net + ' ' + ' '.join('( ' + name + ' ' + pin + ' )' for name, pin in pins) + (' + USE CLOCK' + ndr if net == 'a' else ' + USE SIGNAL') + ' ;' for net, pins in nets.items()]
    text += ['END NETS', 'SPECIALNETS 0 ;', 'END SPECIALNETS']
    return '\n'.join(text)


def with_load(master='sg13g2_buf_1', output='X'):
    data = fixture()
    data[0].append({'name': 'clkload0', 'master': master, 'type': 'CORE'})
    data[1] += [{'instance': 'clkload0', 'pin': pin, 'net': net, 'io_type': direction, 'signal_type': kind} for pin, net, direction, kind in [('A', 'a', 'INPUT', 'SIGNAL'), (output, 'UNCONNECTED', 'OUTPUT', 'SIGNAL'), ('VDD', 'VDD', 'INOUT', 'POWER'), ('VSS', 'VSS', 'INOUT', 'GROUND')]]
    return data


class CtsStructureTests(unittest.TestCase):
    def test_buffer_and_inverter_unobserved_loads_have_actual_function_proof(self):
        lib = library()
        lib.update(base.liberty_logic(cell('inv', '!A', ('A',), 'Y')))
        for master, output in [('sg13g2_buf_1', 'X'), ('inv', 'Y')]:
            data = with_load(master, output)
            filtered, loads = cts.abstract_unobserved_loads(fixture(), data, lib, definition(data))
            self.assertEqual(len(loads), 1)
            self.assertEqual(base.compare_logic(fixture(), filtered, lib)['result'], 'PASS')
            self.assertEqual(len(data[0]), 2)  # actual evidence was not mutated

    def test_any_connected_load_output_is_rejected(self):
        for target in ('z', 'isolated_net'):
            data = modify(with_load(), 'clkload0', 'X', net=target)
            with self.assertRaisesRegex(ValueError, 'output has a connection'):
                cts.abstract_unobserved_loads(fixture(), data, library(), definition(data))

    def test_preexisting_load_cannot_be_abstracted(self):
        data = with_load()
        with self.assertRaisesRegex(ValueError, 'newly added'):
            cts.abstract_unobserved_loads(data, data, library(), definition(data))

    def test_state_cell_is_not_an_unobserved_combinational_load(self):
        lib = library()
        lib.update(base.liberty_logic(cell('sg13g2_buf_1', 'IQ', ('A',), extra='ff (IQ,IQN) { next_state : "A"; clocked_on : "A"; }')))
        data = with_load()
        with self.assertRaisesRegex(ValueError, 'stateless'):
            cts.abstract_unobserved_loads(fixture(), data, lib, definition(data))

    def test_additional_pin_cannot_be_ignored(self):
        data = with_load()
        data[1].append({'instance': 'clkload0', 'pin': 'EXTRA', 'net': 'a', 'io_type': 'INPUT', 'signal_type': 'SIGNAL'})
        with self.assertRaisesRegex(ValueError, 'pin inventory'):
            cts.abstract_unobserved_loads(fixture(), data, library(), definition(data))

    def test_unpowered_load_is_rejected(self):
        data = modify(with_load(), 'clkload0', 'VSS', net='UNCONNECTED')
        with self.assertRaisesRegex(ValueError, 'explicit PG'):
            cts.abstract_unobserved_loads(fixture(), data, library(), definition(data))

    def test_load_must_be_on_actual_clock_net(self):
        data = with_load()
        with self.assertRaisesRegex(ValueError, 'CLOCK net'):
            cts.abstract_unobserved_loads(fixture(), data, library(), definition(data).replace('USE CLOCK', 'USE SIGNAL'))

    def test_disagreement_between_def_and_unconnected_export_is_rejected(self):
        data = with_load()
        bad = definition(data).replace('- z ', '- z ( clkload0 X ) ')
        with self.assertRaisesRegex(ValueError, 'DEF connects'):
            cts.abstract_unobserved_loads(fixture(), data, library(), bad)

    def test_delay_is_proven_by_real_signature_and_no_design_mutation(self):
        lib = library()
        lib.update(base.liberty_logic(cell('sg13g2_dlygate4sd3_1', 'A', ('A',))))
        after = fixture(buffer=True)
        after[0][0]['master'] = 'sg13g2_dlygate4sd3_1'
        result = cts.prove_cts_logic(fixture(), after, lib)
        self.assertEqual(len(result['delay_identity_proofs']), 1)
        self.assertEqual(after[0][0]['master'], 'sg13g2_dlygate4sd3_1')
        lib.update(base.liberty_logic(cell('sg13g2_dlygate4sd3_1', '!A', ('A',))))
        with self.assertRaisesRegex(ValueError, 'not identical'):
            cts.prove_cts_logic(fixture(), after, lib)

    def test_one_to_one_inverter_rename_requires_endpoint_equivalence(self):
        lib = library()
        lib.update(base.liberty_logic(cell('inv', '!A', ('A',), 'Y')))
        before = fixture(buffer=True)
        before[0][0]['master'] = 'inv'
        next(row for row in before[1] if row['instance'] == 'buffer' and row['pin'] == 'X')['pin'] = 'Y'
        after = copy.deepcopy(before)
        after[0][0]['name'] = 'buffer_123'
        for row in after[1]:
            if row['instance'] == 'buffer': row['instance'] = 'buffer_123'
        self.assertEqual(len(cts.prove_cts_logic(before, after, lib)['inverter_instance_bijections']), 1)
        modify(after, 'buffer_123', 'A', net='b')
        with self.assertRaisesRegex(ValueError, 'Connectivity changed'):
            cts.prove_cts_logic(before, after, lib)

    def test_undefined_ndr_and_nonclock_ndr_rejected(self):
        data = fixture()
        text = definition(data)
        bad = definition(data, ' + NONDEFAULTRULE missing')
        with self.assertRaisesRegex(ValueError, 'Undefined NDR'):
            cts.audit_clock_ndr(data, data, text, bad, [], library())
        rules = '\nNONDEFAULTRULES 1 ;\n- missing + LAYER M1 WIDTH 1 SPACING 2 ;\nEND NONDEFAULTRULES\n'
        with self.assertRaisesRegex(ValueError, 'Undefined NDR'):
            cts.audit_clock_ndr(data, data, text, bad.replace('USE CLOCK', 'USE SIGNAL') + rules, [], library())

    def test_existing_ndr_geometry_or_assignment_change_rejected(self):
        data = fixture()
        rules = '\nNONDEFAULTRULES 1 ;\n- C + LAYER M1 WIDTH 1 SPACING 2 ;\nEND NONDEFAULTRULES\n'
        text = definition(data, ' + NONDEFAULTRULE C') + rules
        self.assertEqual(cts.audit_clock_ndr(data, data, text, text, [], library())['result'], 'PASS')
        for changed in (text.replace('WIDTH 1', 'WIDTH 2'), text.replace(' + NONDEFAULTRULE C', '')):
            with self.assertRaises(ValueError):
                cts.audit_clock_ndr(data, data, text, changed, [], library())


if __name__ == '__main__': unittest.main()
