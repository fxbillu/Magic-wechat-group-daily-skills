"""Onboarding CLI acceptance; replace only platform AES and Windows key extraction."""
from contextlib import closing
import hashlib
import hmac
import json
import os
import pty
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import unittest

from test_readiness import reader, get
from test_backend_collection import GROUPS, prepare, sql_file


def envelope(data, key):
    """Small fresh SQLite leaf pages, with 80 reserved bytes, for identity AES."""
    output = bytearray()
    for offset in range(0, len(data), 4096):
        page = bytearray(data[offset:offset + 4096])
        header = 100 if offset == 0 else 0
        if page[header] not in (10, 13):
            raise AssertionError('Fixture expects fresh small leaf pages')
        cells = int.from_bytes(page[header + 3:header + 5], 'big')
        start = int.from_bytes(page[header + 5:header + 7], 'big') or 4096
        if cells:
            page[start - 80:4016] = page[start:4096]
            page[header + 5:header + 7] = (start - 80).to_bytes(2, 'big')
            for i in range(cells):
                pointer = header + 8 + 2 * i
                old = int.from_bytes(page[pointer:pointer + 2], 'big')
                page[pointer:pointer + 2] = (old - 80).to_bytes(2, 'big')
        page[-80:] = bytes(80)
        if offset == 0:
            page[20] = 80
            page[:16] = bytes(range(16))
            salt = bytes(b ^ 0x3A for b in page[:16])
            mac_key = hashlib.pbkdf2_hmac('sha512', key, salt, 2, dklen=32)
            page[-64:] = hmac.new(mac_key, page[16:-64] + struct.pack('<I', 1), hashlib.sha512).digest()
        output.extend(page)
    return bytes(output)


def setup_fixture(root, env, *, broken=False, rich=False):
    seed = root / 'seed'
    snap, _ = prepare(seed, seed / 'config.json')
    if rich:
        table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
        sql_file(snap / 'message/message_0.db', [
            ('INSERT INTO Name2Id VALUES(?)', ('wxid_beta',)),
            (f'UPDATE {table} SET message_content=?', ('合成讨论甲的完整原始素材。' * 30,)),
            (f'INSERT INTO {table} SELECT 2,create_time+60,2,1,? FROM {table} LIMIT 1',
             ('合成讨论乙的完整原始素材。' * 30,))])
    source = root / 'accounts/fixture-account/db_storage'
    key = bytes(range(32))
    keys = {}
    for plain in snap.rglob('*.db'):
        rel = plain.relative_to(snap).as_posix()
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(envelope(plain.read_bytes(), key))
        keys[rel] = {'enc_key': key.hex()}
    if broken:
        (source / 'message/message_1.db').write_bytes(b'broken platform fixture')
    key_fixture = root / 'synthetic-keys.json'
    key_fixture.write_text(json.dumps(keys))
    adapter = root / 'platform-adapter'
    adapter.mkdir()
    (adapter / 'sitecustomize.py').write_text('''import json, os, pathlib, subprocess, sys, types
name='cryptography.hazmat.primitives.ciphers'
module=types.ModuleType(name)
class IdentityAES:
    def __init__(self,*args): pass
    def encryptor(self): return self
    def decryptor(self): return self
    def update(self,data):
        return bytes.fromhex('6bc1bee22e409f96e93d7e117393172a') if data==bytes.fromhex('f58c4c04d6e5f1ba779eabfb5f7bfbd6') else data
    def finalize(self): return b''
module.Cipher=IdentityAES
module.algorithms=types.SimpleNamespace(AES=IdentityAES)
module.modes=types.SimpleNamespace(CBC=IdentityAES)
for path in ('cryptography','cryptography.hazmat','cryptography.hazmat.primitives'):
    sys.modules[path]=types.ModuleType(path)
sys.modules[name]=module
original_expanduser=os.path.expanduser
os.path.expanduser=lambda path: os.environ['DAILY_SYNTHETIC_PROFILE'] if path=='~' else original_expanduser(path)
real_run=subprocess.run
def run(command,*args,**kwargs):
    if any(pathlib.Path(str(part)).name=='wcdb_key_tool_windows.py' for part in command) and 'extract' in command:
        target=pathlib.Path(command[command.index('--output')+1])
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(pathlib.Path(os.environ['DAILY_SYNTHETIC_KEY_FIXTURE']).read_bytes())
        return subprocess.CompletedProcess(command,0,'SYNTHETIC_PRIVATE_KEY_VALUE','SYNTHETIC_PRIVATE_KEY_VALUE')
    return real_run(command,*args,**kwargs)
subprocess.run=run
''')
    return source, dict(env, PYTHONPATH=str(adapter), DAILY_SYNTHETIC_KEY_FIXTURE=str(key_fixture),
                          DAILY_SYNTHETIC_PROFILE=str(root / "profile"))


def setup(package, env, *args, input_text=None):
    return subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/setup.py'), *args],
                          env=env, text=True, input=input_text, capture_output=True, timeout=25)


def payload(result):
    for line in reversed(result.stdout.splitlines()):
        if line.startswith('{'):
            return json.loads(line)
    raise AssertionError(result.stdout + result.stderr)


