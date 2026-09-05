# SPDX-License-Identifier: Apache-2.0
import csv,copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audit_io_ring_plan import placed_pitch,net_connections,validate_connections


class RingPlanTests(unittest.TestCase):
    def setUp(self):
        self.floor=ROOT/'runs/croc-io-ring-floorplan-20260905-001'
        self.physical=ROOT/'runs/croc-io-ring-physical-20260905-002'
        with (self.floor/'instances.tsv').open() as f:self.rows=list(csv.DictReader(f,delimiter='\t'))

    def test_actual_pitch_and_changed_pitch_rejected(self):
        self.assertEqual(placed_pitch(self.rows)['west']['count'],16)
        self.rows[0]['ymin']=str(int(self.rows[0]['ymin'])+1000)
        self.rows[0]['ymax']=str(int(self.rows[0]['ymax'])+1000)
        with self.assertRaises(ValueError):placed_pitch(self.rows)

    def test_off_site_grid_rejected(self):
        self.rows[0]['ymin']=str(int(self.rows[0]['ymin'])+1)
        with self.assertRaisesRegex(ValueError,'site grid'):placed_pitch(self.rows)

    def test_missing_bond_and_pg_rejected(self):
        names={r['name'] for r in self.rows}
        nets=net_connections((self.physical/'io_ring.def').read_text(),names)
        signals=json.loads((self.floor/'manifest.json').read_text())['original_signal_net_connections_retained']
        self.assertEqual(validate_connections(self.rows,nets,signals)['explicit_bondpad_connections'],64)
        for pin in [('IO_BOND_pad_clk_i','pad'),('pad_clk_i','vdd')]:
            broken=dict(nets);broken.pop(pin)
            with self.assertRaises(ValueError):validate_connections(self.rows,broken,signals)

    def test_conflicting_def_pin_nets_rejected(self):
        text='NETS 2 ;\n- A ( X pad ) ;\n- B ( X pad ) ;\nEND NETS\n'
        with self.assertRaisesRegex(ValueError,'Conflicting'):net_connections(text,{'X'})
