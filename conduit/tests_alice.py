"""Tests for the ALICE HPC bundle protocol."""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from django.test import TestCase
from django.core.management import call_command

from conduit.alice import metapact_ga as mpga


class BundleParamsTest(unittest.TestCase):
    def test_defaults_are_conservative(self):
        p = mpga.BundleParams(slug='x')
        # First-bundle safety: small array, short per-task expected
        # runtime, fits well under 4 h cap.
        self.assertLessEqual(p.replicates, 32,
            'first-bundle replicates should stay small')
        # Time cap is HH:MM:SS and parseable.
        h, m, s = p.time_limit.split(':')
        total_min = int(h) * 60 + int(m) + int(s) / 60.0
        self.assertLessEqual(total_min, 240,
            'time limit must fit cpu-short partition (4 h)')


class GenerateBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='alice-bundle-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _make(self, **overrides):
        params = mpga.BundleParams(slug='unit-test', **overrides)
        out = self.tmp / 'unit-test'
        mpga.generate_bundle(out, params)
        return out, params

    def test_bundle_contains_expected_files(self):
        out, p = self._make(replicates=4)
        for name in ('README.md', 'manifest.json', 'submit.sh',
                       'run_task.py', 'push.sh', 'pull.sh', '.gitignore'):
            self.assertTrue((out / name).exists(),
                f'missing {name}')
        # one input JSON per replicate
        inputs = sorted((out / 'inputs').glob('*.json'))
        self.assertEqual(len(inputs), p.replicates)

    def test_manifest_round_trips(self):
        out, p = self._make(replicates=4)
        manifest = json.loads((out / 'manifest.json').read_text())
        self.assertEqual(manifest['kind'], mpga.BUNDLE_KIND)
        self.assertEqual(manifest['slug'], 'unit-test')
        self.assertEqual(manifest['replicates'], 4)
        self.assertEqual(len(manifest['inputs']), 4)
        self.assertEqual(len(manifest['expected_outputs']), 4)

    def test_per_task_seed_is_deterministic(self):
        """seed = seed_base XOR task_id; recover by reading the input."""
        out, p = self._make(replicates=8, seed_base=0xCAFEBABE)
        for i in range(8):
            task = json.loads((out / 'inputs' / f'{i:03d}.json').read_text())
            self.assertEqual(task['seed'], 0xCAFEBABE ^ i)

    def test_submit_sh_is_executable_and_has_safety_flags(self):
        out, p = self._make(replicates=4)
        st = (out / 'submit.sh').stat()
        self.assertTrue(st.st_mode & 0o111, 'submit.sh must be executable')
        submit = (out / 'submit.sh').read_text()
        # Hard-cap on the array size we expose to ALICE.
        self.assertIn(f'--array=0-{p.replicates - 1}', submit)
        self.assertIn(f'--time={p.time_limit}', submit)
        self.assertIn('set -euo pipefail', submit)

    def test_run_task_py_imports_from_repo_root(self):
        out, p = self._make(replicates=2)
        body = (out / 'run_task.py').read_text()
        # Worker must dispatch back to this module's run_task so the GA
        # code stays single-sourced.
        self.assertIn('from conduit.alice.metapact_ga import run_task',
                       body)

    def test_push_pull_scripts_target_configured_host(self):
        out, p = self._make(replicates=2,
            ssh_user='operator', ssh_host='alice.example')
        push = (out / 'push.sh').read_text()
        pull = (out / 'pull.sh').read_text()
        self.assertIn('operator@alice.example', push)
        self.assertIn('operator@alice.example', pull)
        # Pull rsync must point at the remote outputs/ subdir.
        self.assertIn(f'{p.remote_dir}/{p.slug}/outputs/', pull)

    def test_refuses_to_overwrite_existing_bundle(self):
        out, _ = self._make(replicates=2)
        with self.assertRaises(FileExistsError):
            mpga.generate_bundle(out, mpga.BundleParams(slug='unit-test'))

    def test_bundle_gitignore_excludes_outputs(self):
        out, _ = self._make(replicates=2)
        gi = (out / '.gitignore').read_text()
        self.assertIn('outputs/*.json', gi)


