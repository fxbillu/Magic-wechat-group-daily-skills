"""CLI decryption coverage; only the platform AES provider is a test double."""
from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import time
import unittest

from test_readiness import reader
from test_backend_collection import DAY, GROUPS, cli, endpoint, prepare


def encrypted_fixture(path, key, valid=True):
    """Synthetic envelope for identity AES double; not real SQLCipher ciphertext."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as cn:
        cn.execute('VACUUM')
    page = bytearray(path.read_bytes())
    page[:16] = bytes(range(16))
    if not valid:
        page[100] = 255  # invalid SQLite btree page, but valid envelope HMAC
    page[-80:-64] = bytes(16)
    salt = bytes(b ^ 0x3A for b in page[:16])
    mac_key = hashlib.pbkdf2_hmac('sha512', key, salt, 2, dklen=32)
    page[-64:] = hmac.new(mac_key, page[16:-64] + struct.pack('<I', 1), hashlib.sha512).digest()
    path.write_bytes(page)


def platform_aes_double(root, env):
    adapter = root / 'platform-double'
    adapter.mkdir()
    (adapter / 'sitecustomize.py').write_text('''import sys, types
name = 'cryptography.hazmat.primitives.ciphers'
module = types.ModuleType(name)
class IdentityAES:
    def __init__(self, *args): pass
    def decryptor(self): return self
    def update(self, data): return data
    def finalize(self): return b''
module.Cipher = IdentityAES
module.algorithms = types.SimpleNamespace(AES=IdentityAES)
module.modes = types.SimpleNamespace(CBC=IdentityAES)
for path in ('cryptography', 'cryptography.hazmat', 'cryptography.hazmat.primitives'):
    sys.modules[path] = types.ModuleType(path)
sys.modules[name] = module
''')
    return dict(env, PYTHONPATH=str(adapter))


class DecryptionTest(unittest.TestCase):
    def test_partial_decrypt_failure_keeps_success_snapshot_and_blocks_collection(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertEqual(result.returncode, 0, result.stderr)
            previous = (snap / 'message/message_0.db').read_bytes()
            source = root / 'source'
            key = bytes(range(32))
            encrypted_fixture(source / 'other/ok.db', key)
            encrypted_fixture(source / 'message/message_0.db', key, valid=False)
            keys = root / 'keys.json'
            keys.write_text(json.dumps({rel: {'enc_key': key.hex()} for rel in
                                       ('other/ok.db', 'message/message_0.db')}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                     '--db-dir', str(source), '--keys', str(keys), '--output', str(snap)],
                                    env=platform_aes_double(root, env), text=True, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual((snap / 'message/message_0.db').read_bytes(), previous,
                             'A failed decryption must not replace the last readable snapshot')
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(entry['collection']['state'], 'failed')
            self.assertEqual(entry['collection']['coverage']['issues'][0]['code'], 'DECRYPTION_INCOMPLETE')
            self.assertEqual(endpoint(base, 'messages', date=DAY, username=GROUPS[0])['total'], 1)

    def test_nonempty_source_wal_is_reported_without_blocking_original_copy_path(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            source = root / 'source'
            key = bytes(range(32))
            encrypted_fixture(source / 'other/ok.db', key)
            (source / 'other/ok.db-wal').write_bytes(b'synthetic active WAL')
            keys = root / 'keys.json'
            encrypted_fixture(source / 'contact/contact.db', key)
            encrypted_fixture(source / 'message/message_0.db', key)
            keys.write_text(json.dumps({rel: {'enc_key': key.hex()} for rel in
                                       ('other/ok.db', 'contact/contact.db', 'message/message_0.db')}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                     '--db-dir', str(source), '--keys', str(keys), '--output', str(snap)],
                                    env=platform_aes_double(root, env), text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((snap / 'other/ok.db').exists(), result.stdout)
            self.assertIn('SOURCE_WAL_OBSERVED', result.stdout)

    def test_unkeyed_core_shard_and_rebuilt_stamp_cannot_claim_complete_history(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            source = root / 'source'
            (source / 'message').mkdir(parents=True)
            (source / 'message/message_9.db').write_bytes(b'synthetic missing-key source')
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                     '--db-dir', str(source), '--output', str(snap), '--rebuild-stamp'],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(entry['collection']['state'], 'failed')
            self.assertFalse(entry['collection']['coverage']['complete'])

    def test_zero_byte_wal_does_not_prevent_valid_candidate_publication(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            source = root / 'source'
            key = bytes(range(32))
            encrypted_fixture(source / 'other/ok.db', key)
            (source / 'other/ok.db-wal').touch()
            keys = root / 'keys.json'
            keys.write_text(json.dumps({'other/ok.db': {'enc_key': key.hex()}}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                     '--db-dir', str(source), '--keys', str(keys), '--output', str(snap)],
                                    env=platform_aes_double(root, env), text=True, capture_output=True, timeout=15)
            self.assertTrue((snap / 'other/ok.db').exists(), result.stdout + result.stderr)
            self.assertIn('成功 1', result.stdout)


if __name__ == '__main__':
    unittest.main()
