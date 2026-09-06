"""Exercise the publication gate against failed, stale and inconsistent sync results."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SyncPublicationGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = yaml.safe_load(
            (ROOT / '.github/workflows/update_cbmmg_normas.yml').read_text(encoding='utf-8')
        )
        cls.gate = next(
            step['run'] for step in workflow['jobs']['atualizar']['steps']
            if step.get('id') == 'sync_status'
        )
        cls.report = workflow['jobs']['resultado']['steps'][0]['run']

    def run_gate(self, status, process_outcome='success'):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'docs/data/sync_status.json'
            path.parent.mkdir(parents=True)
            if status is not None:
                path.write_text(json.dumps(status), encoding='utf-8')
            return subprocess.run(
                ['bash', '-e', '-c', self.gate],
                cwd=tmp,
                env={**os.environ, 'SYNC_STARTED_AT': '1788652800', 'SYNC_OUTCOME': process_outcome},
                capture_output=True,
                text=True,
                check=False,
            )

    def test_fresh_complete_collection_can_be_published(self):
        result = self.run_gate({'ok': True, 'status': 'ok', 'ultima_tentativa': '2026-09-06T00:00:01Z'})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_failure_diagnostic_can_publish_preserved_catalogue(self):
        result = self.run_gate(
            {'ok': False, 'status': 'falha', 'ultima_tentativa': '2026-09-06T00:00:01+00:00'},
            process_outcome='failure',
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_old_success_does_not_mask_an_interrupted_attempt(self):
        result = self.run_gate(
            {'ok': True, 'status': 'ok', 'ultima_tentativa': '2026-09-05T00:00:01Z'},
            process_outcome='failure',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Diagnóstico antigo', result.stderr)

    def test_diagnostic_must_agree_with_process_exit(self):
        for ok, status, outcome in [(True, 'ok', 'failure'), (False, 'falha', 'success')]:
            with self.subTest(ok=ok, outcome=outcome):
                result = self.run_gate(
                    {'ok': ok, 'status': status, 'ultima_tentativa': '2026-09-06T00:00:01Z'},
                    process_outcome=outcome,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('diverge', result.stderr)

    def test_missing_or_inconsistent_diagnostic_blocks_publication(self):
        cases = [None, {}, [], {'ok': 'false'},
                 {'ok': False, 'status': 'ok', 'ultima_tentativa': '2026-09-06T00:00:01Z'},
                 {'ok': True, 'status': 'ok', 'ultima_tentativa': '2026-09-06T00:00:01'}]
        for case in cases:
            with self.subTest(status=case):
                self.assertNotEqual(self.run_gate(case).returncode, 0)

    def test_published_failure_diagnostic_does_not_report_success(self):
        cases = [
            ('success', 'success', 'success', True),
            ('success', 'failure', 'success', False),
            ('failure', 'success', 'skipped', False),
            ('success', 'success', 'failure', False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for build, sync, deploy, expected_success in cases:
                with self.subTest(build=build, sync=sync, deploy=deploy):
                    result = subprocess.run(
                        ['bash', '-e', '-c', self.report],
                        env={**os.environ, 'BUILD_RESULT': build, 'SYNC_OUTCOME': sync,
                             'DEPLOY_RESULT': deploy, 'GITHUB_STEP_SUMMARY': str(Path(tmp) / 'summary')},
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, expected_success, result.stdout)


if __name__ == '__main__':
    unittest.main()
