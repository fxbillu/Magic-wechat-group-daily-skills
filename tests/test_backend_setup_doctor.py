"""Capabilities are observed through doctor's public JSON command."""
import json
import subprocess
import sys
import unittest

from test_readiness import reader


def doctor(package, env, *args):
    return subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/doctor.py'),
                           '--json', *args], env=env, text=True, capture_output=True, timeout=15)


class DoctorTest(unittest.TestCase):
    def test_unconfigured_probe_reports_actual_capabilities_without_writing_data(self):
        with reader() as (root, package, cp, env, base):
            result = doctor(package, env, '--timezone', 'UTC')
            self.assertEqual(result.returncode, 11, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload['configuration']['state'], 'unconfigured')
            self.assertTrue(payload['capabilities']['python_core']['available'])
            self.assertTrue(payload['capabilities']['timezone']['available'])
            self.assertIsInstance(payload['capabilities']['node_zstd']['available'], bool)
            self.assertFalse(cp.exists())
            self.assertFalse((package / 'scripts/data').exists())

    def test_working_windows_cng_does_not_require_the_optional_python_crypto_package(self):
        with reader() as (root, package, cp, env, base):
            adapter = root / 'cng-adapter'
            adapter.mkdir()
            (adapter / 'sitecustomize.py').write_text("""import ctypes, sys, types
sys.modules['cryptography']=None
def decrypt(key,data,length,padding,iv,iv_length,out,capacity,got,flags):
    out.raw=bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
    got._obj.value=16
    return 0
api=types.SimpleNamespace(BCryptOpenAlgorithmProvider=lambda *a:0, BCryptSetProperty=lambda *a:0,
    BCryptGenerateSymmetricKey=lambda *a:0, BCryptDecrypt=decrypt,
    BCryptDestroyKey=lambda *a:0, BCryptCloseAlgorithmProvider=lambda *a:0)
ctypes.WinDLL=lambda *a:api
""")
            result = doctor(package, dict(env, PYTHONPATH=str(adapter)), '--capabilities-only', '--timezone', 'UTC')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            caps = json.loads(result.stdout)['capabilities']
            self.assertTrue(caps['aes_decrypt']['available'])
            self.assertFalse(caps['cryptography']['required'])
            self.assertFalse(caps['cryptography']['available'])

    def test_node_version_only_and_missing_iana_data_do_not_claim_capability(self):
        with reader() as (root, package, cp, env, base):
            fake_node = root / 'version-only-node'
            fake_node.write_text('#!' + sys.executable + '\nimport sys\n'
                                 "print('v99.0.0') if '--version' in sys.argv else sys.exit(3)\n")
            fake_node.chmod(0o755)
            result = doctor(package, dict(env, WECHAT_NODE=str(fake_node), PYTHONTZPATH=str(root / 'no-zones')),
                            '--timezone', 'Asia/Shanghai', '--fix')
            report = json.loads(result.stdout)
            self.assertFalse(report['capabilities']['node_zstd']['available'])
            self.assertEqual(report['capabilities']['timezone']['code'], 'TIMEZONE_UNAVAILABLE')
            self.assertEqual(report['repair']['state'], 'not_started')
            self.assertFalse(cp.exists())


if __name__ == '__main__':
    unittest.main()
