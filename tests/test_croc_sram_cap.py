# SPDX-License-Identifier: Apache-2.0
import copy
import sys
import unittest
from test_contracts import ROOT, load_module
sys.path.insert(0, str(ROOT / 'scripts'))
a = load_module('audit_croc_sram_cap', ROOT / 'scripts/audit_croc_sram_cap.py')


def fixture(candidate):
    cells = [('ram0', 'RM_IHPSG13_1P_512x32_c2_bm_bist'), ('ram1', 'RM_IHPSG13_1P_512x32_c2_bm_bist'), ('clock_driver', 'sg13g2_buf_4')]
    nets = {'VDD': [('*', 'VDD')], 'VSS': [('*', 'VSS')], 'clock_net': [('clock_driver', 'X')]}
    branches = []
    for bank in range(2):
        for bit in range(32):
            name, net = f'eco_sram_cap_b{bank}_d{bit:02d}', f'data{bank}_{bit}'
            driver = (f'ram{bank}', f'A_DOUT[{bit}]')
            loads = [(f'sink{bank}_{bit}_{i}', 'A') for i in range(4)]
            cells.extend((inst, 'sg13g2_buf_1') for inst, _ in loads)
            branches.append({'buffer': name, 'net': net, 'instance': driver[0], 'pin': driver[1],
                             'loads': [inst + '/' + pin for inst, pin in loads]})
            if candidate:
                cells.append((name, 'sg13g2_buf_4'))
                nets[net] = [driver, (name, 'A')]
                nets[name] = [(name, 'X')] + loads
                nets['VDD'].append((name, 'VDD'))
                nets['VSS'].append((name, 'VSS'))
            else:
                nets[net] = [driver] + loads
    lines = ['UNITS DISTANCE MICRONS 1000 ;', 'DIEAREA ( 0 0 ) ( 100000 100000 ) ;', f'COMPONENTS {len(cells)} ;']
    lines += [f'- {name} {master} + PLACED ( 1000 1000 ) N ;' for name, master in cells]
    lines += ['END COMPONENTS', 'NONDEFAULTRULES 1 ;', '- NDR + LAYER Metal2 WIDTH 200 SPACING 420 ;', 'END NONDEFAULTRULES', f'NETS {len(nets)} ;']
    for net, pins in nets.items():
        attr = ' + USE CLOCK + NONDEFAULTRULE NDR' if net == 'clock_net' else ' + USE SIGNAL'
        if net in ('VDD', 'VSS'):
            attr = ' + USE ' + ('POWER' if net == 'VDD' else 'GROUND')
        lines.append('- ' + net + ' ' + ' '.join(f'( {inst} {pin} )' for inst, pin in pins) + attr + ' ;')
    lines += ['END NETS', 'SPECIALNETS 0 ;', 'END SPECIALNETS']
    return '\n'.join(lines), branches


class SramCapTests(unittest.TestCase):
    def setUp(self):
        self.before, self.branches = fixture(False)
        self.after, _ = fixture(True)

    def test_exact_64_output_buffers_preserve_every_original_connection(self):
        result = a.prove_buffers(self.before, self.after, self.branches)
        self.assertEqual(result['new_buffers'], 64)
        self.assertEqual(result['clock_ndr']['routing_ndr_policy_qualification'], 'UNVERIFIED')

    def test_changed_functional_load_pin_rejected(self):
        with self.assertRaisesRegex(ValueError, 'four original loads'):
            a.prove_buffers(self.before, self.after.replace('( sink0_0_0 A )', '( sink0_0_0 X )'), self.branches)

    def test_remaining_unbuffered_load_rejected(self):
        changed = self.after.replace('( ram0 A_DOUT[0] ) ( eco_sram_cap_b0_d00 A )', '( ram0 A_DOUT[0] ) ( eco_sram_cap_b0_d00 A ) ( sink0_0_0 A )')
        with self.assertRaises(ValueError):
            a.prove_buffers(self.before, changed, self.branches)

    def test_implicit_pg_wildcard_does_not_replace_explicit_new_supply(self):
        with self.assertRaisesRegex(ValueError, 'explicit VDD/VSS'):
            a.prove_buffers(self.before, self.after.replace('( eco_sram_cap_b0_d00 VDD )', ''), self.branches)

    def test_wrong_buffer_master_rejected(self):
        with self.assertRaisesRegex(ValueError, 'buffer master'):
            a.prove_buffers(self.before, self.after.replace('eco_sram_cap_b0_d00 sg13g2_buf_4', 'eco_sram_cap_b0_d00 sg13g2_inv_4'), self.branches)

    def test_original_master_change_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Original instance/master'):
            a.prove_buffers(self.before, self.after.replace('sink0_0_0 sg13g2_buf_1', 'sink0_0_0 sg13g2_inv_1'), self.branches)

    def test_changed_original_clock_ndr_rejected(self):
        with self.assertRaisesRegex(ValueError, 'NDR definitions'):
            a.prove_buffers(self.before, self.after.replace('WIDTH 200', 'WIDTH 100'), self.branches)

    def test_new_data_buffer_net_must_not_become_clock(self):
        changed = '\n'.join(line.replace('USE SIGNAL', 'USE CLOCK') if line.startswith('- eco_sram_cap_b0_d00 (') else line for line in self.after.splitlines())
        with self.assertRaisesRegex(ValueError, 'wrong identity/use/NDR'):
            a.prove_buffers(self.before, changed, self.branches)

    def test_missing_or_duplicate_diagnosed_buffer_rejected(self):
        with self.assertRaisesRegex(ValueError, '64 unique'):
            a.prove_buffers(self.before, self.after, self.branches[:-1])
        changed = copy.deepcopy(self.branches)
        changed[-1] = changed[0]
        with self.assertRaisesRegex(ValueError, '64 unique'):
            a.prove_buffers(self.before, self.after, changed)

    def test_original_placement_status_and_geometry_must_be_restored(self):
        before = [{'name': 'cell', 'master': 'buffer', 'status': 'PLACED', 'xmin': '100'}]
        self.assertEqual(a.original_geometry(before, copy.deepcopy(before))['result'], 'PASS')
        for key, value in [('status', 'FIRM'), ('xmin', '101')]:
            changed = copy.deepcopy(before)
            changed[0][key] = value
            with self.assertRaisesRegex(ValueError, 'Original geometry'):
                a.original_geometry(before, changed)

    def test_incomplete_cap_report_cannot_prove_sram_clear(self):
        with self.assertRaisesRegex(ValueError, 'cap report section'):
            a.sram_violations('max slew\n')
        self.assertEqual(a.sram_violations('max capacitance\npad/pad 4.0 15.0 -11.0 (VIOLATED)\n'), [])

    def test_duplicate_sram_violations_rejected(self):
        line = 'ram/A_DOUT[0] 0.06 0.1 -0.04 (VIOLATED)\n'
        with self.assertRaisesRegex(ValueError, 'Duplicate SRAM'):
            a.sram_violations('max capacitance\n' + line + line)


if __name__ == '__main__':
    unittest.main()
