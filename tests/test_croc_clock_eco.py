# SPDX-License-Identifier: Apache-2.0
import unittest
from test_contracts import ROOT, load_module
eco=load_module('validate_croc_clock_eco',ROOT/'scripts/validate_croc_clock_eco.py')


def fixture(candidate=True,wrong_load=False,missing_supply=False):
    cells=[]; nets={'VDD':[], 'VSS':[]}
    for branch in range(4):
        driver=f'drv{branch}'
        cells.append((driver,'sg13g2_buf_16'))
        net=f'clk{branch}'
        nets[net]=[(driver,'X')]
        for group in range(2):
            buf=f'eco_cts_b{branch}_g{group}'
            if candidate:
                cells.append((buf,'sg13g2_buf_8'))
                nets[net].append((buf,'A'))
                nets[buf]=[(buf,'X')]
                if not missing_supply:
                    nets['VDD'].append((buf,'VDD')); nets['VSS'].append((buf,'VSS'))
            for index in range(8):
                sink=f's{branch}_{group}_{index}'
                cells.append((sink,'sg13g2_dfrbp_1'))
                target=buf if candidate else net
                pin='D' if wrong_load and index==0 else 'CLK'
                nets[target].append((sink,pin))
    lines=['UNITS DISTANCE MICRONS 1000 ;','DIEAREA ( 0 0 ) ( 100000 100000 ) ;',f'COMPONENTS {len(cells)} ;']
    lines += [f'- {name} {master} + PLACED ( 0 0 ) N ;' for name,master in cells]
    lines += ['END COMPONENTS','NONDEFAULTRULES 1 ;','- CTS_NDR_1 + LAYER Metal2 WIDTH 200 SPACING 420 ;','END NONDEFAULTRULES',f'NETS {len(nets)} ;']
    lines += [f'- {name} '+ ' '.join(f'( {i} {p} )' for i,p in pins)+ (' + USE CLOCK + NONDEFAULTRULE CTS_NDR_1' if name not in ('VDD','VSS') else '') +' ;' for name,pins in nets.items()]
    lines += ['END NETS','SPECIALNETS 0 ;','END SPECIALNETS']
    return '\n'.join(lines)


class ClockEcoTests(unittest.TestCase):
    def test_buffer_collapse_preserves_all_connectivity(self):
        self.assertEqual(eco.validate(fixture(False),fixture())['added_buffers'],8)
    def test_clock_reconnected_to_data_pin_is_rejected(self):
        with self.assertRaises(ValueError): eco.validate(fixture(False),fixture(wrong_load=True))
    def test_unpowered_buffers_are_rejected(self):
        with self.assertRaises(ValueError): eco.validate(fixture(False),fixture(missing_supply=True))
    def test_changed_original_master_is_rejected(self):
        with self.assertRaises(ValueError): eco.validate(fixture(False),fixture().replace('sg13g2_dfrbp_1','sg13g2_inv_1',1))
    def test_incomplete_net_parse_is_rejected(self):
        with self.assertRaises(ValueError): eco.validate(fixture(False),fixture().replace('NETS 14','NETS 15'))

    def test_missing_inherited_ndr_is_rejected(self):
        lines=fixture().splitlines()
        after='\n'.join(line.replace(' + NONDEFAULTRULE CTS_NDR_1','')
                        if line.startswith('- eco_cts_b0_g0 (') else line for line in lines)
        with self.assertRaises(ValueError): eco.validate(fixture(False),after)
    def test_modified_ndr_geometry_is_rejected(self):
        with self.assertRaises(ValueError): eco.validate(fixture(False),fixture().replace('WIDTH 200','WIDTH 100'))
    def test_new_clock_net_as_signal_is_rejected(self):
        with self.assertRaises(ValueError): eco.validate(fixture(False),fixture().replace('+ USE CLOCK', '+ USE SIGNAL'))

    def test_unknown_instance_is_rejected(self):
        with self.assertRaises(ValueError):
            eco.validate(fixture(False),fixture().replace('( eco_cts_b0_g0 X )','( absent X )'))
    def test_duplicate_component_is_rejected(self):
        with self.assertRaises(ValueError):
            eco.validate(fixture(False),fixture().replace('- s0_0_1 sg13g2_dfrbp_1','- s0_0_0 sg13g2_dfrbp_1'))

    def test_existing_pg_wildcard_is_preserved_without_implied_new_supply(self):
        def add_wildcard(text):
            return text.replace('- VDD ', '- VDD ( * VDD ) ',1)
        eco.validate(add_wildcard(fixture(False)),add_wildcard(fixture()))
        with self.assertRaises(ValueError):
            eco.validate(add_wildcard(fixture(False)),add_wildcard(fixture(missing_supply=True)))
        with self.assertRaises(ValueError):
            eco.validate(add_wildcard(fixture(False)),fixture())
