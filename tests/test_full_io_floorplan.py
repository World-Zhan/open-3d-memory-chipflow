# SPDX-License-Identifier: Apache-2.0
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_full_io_floorplan import check_pg, check_terminals, pin_signatures


class FullFloorplanEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.signatures = {f'p{i}': (f'n{i}', 'INOUT', 'SIGNAL') for i in range(52)}
        self.pins, self.bonds = [], []
        for i in range(64):
            port = i % 52
            rect = dict(net=f'n{port}', xmin=str(i*100), ymin='0', xmax=str(i*100+70), ymax='70')
            self.pins.append(dict(rect, port=f'p{port}', io_type='INOUT', signal_type='SIGNAL', layer='TopMetal2', placement_status='FIRM'))
            self.bonds.append(dict(rect, instance=f'bond{i}'))
        self.pg = [dict(net=n, tcl_catch_code='0', message='1') for n in ('VDD', 'VSS')]
        self.log = '\n'.join(f'STATIC_PG_CHECK_BEGIN {n}\n[INFO PSM-0040] All shapes on net {n} are connected.\nSTATIC_PG_CHECK_END {n} catch=0' for n in ('VDD', 'VSS')) + '\nFULL_FLOORPLAN_READBACK_COMPLETE'
        self.tcl = 'check_power_grid -net $net -floorplanning -error_file /output/error.rpt'

    def terminal_check(self, pins=None, bonds=None):
        return check_terminals(self.pins if pins is None else pins, self.bonds if bonds is None else bonds, self.signatures, self.signatures)

    def test_valid_complete_terminal_contract(self):
        self.assertTrue(self.terminal_check())

    def test_swapped_ports_do_not_pass_equal_net_box_inventory(self):
        pins = copy.deepcopy(self.pins)
        pins[0]['port'], pins[1]['port'] = pins[1]['port'], pins[0]['port']
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.terminal_check(pins=pins)

    def test_wrong_layer_status_type_or_geometry_rejected(self):
        for key, value in [('layer', 'Metal1'), ('placement_status', 'UNPLACED'), ('signal_type', 'POWER'), ('xmax', '0')]:
            with self.subTest(key=key):
                pins = copy.deepcopy(self.pins)
                pins[0][key] = value
                with self.assertRaises(ValueError):
                    self.terminal_check(pins=pins)

    def test_missing_pin_and_duplicate_bond_rejected(self):
        with self.assertRaises(ValueError):
            self.terminal_check(pins=self.pins[:-1])
        bonds = copy.deepcopy(self.bonds)
        bonds[-1]['instance'] = bonds[0]['instance']
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.terminal_check(bonds=bonds)

    def test_pg_requires_positive_physical_message(self):
        self.assertTrue(check_pg(self.pg, self.log, self.tcl))
        with self.assertRaisesRegex(ValueError, 'positive'):
            check_pg(self.pg, self.log.replace('All shapes on net VDD are connected.', 'No connectivity conclusion.'), self.tcl)

    def test_pg_missing_failed_wrong_scope_or_errors_rejected(self):
        bad = copy.deepcopy(self.pg)
        bad[0]['message'] = '0'
        for rows, log, tcl in [(bad, self.log, self.tcl), (self.pg[:1], self.log, self.tcl), (self.pg, self.log+'\n[ERROR PSM-0069] disconnected', self.tcl), (self.pg, self.log, 'check_power_grid -net $net')]:
            with self.assertRaises(ValueError):
                check_pg(rows, log, tcl)

    def test_def_requires_count_and_complete_unique_signatures(self):
        line = '- p0 + NET n0 + DIRECTION INOUT + USE SIGNAL ;\n'
        self.assertEqual(pin_signatures('PINS 1 ;\n'+line+'END PINS\n'), {'p0': ('n0','INOUT','SIGNAL')})
        for text in ['PINS 2 ;\n'+line+'END PINS', 'PINS 2 ;\n'+line+line+'END PINS', 'PINS 1 ;\n- p0 + NET n0 ;\nEND PINS']:
            with self.assertRaises(ValueError):
                pin_signatures(text)


if __name__ == '__main__':
    unittest.main()