class RunTaskTest(unittest.TestCase):
    """Smoke test for the deterministic worker. Tiny GA so it runs in
    a couple of seconds; the point is to prove the JSON contract."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='alice-run-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_run_task_writes_expected_output_shape(self):
        task = {
            'task_id':     0,
            'seed':        12345,
            'generations': 2,
            'pop_size':    3,
            'depth':       3,
            'chain_ticks': 4,
            'mutation_rate': 0.01,
            'w_chain':     0.3,
            'w_leaf':      0.7,
            'corpus':      'hello world ' * 8,
        }
        ipath = self.tmp / 'in.json'
        opath = self.tmp / 'out.json'
        ipath.write_text(json.dumps(task))

        result = mpga.run_task(ipath, opath)

        # Output written + parseable
        on_disk = json.loads(opath.read_text())
        self.assertEqual(on_disk, result)
        # Required keys present
        for key in ('best_seed_hex', 'best_fitness', 'history',
                     'chain_classes', 'chain_scores', 'elapsed_seconds',
                     'evals'):
            self.assertIn(key, result)
        # best_seed_hex decodes to RULE_SIZE bytes
        from spoeqi.metachain import RULE_SIZE
        self.assertEqual(len(bytes.fromhex(result['best_seed_hex'])),
                          RULE_SIZE)
        # History length == generations
        self.assertEqual(len(result['history']), task['generations'])
        # Determinism: same seed → byte-identical best_seed_hex
        opath2 = self.tmp / 'out2.json'
        result2 = mpga.run_task(ipath, opath2)
        self.assertEqual(result['best_seed_hex'], result2['best_seed_hex'])


class AnalyseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='alice-analyse-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _make_bundle_with_outputs(self, n=3):
        params = mpga.BundleParams(slug='analyse-test', replicates=n)
        out = self.tmp / 'analyse-test'
        mpga.generate_bundle(out, params)
        for i in range(n):
            (out / 'outputs' / f'{i:03d}.json').write_text(json.dumps({
                'task_id': i, 'seed_in': 100 + i,
                'best_seed_hex': '00' * 16384,
                'best_fitness': 0.4 + 0.01 * i,
                'best_chain_quality': 0.6,
                'best_leaf_fitness': 0.3,
                'history': [[0.4, 0.35, 0.3]],
                'chain_classes': [3] * 10,
                'chain_scores': [0.06] * 10,
                'depth_class4': 0,
                'elapsed_seconds': 100 + i,
                'evals': 50 * 32,
            }))
        return out

    def test_complete_summary(self):
        out = self._make_bundle_with_outputs(n=3)
        s = mpga.analyse(out)
        self.assertEqual(s['status'], 'complete')
        self.assertEqual(s['n_tasks'], 3)
        self.assertEqual(s['n_expected'], 3)
        self.assertAlmostEqual(s['fitness']['max'], 0.42)
        self.assertEqual(s['best']['task_id'], 2)

    def test_partial_summary(self):
        out = self._make_bundle_with_outputs(n=3)
        (out / 'outputs' / '001.json').unlink()
        s = mpga.analyse(out)
        self.assertEqual(s['status'], 'partial')
        self.assertEqual(s['n_tasks'], 2)
        self.assertIn('001.json', ' '.join(s['missing']))

    def test_no_outputs(self):
        params = mpga.BundleParams(slug='empty-test', replicates=2)
        out = self.tmp / 'empty-test'
        mpga.generate_bundle(out, params)
        s = mpga.analyse(out)
        self.assertEqual(s['status'], 'no-outputs')


class ManagementCommandTest(TestCase):
    def test_alice_bundle_metapact_writes_bundle(self):
        from django.conf import settings
        from django.core.management import call_command
        slug = 'cli-test-mp'
        target_dir = Path(settings.BASE_DIR) / 'conduit' / 'alice' / 'bundles' / slug
        if target_dir.exists():
            shutil.rmtree(target_dir)
        try:
            buf = io.StringIO()
            call_command('alice_bundle_metapact',
                          '--slug', slug, '--replicates', '2',
                          stdout=buf)
            self.assertTrue((target_dir / 'submit.sh').exists())
            self.assertTrue((target_dir / 'manifest.json').exists())
        finally:
            if target_dir.exists():
                shutil.rmtree(target_dir)
