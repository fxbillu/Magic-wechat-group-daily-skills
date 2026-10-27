"""CLI decryption coverage; only the platform AES provider is a test double."""
from contextlib import closing
import hashlib
import hmac
import json
import os
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
    def test_legacy_fts_updates_do_not_invalidate_core_freshness(self):
        from datetime import date
        with reader() as (root, package, cp, env, base):
            snap, _ = prepare(root, cp)
            table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
            from datetime import datetime
            with closing(sqlite3.connect(snap / 'message/message_0.db')) as connection:
                connection.execute(f'UPDATE "{table}" SET create_time=?',
                                   (int(datetime.combine(date.today(), datetime.min.time()).timestamp()) + 3600,))
                connection.commit()
            source = root / 'source'
            fts = source / 'message/message_fts.db'
            fts.parent.mkdir(parents=True)
            fts.write_bytes(b'old optional index')
            future = time.time() + 600
            os.utime(fts, (future, future))
            stamp_path = snap / '.stamp.json'
            stamp = json.loads(stamp_path.read_text())
            stamp['source_dir'] = str(source)
            stamp['files']['message/message_fts.db'] = {'verified_at': stamp['decrypted_at']}
            stamp_path.write_text(json.dumps(stamp))
            result = cli(package, env, 'stat', '--chat', GROUPS[0], '--date', date.today().isoformat())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            core = source / 'message/message_0.db'
            core.write_bytes(b'core source changed')
            os.utime(core, (future, future))
            blocked = cli(package, env, 'stat', '--chat', GROUPS[0], '--date', date.today().isoformat())
            self.assertEqual(blocked.returncode, 5, blocked.stdout + blocked.stderr)

    def test_empty_or_partly_marked_interrupted_workspace_recovers(self):
        for signature in (None, 'wechat-group-daily-decrypt-'):
            with self.subTest(signature=signature), reader() as (root, package, cp, env, base):
                snap, _ = prepare(root, cp)
                work = snap / '.decrypt-work'
                work.mkdir()
                if signature is not None:
                    (work / '.format').write_text(signature)
                result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                         '--db-dir', str(root / 'source'), '--output', str(snap), '--rebuild-stamp'],
                                        env=env, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_restart_reclaims_interrupted_work_without_touching_legacy_files_or_history(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            history = {path: path.read_bytes() for path in Path(cfg['paths']['data']).rglob('*')
                       if path.is_file() and path.suffix == '.json'}
            report = Path(cfg['paths']['reports']) / 'historical.html'
            report.parent.mkdir(parents=True)
            report.write_text('合成历史日报')
            original_config = cp.read_bytes()
            previous = (snap / 'message/message_0.db').read_bytes()
            legacy = snap / 'message/tmp-legacy.candidate'
            legacy.write_bytes(b'unknown legacy ownership; preserve')
            source = root / 'source'
            key = bytes(range(32))
            targets = ('contact/contact.db', 'message/message_0.db', 'message/message_1.db')
            for rel in targets:
                encrypted_fixture(source / rel, key)
            keys = root / 'keys.json'
            keys.write_text(json.dumps({rel: {'enc_key': key.hex()} for rel in targets}))
            adapted = platform_aes_double(root, env)
            adapter = Path(adapted['PYTHONPATH']) / 'sitecustomize.py'
            with adapter.open('a') as stream:
                stream.write('''
import os, time
real_sleep = time.sleep
def sleep(seconds):
    real_sleep(30 if seconds == .4 and os.environ.get('DAILY_SYNTHETIC_PAUSE') else seconds)
time.sleep = sleep
''')
            command = [sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                       '--db-dir', str(source), '--keys', str(keys), '--output', str(snap)]
            active = subprocess.Popen(command, env=dict(adapted, DAILY_SYNTHETIC_PAUSE='1'),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not list(snap.rglob('*.snap')) and active.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(list(snap.rglob('*.snap')), 'Did not reach the real snapshot step')
                live_files = {p: p.read_bytes() for p in snap.rglob('*') if p.suffix in ('.snap', '.candidate')}
                contender = subprocess.run(command, env=adapted, text=True, capture_output=True, timeout=5)
                self.assertEqual(contender.returncode, 10, contender.stdout + contender.stderr)
                self.assertIn('DECRYPTION_BUSY', contender.stderr)
                self.assertTrue(all(path.read_bytes() == data for path, data in live_files.items()))
                active.kill()
                active.wait(timeout=5)
            finally:
                if active.poll() is None:
                    active.kill()
                    active.wait(timeout=5)
            abandoned = [p for p in snap.rglob('*') if p.suffix in ('.snap', '.candidate') and p != legacy]
            self.assertTrue(abandoned)
            self.assertEqual((snap / 'message/message_0.db').read_bytes(), previous)
            restarted = subprocess.run(command, env=adapted, text=True, capture_output=True, timeout=15)
            self.assertEqual(restarted.returncode, 0, restarted.stdout + restarted.stderr)
            self.assertTrue(all(not path.exists() for path in abandoned), 'Interrupted temporary files were not reclaimed')
            self.assertEqual(legacy.read_bytes(), b'unknown legacy ownership; preserve')
            self.assertEqual(cp.read_bytes(), original_config)
            self.assertEqual(report.read_text(), '合成历史日报')
            self.assertTrue(all(path.read_bytes() == data for path, data in history.items()))

    def test_cleanup_refuses_unmarked_or_linked_workspace(self):
        for linked in (False, True):
            with self.subTest(linked=linked), reader() as (root, package, cp, env, base):
                snap, _ = prepare(root, cp)
                outside = root / 'unrelated'
                outside.mkdir()
                protected = outside / 'tmp-protected.candidate'
                protected.write_bytes(b'not owned by the decryptor')
                work = snap / '.decrypt-work'
                if linked:
                    work.symlink_to(outside, target_is_directory=True)
                else:
                    work.mkdir()
                    (work / 'tmp-unknown.snap').write_bytes(b'unknown owner')
                result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                         '--db-dir', str(root / 'source'), '--output', str(snap), '--rebuild-stamp'],
                                        env=env, text=True, capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('DECRYPTION_IO_ERROR', result.stderr)
                self.assertEqual(protected.read_bytes(), b'not owned by the decryptor')
                if not linked:
                    self.assertEqual((work / 'tmp-unknown.snap').read_bytes(), b'unknown owner')

    def test_optional_failure_does_not_negate_verified_core_success(self):
        with reader() as (root, package, cp, env, base):
            snap, _ = prepare(root, cp)
            source, key = root / 'source', bytes(range(32))
            targets = ('contact/contact.db', 'message/message_0.db', 'message/message_fts.db')
            for rel in targets:
                encrypted_fixture(source / rel, key, valid=not rel.endswith('_fts.db'))
            keys = root / 'keys.json'
            keys.write_text(json.dumps({rel: {'enc_key': key.hex()} for rel in targets}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                     '--db-dir', str(source), '--keys', str(keys), '--output', str(snap),
                                     '--include-optional'], env=platform_aes_double(root, env),
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('OPTIONAL_DECRYPTION_FAILED', result.stdout)
            self.assertTrue((snap / 'message/message_0.db').is_file())

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
            keys = root / 'keys.json'
            encrypted_fixture(source / 'contact/contact.db', key)
            (source / 'contact/contact.db-wal').write_bytes(b'synthetic active WAL')
            encrypted_fixture(source / 'message/message_0.db', key)
            keys.write_text(json.dumps({rel: {'enc_key': key.hex()} for rel in
                                       ('other/ok.db', 'contact/contact.db', 'message/message_0.db')}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                                     '--db-dir', str(source), '--keys', str(keys), '--output', str(snap)],
                                    env=platform_aes_double(root, env), text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((snap / 'other/ok.db').exists(), result.stdout)
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
                                     '--db-dir', str(source), '--keys', str(keys), '--output', str(snap),
                                     '--only', 'other/ok.db'],
                                    env=platform_aes_double(root, env), text=True, capture_output=True, timeout=15)
            self.assertTrue((snap / 'other/ok.db').exists(), result.stdout + result.stderr)
            self.assertIn('成功 1', result.stdout)


if __name__ == '__main__':
    unittest.main()
