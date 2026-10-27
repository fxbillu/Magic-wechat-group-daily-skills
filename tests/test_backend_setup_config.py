"""T2 configuration safety through public CLI and HTTP."""
import json
import hashlib
import subprocess
import sys
import unittest

from test_readiness import reader, get


class ConfigurationTest(unittest.TestCase):
    def test_saved_setup_status_ignores_legacy_error_without_rewriting_user_files(self):
        with reader() as (root, package, cp, env, base):
            cp.parent.mkdir(exist_ok=True)
            cp.write_text('{}')
            original = cp.read_bytes()
            progress = cp.with_name(cp.name + '.onboarding.json')
            record = {'stage': 'configuration_saved', 'token': 'synthetic-resume',
                      'committed_hash': hashlib.sha256(original).hexdigest(),
                      'last_error': 'DECRYPTION_INCOMPLETE'}
            progress.write_text(json.dumps(record))
            before = progress.read_bytes()
            command = [sys.executable, '-B', str(package / 'scripts/tools/setup.py'), '--status']
            result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(json.loads(result.stdout)['code'])
            self.assertEqual(progress.read_bytes(), before)
            self.assertEqual(cp.read_bytes(), original)
            record['stage'] = 'decrypting'
            progress.write_text(json.dumps(record))
            failed = subprocess.run(command, env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(json.loads(failed.stdout)['code'], 'DECRYPTION_INCOMPLETE')

    def test_corrupt_configuration_is_an_explicit_error_and_remains_untouched(self):
        with reader('{broken-json') as (root, package, cp, env, base):
            before = cp.read_bytes()
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/fetch.py'), 'status'],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('CONFIG_INVALID', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(cp.read_bytes(), before)
            self.assertEqual(json.loads(get(base, '/api/status')[1])['configuration']['state'], 'needs_repair')
            self.assertFalse((package / 'scripts/decrypted').exists())


if __name__ == '__main__':
    unittest.main()
