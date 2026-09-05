# SPDX-License-Identifier: Apache-2.0
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_io_ring_composite_v3 import (
    CHANGES, IMAGE, sha, validate_arguments, validate_command,
    timestamp, validate_deep_outputs, validate_runtime_source_inventory, validate_terminal,
)


class CompositeV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)/'fixture-deep1'
        self.folder.mkdir()
        self.state = dict(Status='exited', ExitCode=0, Pid=0, Error='', Running=False,
                          OOMKilled=False, Dead=False, Paused=False, Restarting=False,
                          StartedAt='2026-09-05T10:00:00Z', FinishedAt='2026-09-05T10:01:00Z')
        self.terminal = dict(state_returncode=0, resources_returncode=0, state=self.state,
                             observed_at='2026-09-05T10:01:01Z',
                             resources=dict(Name=self.folder.name, Container=self.folder.name, ID='abcdef'))
        running = dict(self.state, Status='running', Running=True, Pid=42,
                       FinishedAt='0001-01-01T00:00:00Z')
        self.samples = [dict(state_returncode=0, resources_returncode=0, state=running,
                             observed_at='2026-09-05T10:00:30Z',
                             resources=dict(self.terminal['resources'], MemUsage='3.5GiB / 8GiB'))]
        self.manifest = dict(returncode=0, status='completed', execution_complete=True,
                             outer_timeout_expired=False, timeout_verbose_signal_lines=[],
                             terminal_container_state=self.state, maximal_raw_markers=0,
                             started_at='2026-09-05T09:59:59Z', finished_at='2026-09-05T10:01:02Z',
                             elapsed_seconds=63)
        log = ('Klayout will use 1 thread(s)\n'
               'deep mode is enabled for sg13g2_maximal runset.\n'
               'Number of DRC errors for maximum rule set: 0\n'
               'DRC run for maximum ruleSet completed in 60.0 seconds\n')
        for name in ('tool.log', 'maximal.log'):
            (self.folder/name).write_text(log)
        self.report = self.folder/'maximal.lyrdb'
        self.report.write_text('<report-database><top-cell>io_ring_sealed</top-cell>'
            '<cells><cell><name>io_ring_sealed</name></cell></cells>'
            '<categories><category><name>M1.a</name></category></categories><items/></report-database>')
        (self.folder/'terminal_observation.json').write_text(json.dumps(self.terminal))
        (self.folder/'resource_samples.json').write_text(json.dumps(self.samples))
        self.rehash()

    def rehash(self):
        self.manifest['outputs_sha256'] = {p.name:sha(p) for p in self.folder.iterdir()}

    def validate(self):
        return validate_deep_outputs(self.folder, self.manifest, {'M1.a'})

    def test_success_requires_real_terminal_and_report_evidence(self):
        facts = self.validate()
        self.assertEqual(facts['markers'], 0)
        self.assertEqual(facts['sampled_max_memory_mib'], 3584)
        self.assertTrue(facts['terminal_container_state_verified'])

    def test_docker_nanosecond_timestamps_supported_on_python310(self):
        self.assertEqual(timestamp('2026-09-05T10:33:52.24413955Z').microsecond, 244139)
        self.assertEqual(timestamp('2026-09-05T10:39:44.682103377Z').microsecond, 682103)

    def test_runtime_sources_require_deep_runner_and_preservation(self):
        good = dict(source_sha256={'scripts/run_io_ring_maximal_diagnostic.py':'a'*64},
                    source_hashes_unchanged=True)
        validate_runtime_source_inventory(good)
        for bad in [dict(good, source_sha256={}), dict(good, source_hashes_unchanged=False),
                    dict(good, source_hashes_unchanged=None)]:
            with self.assertRaises(ValueError):
                validate_runtime_source_inventory(bad)

    def test_manifest_time_disagreement_and_nonfinite_elapsed_rejected(self):
        bad = [('started_at','2026-09-05T10:00:01Z'), ('finished_at','2026-09-05T10:00:59Z')]
        bad += [('elapsed_seconds', value) for value in [None,False,-1,946,float('nan'),float('inf'),3]]
        for key, value in bad:
            with self.assertRaises(ValueError):
                validate_terminal(dict(self.manifest, **{key:value}), self.terminal, self.samples, self.folder.name)

    def test_missing_terminal_or_resource_hash_cannot_pass(self):
        for name in ('terminal_observation.json', 'resource_samples.json'):
            self.rehash()
            del self.manifest['outputs_sha256'][name]
            with self.assertRaises(ValueError):
                self.validate()

    def test_running_oom_and_noninteger_terminal_codes_cannot_pass(self):
        for key, values in {'Status':['running'], 'ExitCode':[False, '0', 137],
                            'Running':[True, None], 'OOMKilled':[True, None],
                            'Pid':[False, 42], 'Dead':[True], 'Error':['failed']}.items():
            for value in values:
                terminal, manifest = copy.deepcopy(self.terminal), copy.deepcopy(self.manifest)
                terminal['state'][key] = value
                manifest['terminal_container_state'] = terminal['state']
                with self.assertRaises(ValueError):
                    validate_terminal(manifest, terminal, self.samples, self.folder.name)

    def test_disagreement_with_terminal_file_is_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['terminal_container_state']['ExitCode'] = 137
        with self.assertRaises(ValueError):
            validate_terminal(manifest, self.terminal, self.samples, self.folder.name)

    def test_missing_samples_other_container_and_wrong_time_rejected(self):
        invalid = [[]]
        for field, value in [('ID','another-id'), ('Name','another-run'), ('MemUsage','0B / 0B')]:
            samples = copy.deepcopy(self.samples)
            samples[0]['resources'][field] = value
            invalid.append(samples)
        samples = copy.deepcopy(self.samples)
        samples[0]['observed_at'] = '2026-09-05T10:02:00Z'
        invalid.append(samples)
        for samples in invalid:
            with self.assertRaises(ValueError):
                validate_terminal(self.manifest, self.terminal, samples, self.folder.name)

    def test_timeout_or_missing_observation_codes_rejected(self):
        for key, value in [('returncode', False), ('outer_timeout_expired', True),
                           ('timeout_verbose_signal_lines', ['timeout: sending signal TERM'])]:
            manifest = dict(self.manifest, **{key:value})
            with self.assertRaises(ValueError):
                validate_terminal(manifest, self.terminal, self.samples, self.folder.name)
        terminal = dict(self.terminal, state_returncode=False)
        with self.assertRaises(ValueError):
            validate_terminal(self.manifest, terminal, self.samples, self.folder.name)

    def test_rule_or_mode_changes_are_rejected(self):
        original = ['klayout', '-rd', 'run_mode=deep', '-rd', 'no_recommended=false']
        original += [arg for token in CHANGES for arg in ('-rd', token)]
        expected = [CHANGES.get(arg, arg) for arg in original]
        validate_arguments(original, expected)
        for source, target in [('run_mode=deep','run_mode=flat'),
                               ('no_recommended=false','no_recommended=true'), ('threads=1','threads=2')]:
            bad = [target if arg == source else arg for arg in expected]
            with self.assertRaises(ValueError):
                validate_arguments(original, bad)

    def test_shell_image_and_mount_changes_are_rejected(self):
        import shlex
        root = Path('/worktree')
        replay = root/'runs/run'
        original = ['klayout', '-rd', 'run_mode=deep']
        original += [arg for token in CHANGES for arg in ('-rd', token)]
        actual = [CHANGES.get(arg, arg) for arg in original]
        command = ['docker','run','--name','run','--cpus','2','--memory','8g','--user','1000:1000',
                   '-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/bin/bash',
                   '-v',f'{root}:/work:ro','-v',f'{replay}:/output:rw',IMAGE,'-lc',
                   shlex.join(['timeout','--verbose','--signal=TERM','--kill-after=15s','900s',*actual])]
        manifest = dict(command=command, original_rule_command=original, replay_rule_command=actual,
                        changed_rule_arguments=[[x,CHANGES[x]] for x in original if x in CHANGES],run_id='run',
                        limits=dict(cpus=2,memory_gb=8,inner_seconds=900,kill_grace_seconds=15,outer_seconds=945))
        validate_command(root, replay, manifest, original)
        for index, value in [(20,'untrusted:latest'),(17,'/other:/work:ro'),(22,command[-1]+'; true')]:
            bad = copy.deepcopy(manifest)
            bad['command'][index] = value
            with self.assertRaises(ValueError):
                validate_command(root, replay, bad, original)

    def test_log_count_mode_error_and_report_mismatch_rejected(self):
        log = self.folder/'tool.log'
        text = log.read_text()
        for bad in [text.replace('rule set: 0','rule set: 3'),
                    text.replace('deep mode','flat mode'), text+'ERROR: late crash\n']:
            log.write_text(bad)
            self.rehash()
            with self.assertRaises(ValueError):
                self.validate()
        log.write_text(text)
        self.report.write_text('<report-database/>')
        self.rehash()
        with self.assertRaises(ValueError):
            self.validate()


if __name__ == '__main__':
    unittest.main()