class SetupTest(unittest.TestCase):
    def test_different_drives_are_allowed_but_source_subdirectories_are_rejected(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            runtime = root / 'runtime'
            adapter = Path(adapted['PYTHONPATH']) / 'sitecustomize.py'
            with adapter.open('a') as stream:
                stream.write('''
# Simulate only Windows' cross-drive commonpath behavior at the OS boundary.
real_commonpath = os.path.commonpath
def commonpath(paths):
    if tuple(paths) == (os.environ['DAILY_SYNTHETIC_SOURCE'], os.environ['DAILY_SYNTHETIC_OUTPUT']):
        import ntpath
        return ntpath.commonpath(('F:\\\\wechat\\\\db_storage', 'C:\\\\daily'))
    return real_commonpath(paths)
os.path.commonpath = commonpath
''')
            adapted = dict(adapted, DAILY_SYNTHETIC_SOURCE=str(source.resolve()),
                           DAILY_SYNTHETIC_OUTPUT=str(runtime.resolve()))
            args = ['--auto', '--db-dir', str(source), '--account', 'fixture-account',
                    '--root', str(runtime), '--groups', GROUPS[0],
                    '--timezone', 'UTC', '--effective-from', '2026-10-25']
            configured = setup(package, adapted, *args)
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            previous = cp.read_bytes()
            args[args.index(str(runtime))] = str(source / 'daily')
            unsafe = setup(package, adapted, *args)
            self.assertNotEqual(unsafe.returncode, 0)
            self.assertEqual(payload(unsafe)['code'], 'UNSAFE_DATA_ROOT')
            self.assertEqual(cp.read_bytes(), previous)
            self.assertFalse((source / 'daily').exists())

    def test_unused_fts_failures_do_not_block_setup_or_create_fts_copies(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            key_file = Path(adapted['DAILY_SYNTHETIC_KEY_FIXTURE'])
            keys = json.loads(key_file.read_text())
            for rel in ('message/message_fts.db', 'message/message_fts_1.db', 'fts/search.db'):
                path = source / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'unreadable synthetic optional index')
                keys[rel] = {'enc_key': bytes(range(32)).hex()}
            key_file.write_text(json.dumps(keys))
            result = setup(package, adapted, '--auto', '--db-dir', str(source), '--account', 'fixture-account',
                           '--root', str(root / 'runtime'), '--groups', GROUPS[0],
                           '--timezone', 'UTC', '--effective-from', '2026-10-25')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            cfg = json.loads(cp.read_text())
            snapshot = Path(cfg['paths']['decrypted'])
            self.assertTrue((snapshot / 'message/message_0.db').is_file())
            self.assertFalse((snapshot / 'message/message_fts.db').exists())
            self.assertFalse((snapshot / 'fts').exists())

    def test_decryption_failure_never_commits_configuration_or_claims_completion(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env, broken=True)
            result = setup(package, adapted, '--auto', '--db-dir', str(source), '--account', 'fixture-account',
                           '--root', str(root / 'runtime'), '--groups', GROUPS[0],
                           '--timezone', 'UTC', '--effective-from', '2026-10-25')
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('DECRYPTION_INCOMPLETE', result.stdout + result.stderr)
            self.assertFalse(cp.exists(), result.stdout)
            self.assertNotIn('初始化完成', result.stdout)
            self.assertEqual(json.loads(get(base, '/api/status')[1])['configuration']['state'], 'unconfigured')

    def test_noninteractive_group_ambiguity_returns_candidates_and_preserves_config(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            result = setup(package, adapted, '--auto', '--db-dir', str(source), '--account', 'fixture-account',
                           '--root', str(root / 'runtime'), '--groups', '同名群',
                           '--timezone', 'UTC', '--effective-from', '2026-10-25')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('Traceback', result.stderr)
            report = payload(result)
            self.assertEqual(report['code'], 'AMBIGUOUS_GROUP')
            self.assertEqual({c['username'] for c in report['candidates']}, set(GROUPS))
            self.assertFalse(cp.exists())

    def test_interactive_empty_root_uses_the_same_external_default_as_auto(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            master, slave = pty.openpty()
            try:
                process = subprocess.Popen([sys.executable, '-B', str(package / 'scripts/tools/setup.py'),
                                            '--db-dir', str(source), '--account', 'fixture-account',
                                            '--groups', GROUPS[0], '--timezone', 'UTC', '--effective-from', '2026-10-25'],
                                           env=adapted, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True)
                os.close(slave)
                slave = None
                os.write(master, b'\n\n\n\n')
                stdout, stderr = process.communicate(timeout=25)
            finally:
                os.close(master)
                if slave is not None:
                    os.close(slave)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            config = json.loads(cp.read_text())
            self.assertEqual(config['paths']['root'], str(root / 'profile/wechat-daily'))
            self.assertFalse((package / 'scripts/secrets').exists())
            self.assertFalse((package / 'scripts/decrypted').exists())

    def test_ambiguous_selection_resumes_to_configuration_without_claiming_a_first_report(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            result = setup(package, adapted, '--auto', '--db-dir', str(source), '--account', 'fixture-account',
                           '--root', str(root / 'runtime'), '--groups', '同名群',
                           '--timezone', 'UTC', '--effective-from', '2026-10-25')
            report = payload(result)
            self.assertEqual(report['code'], 'AMBIGUOUS_GROUP')
            resumed = setup(package, adapted, '--auto', '--resume', report['resume_token'], '--groups', GROUPS[0])
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            self.assertEqual(payload(resumed)['stage'], 'configuration_saved')
            self.assertIn('desktop_shortcut', payload(resumed))
            config = json.loads(cp.read_text())
            self.assertEqual(config['chats'][0]['username'], GROUPS[0])
            self.assertEqual(config['chats'][0]['effective_from'], '2026-10-25')
            state = json.loads(get(base, '/api/status')[1])
            self.assertEqual(state['first_report']['state'], 'not_observed')
            self.assertIsNone(state['schedule']['registered'])
            before = cp.read_bytes()
            repeated = setup(package, adapted, '--auto', '--resume', report['resume_token'], '--groups', GROUPS[0])
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertEqual(cp.read_bytes(), before)

    def test_failed_retry_preserves_old_config_snapshot_and_never_forwards_key_output(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            args = ['--auto', '--db-dir', str(source), '--account', 'fixture-account',
                    '--root', str(root / 'runtime'), '--groups', GROUPS[0],
                    '--timezone', 'UTC', '--effective-from', '2026-10-25']
            first = setup(package, adapted, *args)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertNotIn('SYNTHETIC_PRIVATE_KEY_VALUE', first.stdout + first.stderr)
            original = cp.read_bytes()
            cfg = json.loads(original)
            db = Path(cfg['paths']['decrypted']) / 'message/message_0.db'
            snapshot = db.read_bytes()
            (source / 'message/message_1.db').write_bytes(b'failed retry fixture')
            failed = setup(package, adapted, *args)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('DECRYPTION_INCOMPLETE', failed.stdout)
            self.assertNotIn('SYNTHETIC_PRIVATE_KEY_VALUE', failed.stdout + failed.stderr)
            self.assertEqual(cp.read_bytes(), original)
            self.assertEqual(db.read_bytes(), snapshot)

    def test_explicit_legacy_migration_backs_up_source_and_preserves_data(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            legacy_data, legacy_reports = root / 'legacy-data', root / 'legacy-reports'
            legacy_data.mkdir(parents=True)
            legacy_reports.mkdir()
            (legacy_data / 'keep.txt').write_text('合成旧数据')
            legacy = package / 'scripts/config.json'
            legacy.write_text(json.dumps({'wechat': {'account': 'fixture-account'},
                                          'paths': {'data': str(legacy_data), 'reports': str(legacy_reports)}}))
            original = legacy.read_bytes()
            configured = setup(package, adapted, '--auto', '--db-dir', str(source), '--account', 'fixture-account',
                               '--root', str(root / 'runtime'), '--groups', GROUPS[0], '--timezone', 'UTC',
                               '--effective-from', '2026-10-25', '--migrate-from', str(legacy))
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            cfg = json.loads(cp.read_text())
            stage = Path(cfg['paths']['decrypted']).parent
            self.assertEqual((stage / 'legacy-config.backup.json').read_bytes(), original)
            self.assertEqual(legacy.read_bytes(), original)
            self.assertEqual((Path(cfg['paths']['data']) / 'keep.txt').read_text(), '合成旧数据')
            self.assertEqual(json.loads(get(base, '/api/status')[1])['first_report']['state'], 'not_observed')

    def test_account_discovery_requires_a_choice_and_successful_updates_keep_backup(self):
        with reader() as (root, package, cp, env, base):
            source, adapted = setup_fixture(root, env)
            home = root / 'wechat-home'
            for account in ('first-account', 'second-account'):
                (home / 'xwechat_files' / account / 'db_storage').mkdir(parents=True)
            appdata = root / 'appdata'
            config_dir = appdata / 'Tencent/xwechat/config'
            config_dir.mkdir(parents=True)
            (config_dir / 'synthetic.ini').write_text(str(home))
            choices = setup(package, dict(adapted, APPDATA=str(appdata)), '--auto', '--timezone', 'UTC')
            self.assertEqual(payload(choices)['code'], 'ACCOUNT_SELECTION_REQUIRED')
            self.assertEqual(len(payload(choices)['candidates']), 2)
            self.assertFalse(cp.exists())
            args = ['--auto', '--db-dir', str(source), '--account', 'fixture-account',
                    '--root', str(root / 'runtime'), '--groups', GROUPS[0],
                    '--timezone', 'UTC', '--effective-from', '2026-10-25']
            self.assertEqual(setup(package, adapted, *args).returncode, 0)
            old = cp.read_bytes()
            args[args.index(GROUPS[0])] = ','.join(GROUPS)
            updated = setup(package, adapted, *args)
            self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
            self.assertTrue(any(path.read_bytes() == old for path in cp.parent.glob('config.json.bak-*')))


if __name__ == '__main__':
    unittest.main()
