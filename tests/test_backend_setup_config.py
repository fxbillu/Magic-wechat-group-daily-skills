"""T2 configuration safety through public CLI and HTTP."""
import json
import subprocess
import sys
import unittest

from test_readiness import reader, get


class ConfigurationTest(unittest.TestCase):
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
