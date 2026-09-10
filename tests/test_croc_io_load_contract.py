# SPDX-License-Identifier: Apache-2.0
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_croc_io_load_contract import digital_io_limits, classify_violations

LIB='capacitive_load_unit(1,pf); cell(sg13g2_IOPadOut30mA) {pin(pad){direction:output; max_capacitance:4.53171;}}'
REPORT='max slew\nPin Limit Slew Slack\npad_uart_tx_o/pad 1.20 3.55 -2.35 (VIOLATED)\nmax fanout\nPin Limit Fanout Slack\nclkbuf_2_0/X 8 16 -8 (VIOLATED)\nmax capacitance\nPin Limit Cap Slack\ngpio0_io 4.21 15.37 -11.16 (VIOLATED)\nx/A_DOUT[3] 0.06 0.09 -0.03 (VIOLATED)\n'
class LoadContractTests(unittest.TestCase):
    def test_digital_catalog_ignores_passive_analog(self):
        text=LIB+'cell(sg13g2_IOPadAnalog){pin(pad){direction:inout;max_capacitance:500;}}'
        self.assertEqual(digital_io_limits(text),{'sg13g2_IOPadOut30mA':4.53171})
    def test_unknown_units_rejected(self):
        with self.assertRaises(ValueError):digital_io_limits(LIB.replace('(1,pf)','(1,ff)'))
    def test_missing_limit_rejected(self):
        with self.assertRaises(ValueError):digital_io_limits(LIB.replace('max_capacitance:4.53171;',''))
    def test_duplicate_catalog_rejected(self):
        with self.assertRaises(ValueError):digital_io_limits(LIB+LIB.split(';',1)[1])
    def test_counts_and_receiver_boundary(self):
        rows=classify_violations(REPORT)
        self.assertEqual(rows['max capacitance']['by_category'],{'external_gpio_driver':1,'sram_output':1})
        self.assertEqual(rows['max fanout']['count'],1)
    def test_malformed_violation_rejected(self):
        with self.assertRaises(ValueError):classify_violations(REPORT.replace('8 16 -8','8 BAD -8'))
    def test_unknown_endpoint_retained(self):
        rows=classify_violations(REPORT.replace('gpio0_io','mystery/X'))
        self.assertEqual(rows['max capacitance']['by_category']['unclassified'],1)
    def test_missing_section_rejected(self):
        with self.assertRaises(ValueError):classify_violations(REPORT.replace('max fanout','different'))
if __name__=='__main__':unittest.main()
