# SPDX-License-Identifier: Apache-2.0
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from probe_ihp_io_physical import lef_macro
from audit_ihp_io_physical import completion,command_is_strict
from audit_bondpad_drc import antenna_categories

LEF='MACRO io\nSIZE 80 BY 180 ;\nPIN pad\nDIRECTION OUTPUT ;\nUSE SIGNAL ;\nPORT\nLAYER Metal2 ;\nRECT 5 0 75 3 ;\nEND\nEND pad\nEND io\n'
class IOPhysicalTests(unittest.TestCase):
    def inputs(self):
        main='\n'.join(x+' enabled: true' for x in ('FEOL','BEOL','OFFGRID','ANGLE','PIN','FORBIDDEN','RECOMMENDED','CONNECTIVITY_RULES'))+"\nPreCheck DRC enabled: false\nrun for tables 'main' completed in 2.1 seconds"
        return [main,'run for density table completed in 0.2 seconds','Executing rule Ant.i','run for maximum ruleSet completed in 1.2 seconds','Total DRC Run time:',antenna_categories(),{'Status':'exited','Running':False,'OOMKilled':False,'ExitCode':1},1]
    def test_parse_exact_lef_pin(self):self.assertEqual(lef_macro(LEF,'io')['pins']['pad']['rects'][0]['um'],[5,0,75,3])
    def test_missing_macro(self):
        with self.assertRaises(ValueError):lef_macro(LEF,'other')
    def test_duplicate_macro(self):
        with self.assertRaises(ValueError):lef_macro(LEF+LEF,'io')
    def test_unknown_layer(self):
        with self.assertRaises(ValueError):lef_macro(LEF.replace('Metal2','Unknown'),'io')
    def test_empty_rectangle(self):
        with self.assertRaises(ValueError):lef_macro(LEF.replace('75 3','5 3'),'io')
    def test_missing_pin_use(self):
        with self.assertRaises(ValueError):lef_macro(LEF.replace('USE SIGNAL ;',''),'io')
    def test_completed_violation_exit_is_execution_not_signoff(self):self.assertTrue(all(completion(*self.inputs()).values()))
    def test_oom_not_complete(self):
        args=self.inputs();args[6]['OOMKilled']=True;self.assertFalse(all(completion(*args).values()))
    def test_disabled_offgrid_not_complete(self):
        args=self.inputs();args[0]=args[0].replace('OFFGRID enabled: true','OFFGRID enabled: false');self.assertFalse(all(completion(*args).values()))
    def test_missing_antenna_category_not_complete(self):
        args=self.inputs();args[5].remove('Ant.i');self.assertFalse(all(completion(*args).values()))
    def test_incomplete_maximal_not_complete(self):
        args=self.inputs();args[3]='Starting maximal';self.assertFalse(all(completion(*args).values()))
    def test_tool_exception_not_complete(self):
        args=self.inputs();args[4]+=' generated an exception';self.assertFalse(all(completion(*args).values()))
    def test_strict_command(self):self.assertTrue(command_is_strict(['--mp 1 --run_mode deep --density_thr 1 --antenna']))
    def test_no_density_command_rejected(self):self.assertFalse(command_is_strict(['--mp 1 --run_mode deep --density_thr 1 --antenna --no_density']))
if __name__=='__main__':unittest.main()
