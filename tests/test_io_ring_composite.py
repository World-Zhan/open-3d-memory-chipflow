# SPDX-License-Identifier: Apache-2.0
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_io_ring_composite import CHANGES, execution_gate, validate_arguments


class CompositeAuditTests(unittest.TestCase):
    def setUp(self):
        self.expected = {f'rule_{n}' for n in range(39)} | {'sg13g2_maximal'}
        self.observed = {n: True for n in self.expected - {'sg13g2_maximal'}}
        self.replay = dict(returncode=0, terminal_completion=True, error_free=True,
                           markers=0, source_identity_verified=True)

    def gate(self, **changes):
        replay = dict(self.replay, **changes)
        return execution_gate(self.expected, self.observed, ['sg13g2_maximal'], replay)

    def test_replay_does_not_rehabilitate_exit11_or_timeout(self):
        self.assertTrue(self.gate())
        self.assertFalse(self.gate(returncode=11))
        self.assertFalse(self.gate(returncode=124))
        self.assertFalse(self.gate(error_free=False))
        self.assertFalse(self.gate(terminal_completion=False))
        self.assertFalse(self.gate(source_identity_verified=False))

    def test_missing_report_or_task_cannot_complete(self):
        self.assertFalse(self.gate(markers=None))
        self.assertFalse(self.gate(markers=False))
        self.assertFalse(self.gate(markers=-1))
        self.observed.pop('rule_0')
        self.assertFalse(self.gate())

    def test_additional_failed_task_cannot_be_waived(self):
        self.assertFalse(execution_gate(self.expected, self.observed,
                         ['sg13g2_maximal', 'antenna'], self.replay))
        self.observed['rule_0'] = False
        self.assertFalse(self.gate())

    def test_rule_weakening_and_input_substitution_rejected(self):
        original = ['klayout', *CHANGES, 'no_recommended=false', 'input=/same.gds']
        actual = [CHANGES.get(x, x) for x in original]
        validate_arguments(original, actual)
        for index, value in ((-2, 'no_recommended=true'), (-1, 'input=/other.gds')):
            changed = copy.copy(actual)
            changed[index] = value
            with self.assertRaises(ValueError):
                validate_arguments(original, changed)
