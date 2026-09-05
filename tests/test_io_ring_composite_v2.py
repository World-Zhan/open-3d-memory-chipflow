# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_io_ring_composite_v2 import execution_gate, validate_replay_report, validate_report, sha


class CompositeV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.categories = {'M1.a', 'LBE.f'}
        self.good = '<report-database><top-cell>io_ring_sealed</top-cell><cells><cell><name>io_ring_sealed</name></cell></cells><categories><category><name>M1.a</name></category><category><name>LBE.f</name></category></categories><items/></report-database>'
        for name in ('tool.log', 'maximal.log'):
            (self.folder/name).write_text('completed')
        self.report = self.folder/'maximal.lyrdb'
        self.report.write_text(self.good)

    def manifest(self, rc=0):
        return {'returncode': rc, 'outputs_sha256': {p.name: sha(p) for p in self.folder.iterdir()}}

    def test_valid_empty_report_has_known_zero(self):
        facts = validate_replay_report(self.folder, self.manifest(), self.categories, 'io_ring_sealed')
        self.assertEqual(facts['markers'], 0)
        self.assertTrue(facts['report_structure_valid'])
        self.assertTrue(facts['required_output_hashes_verified'])

    def test_success_requires_each_output_hash(self):
        for name in ('tool.log', 'maximal.log', 'maximal.lyrdb'):
            manifest = self.manifest()
            del manifest['outputs_sha256'][name]
            with self.assertRaises(ValueError):
                validate_replay_report(self.folder, manifest, self.categories, 'io_ring_sealed')

    def test_bool_string_and_missing_exit_codes_rejected(self):
        for rc in (False, True, '0', None):
            with self.assertRaises(ValueError):
                validate_replay_report(self.folder, self.manifest(rc), self.categories, 'io_ring_sealed')
        expected = {'sg13g2_maximal'} | {str(i) for i in range(39)}
        facts = dict(returncode=False, terminal_completion=True, error_free=True, markers=0, source_identity_verified=True,
                     report_structure_valid=True, required_output_hashes_verified=True)
        self.assertFalse(execution_gate(expected, {n: True for n in expected-{'sg13g2_maximal'}}, ['sg13g2_maximal'], facts))

    def test_failed_missing_report_stays_unknown(self):
        self.report.unlink()
        facts = validate_replay_report(self.folder, self.manifest(137), self.categories, 'io_ring_sealed')
        self.assertIsNone(facts['markers'])
        self.assertFalse(facts['report_structure_valid'])
        self.assertFalse(facts['required_output_hashes_verified'])

    def test_forged_or_incomplete_XML_cannot_be_zero_markers(self):
        bad = ['<empty/>', '<report-database/>', self.good.replace('<items/>', ''),
               self.good.replace('<cells>', '<other>').replace('</cells>', '</other>'),
               self.good.replace('<categories>', '<other>').replace('</categories>', '</other>'),
               self.good.replace('<top-cell>io_ring_sealed</top-cell>', '<top-cell>another_chip</top-cell>'),
               self.good.replace('<name>LBE.f</name>', '<name>invented_rule</name>'),
               self.good.replace('<category><name>LBE.f</name></category>', '')]
        for text in bad:
            self.report.write_text(text)
            with self.assertRaises(ValueError):
                validate_replay_report(self.folder, self.manifest(), self.categories, 'io_ring_sealed')

    def test_failed_malformed_report_stays_incomplete(self):
        self.report.write_text('<report-database>')
        facts = validate_replay_report(self.folder, self.manifest(137), self.categories, 'io_ring_sealed')
        self.assertIsNone(facts['markers'])
        self.assertFalse(facts['report_structure_valid'])

    def test_changed_output_and_invalid_marker_rejected(self):
        manifest = self.manifest()
        self.report.write_text(self.good+' ')
        with self.assertRaises(ValueError):
            validate_replay_report(self.folder, manifest, self.categories, 'io_ring_sealed')
        self.report.write_text(self.good.replace('<items/>', '<items><item><category>not-a-rule</category><cell>io_ring_sealed</cell><values/></item></items>'))
        with self.assertRaises(ValueError):
            validate_report(self.report, self.categories, 'io_ring_sealed')
