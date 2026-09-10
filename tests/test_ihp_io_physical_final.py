# SPDX-License-Identifier: Apache-2.0
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_ihp_io_physical_final import exact_scope,terminal,exact_command,CELLS
class IOFinalTests(unittest.TestCase):
    def evidence(self):
        state={'Status':'exited','Running':False,'OOMKilled':False,'ExitCode':0}
        return {'returncode':0,'terminal_state':state},{'state_returncode':0,'state':copy.deepcopy(state)}
    def test_exact_cli_arguments(self):exact_command(['--mp 1 --density_thr 1 --run_mode deep --antenna'])
    def test_mp_prefix_rejected(self):
        with self.assertRaises(ValueError):exact_command(['--mp 16 --density_thr 1 --run_mode deep --antenna'])
    def test_density_prefix_rejected(self):
        with self.assertRaises(ValueError):exact_command(['--mp 1 --density_thr 10 --run_mode deep --antenna'])
    def test_duplicate_argument_rejected(self):
        with self.assertRaises(ValueError):exact_command(['--mp 1 --mp 1 --density_thr 1 --run_mode deep --antenna'])
    def test_exact_scope(self):exact_scope(CELLS[:2],CELLS,CELLS)
    def test_empty_arms_rejected(self):
        with self.assertRaises(ValueError):exact_scope([],CELLS,CELLS)
    def test_missing_label_macro_rejected(self):
        with self.assertRaises(ValueError):exact_scope(CELLS[:2],CELLS,CELLS[:2])
    def test_terminal_pass(self):terminal(*self.evidence(),{0})
    def test_independent_disagreement(self):
        e,o=self.evidence();o['state']['ExitCode']=1
        with self.assertRaises(ValueError):terminal(e,o,{0})
    def test_running_zero_exit_rejected(self):
        e,o=self.evidence();e['terminal_state']['Running']=True;o['state']['Running']=True
        with self.assertRaises(ValueError):terminal(e,o,{0})
    def test_nonexited_zero_exit_rejected(self):
        e,o=self.evidence();e['terminal_state']['Status']='created';o['state']['Status']='created'
        with self.assertRaises(ValueError):terminal(e,o,{0})
    def test_oom_rejected(self):
        e,o=self.evidence();e['terminal_state']['OOMKilled']=True;o['state']['OOMKilled']=True
        with self.assertRaises(ValueError):terminal(e,o,{0})
if __name__=='__main__':unittest.main()
