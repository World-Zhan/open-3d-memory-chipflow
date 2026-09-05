# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import tempfile
import unittest

from test_contracts import collect_croc


class ElectricalAcceptanceTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.rpt"
            path.write_text(text)
            return collect_croc.final_timing(path)

    def clean_report(self):
        return "wns max 0.00\ntns max 0.00\n" + "".join(
            label + " 0\n" for label in collect_croc.TIMING_COUNTS.values()
        )

    def test_real_opensta_format_catches_electrical_violations(self):
        text = self.clean_report().replace("max slew violation count 0", "max slew violation count 76")
        text = text.replace("max cap violation count 0", "max cap violation count 71")
        text = text.replace("max fanout violation count 0", "max fanout violation count 200")
        timing = self.parse(text)
        self.assertEqual(timing['max_slew_violations'], 76)
        self.assertEqual(timing['max_capacitance_violations'], 71)
        self.assertEqual(timing['max_fanout_violations'], 200)
        checks = collect_croc.timing_checks(timing)
        self.assertTrue(checks['setup_violations_zero'])
        self.assertTrue(checks['hold_violations_zero'])
        self.assertEqual(sum(not passed for passed in checks.values()), 3)

    def test_complete_clean_report_passes(self):
        self.assertTrue(all(collect_croc.timing_checks(self.parse(self.clean_report())).values()))

    def test_each_missing_metric_fails_closed(self):
        lines = self.clean_report().splitlines(keepends=True)
        for omitted in range(len(lines)):
            with self.subTest(omitted=omitted):
                timing = self.parse(''.join(lines[:omitted] + lines[omitted+1:]))
                self.assertFalse(all(collect_croc.timing_checks(timing).values()))

    def test_bad_metric_is_not_hidden_by_clean_duplicate(self):
        for extra in ('wns max nan\n', 'wns max inf\n', 'wns max -0.05\n',
                      'setup violation count unknown\n', 'max cap violation count -1\n',
                      'max cap violation count 1 unexpected\n', 'setup violation count\n',
                      'wns max -1 unexpected\n', 'wns max\n'):
            with self.subTest(extra=extra):
                timing = self.parse(self.clean_report() + extra)
                self.assertFalse(all(collect_croc.timing_checks(timing).values()))

    def test_worst_observation_retained_across_report_sections(self):
        text = self.clean_report() + 'wns max -0.4\ntns max -1.2\nmax cap violation count 4\n'
        timing = self.parse(text)
        self.assertEqual(timing['wns_ns'], -0.4)
        self.assertEqual(timing['tns_ns'], -1.2)
        self.assertEqual(timing['max_capacitance_violations'], 4)

    def test_report_headings_with_named_values(self):
        text = ('05_croc.final report_wns\n----------\nwns max 0.00\n'
                '05_croc.final report_tns\n----------\ntns max 0.00\n')
        timing = self.parse(text)
        self.assertEqual(timing['wns_ns'], 0.0)
        self.assertEqual(timing['tns_ns'], 0.0)


if __name__ == '__main__':
    unittest.main()
