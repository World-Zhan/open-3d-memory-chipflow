# SPDX-License-Identifier: Apache-2.0
import sys, unittest, json, tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_bondpad_integration import density_kind, verify_generated_inputs, sha


class IntegrationAuditTests(unittest.TestCase):
    def test_window_coverage_classified_from_actual_marker(self):
        item = ET.fromstring('<item><values><value>Local Density Window Violation</value></values></item>')
        self.assertEqual(density_kind(item, 'Min. Metal1 coverage ratio'), 'local_window')

    def test_global_and_geometric_fill_spacing_are_distinct(self):
        item = ET.fromstring('<item><values><value>Global Density Violation</value></values></item>')
        self.assertEqual(density_kind(item, ''), 'global')
        self.assertIsNone(density_kind(ET.fromstring('<item/>'), 'Minimum Metal1 filler spacing'))

    def test_generated_gds_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'inputs').mkdir()
            gds = root/'inputs/a.gds'; gds.write_bytes(b'original')
            value = sha(gds)
            facts = root/'inputs/fixture_summary.json'
            facts.write_text(json.dumps({'outputs_sha256': {'a.gds': value}, 'arms': [{'name':'a','gds_sha256':value}]}))
            (root/'manifest.json').write_text(json.dumps({'fixture_summary_sha256':sha(facts),'arms':[{'name':'a','fixture_gds_sha256':value}]}))
            self.assertEqual(verify_generated_inputs(root), {'a':value})
            gds.write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError, 'Generated fixture input changed'):
                verify_generated_inputs(root)
