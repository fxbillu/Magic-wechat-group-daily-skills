"""Voice behavior through installed CLI, real SQLite/HTTP and report files."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from test_readiness import reader
from test_backend_collection import cli, endpoint, GROUPS, sql_file
from test_backend_daily import fixture, daily, START, END

TEXT = '这是合成语音中的项目讨论，大家确认了今天的进度和明天需要跟进的问题。' * 30


def voice_fixture(root, cp, env, tokens=('one', 'two'), timeout=30):
    snap, cfg = fixture(root, cp)
    model = root / 'model-cache'
    model.mkdir()
    (model / 'model.bin').write_bytes(b'synthetic weights')
    (model / 'config.json').write_text('{}')
    (model / 'tokenizer.json').write_text('{}')
    cfg['voice'] = {'model_dir': str(model), 'timeout_seconds': timeout}
    cp.write_text(json.dumps(cfg))
    table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
    sql_file(snap / 'message/message_0.db', [
        (f'UPDATE {table} SET local_type=34, message_content=? WHERE local_id IN (2,3,4)',
         ('<voicemsg voicelength="12000" voiceformat="4" />',))])
    begin, end = (int(datetime.fromisoformat(x).timestamp()) for x in (START, END))
    sql_file(snap / 'message/media_0.db', [
        ('CREATE TABLE Name2Id(user_name TEXT)', ()),
        ('INSERT INTO Name2Id VALUES(?)', (GROUPS[0],)),
        ('INSERT INTO Name2Id VALUES(?)', (GROUPS[1],)),
        ('CREATE TABLE VoiceInfo(local_id INTEGER, chat_name_id INTEGER, create_time INTEGER, voice_data BLOB)', ()),
        *[('INSERT INTO VoiceInfo VALUES(?,?,?,?)', row) for row in (
            (2, 1, begin, tokens[0].encode()), (3, 1, end - 1, tokens[1].encode()),
            (4, 1, end, b'forbidden'), (2, 2, begin, b'forbidden'))]])
    boundary = root / 'external-boundary'
    boundary.mkdir()
    (boundary / 'ctranslate2.py').write_text('# Synthetic native runtime discovery only.\n')
    ledger = root / 'external-events.jsonl'
    common = '''import json, os\nfrom pathlib import Path\ndef event(kind, **values):\n    with open(os.environ['VOICE_FIXTURE_LEDGER'], 'a') as f:\n        f.write(json.dumps(dict(kind=kind, **values)) + '\\n')\n'''
    (boundary / 'pilk.py').write_text(common + '''
def decode(src, dst, **kwargs):
    token = Path(src).read_bytes().decode()
    event('decode', token=token)
    if token == 'bad':
        raise RuntimeError('synthetic decoder failure')
    if token == 'hang':
        import time
        time.sleep(60)
    Path(dst).write_bytes(token.encode().ljust(32, b'\\0'))
''')
    (boundary / 'faster_whisper.py').write_text(common + '''
import wave
from types import SimpleNamespace
class Native:
    def unload_model(self):
        event('unload')
class WhisperModel:
    def __init__(self, path, **kwargs):
        assert Path(path).is_dir(), 'network model loading forbidden'
        assert kwargs.get('local_files_only') is True, 'downloads must be disabled'
        self.model = Native()
        event('load', pid=os.getpid())
    def transcribe(self, path, **kwargs):
        with wave.open(path, 'rb') as wav:
            token = wav.readframes(wav.getnframes()).rstrip(b'\\0').decode()
        assert token != 'forbidden', 'wrong group or out-of-window audio'
        event('recognize', token=token)
        return iter([SimpleNamespace(text=os.environ['VOICE_FIXTURE_TEXT'] + token)]), None
''')
    env = dict(env, PYTHONPATH=str(boundary), VOICE_FIXTURE_LEDGER=str(ledger), VOICE_FIXTURE_TEXT=TEXT)
    return snap, cfg, env, ledger


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def render(package, env, root, item, opening=TEXT):
    draft = root / 'story.json'
    draft.write_text(json.dumps({'username': GROUPS[0], 'group_name': '合成群', 'date': item['date'],
        'source_revision': item['revision'], 'lead_title': '语音合成日报', 'opening': opening, 'timeline': []}))
    return subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/render_daily.py'),
        str(draft), '--no-png', '--no-avatar'], env=env, capture_output=True, text=True, timeout=10)


class VoiceTest(unittest.TestCase):
    def test_voice_only_edition_reaches_archive_http_and_report_without_repeat_asr(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env)
            before = (snap / 'message/media_0.db').read_bytes()
            result, prepared = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            item = prepared['groups'][0]
            self.assertEqual(item['state'], 'pending')
            payload = json.loads(Path(item['archive']).read_text())
            self.assertEqual(payload['range'], {'start': START, 'end': END})
            self.assertEqual([m['local_id'] for m in payload['messages']], [2, 3])
            self.assertEqual([m['text'] for m in payload['messages']], [TEXT + 'one', TEXT + 'two'])
            self.assertGreater(payload['stats']['chars'], 1000)
            analyzed = cli(package, env, 'analyze', '--chat', GROUPS[0], '--date', item['date'])
            self.assertEqual(analyzed.returncode, 0, analyzed.stdout + analyzed.stderr)
            self.assertEqual(json.loads(analyzed.stdout)['days'][0]['activity']['text_chars'], len(TEXT + 'one') + len(TEXT + 'two'))
            messages = endpoint(base, 'messages', date=item['date'], username=GROUPS[0])['messages']
            self.assertEqual(messages[0]['text'], TEXT + 'one')
            self.assertEqual(messages[0]['sender'], '成员甲')
            repeated, _ = daily(package, env)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            observed = events(ledger)
            self.assertEqual(sum(e['kind'] == 'load' for e in observed), 1)
            self.assertEqual(sum(e['kind'] == 'unload' for e in observed), 1)
            self.assertEqual([e['token'] for e in observed if e['kind'] == 'decode'], ['one', 'two'])
            output = render(package, env, root, item)
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr)
            html = next(Path(cfg['paths']['reports']).rglob('*.html')).read_text()
            self.assertIn(TEXT, html)
            self.assertIn('语音转写', html)
            self.assertIn('0 条未转写', html)
            self.assertEqual((snap / 'message/media_0.db').read_bytes(), before)
            self.assertTrue((root / 'model-cache/model.bin').is_file())
            self.assertFalse(list((Path(cfg['paths']['data']) / 'voice-work').glob('job-*')))
            self.assertFalse([p for p in Path(cfg['paths']['root']).rglob('*') if p.suffix in ('.silk', '.wav', '.pcm')])

    def test_partial_failure_is_disclosed_and_retry_updates_revision_preserving_old_report(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env, tokens=('one', 'bad'))
            result, prepared = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            item = prepared['groups'][0]
            self.assertEqual(item['state'], 'pending')
            original = json.loads(Path(item['archive']).read_text())
            self.assertEqual(original['messages'][1]['voice']['transcription']['state'], 'failed')
            rendered = render(package, env, root, item)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            report = next(Path(cfg['paths']['reports']).rglob('*.html'))
            old_html = report.read_bytes()
            self.assertIn('1 条未转写', old_html.decode())
            _, completed = daily(package, env, '--finish')
            self.assertEqual(completed['groups'][0]['state'], 'completed')
            sql_file(snap / 'message/media_0.db', [
                ('UPDATE VoiceInfo SET voice_data=? WHERE local_id=3 AND chat_name_id=1', (b'repaired',))])
            retried = cli(package, env, 'voice', 'retry', '--chat', GROUPS[0], '--date', item['date'])
            self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
            new_item = json.loads(retried.stdout)
            self.assertNotEqual(new_item['revision'], item['revision'])
            payload = json.loads(Path(item['archive']).read_text())
            self.assertEqual(payload['range'], original['range'])
            self.assertEqual(payload['messages'][0]['text'], original['messages'][0]['text'])
            self.assertEqual(payload['messages'][1]['text'], TEXT + 'repaired')
            self.assertEqual(report.read_bytes(), old_html)
            self.assertEqual(endpoint(base, 'entry', date=item['date'], username=GROUPS[0])['report']['state'], 'stale')
            rejected = render(package, env, root, item)
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertEqual(report.read_bytes(), old_html)
            _, pending = daily(package, env)
            self.assertEqual(pending['groups'][0]['revision'], new_item['revision'])
            refreshed = render(package, env, root, new_item)
            self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)
            _, finished = daily(package, env, '--finish')
            self.assertEqual(finished['groups'][0]['state'], 'completed')
            self.assertEqual(len(list(Path(cfg['paths']['reports']).rglob('*.html'))), 1)
            repeated = cli(package, env, 'voice', 'retry', '--chat', GROUPS[0], '--date', item['date'])
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertEqual([e['token'] for e in events(ledger) if e['kind'] == 'decode'], ['one', 'bad', 'repaired'])

    def test_media_is_decrypted_only_into_job_and_original_files_remain_unchanged(self):
        from test_backend_setup_flow import envelope
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env)
            media = snap / 'message/media_0.db'
            source = root / 'original-wechat/message/media_1.db'
            source.parent.mkdir(parents=True)
            key = bytes(range(32))
            original = envelope(media.read_bytes(), key)
            source.write_bytes(original)
            media.unlink()
            secrets = Path(cfg['paths']['secrets'])
            secrets.mkdir(parents=True)
            (secrets / 'all_keys.json').write_text(json.dumps({'message/media_1.db': {'enc_key': key.hex()}}))
            cfg['wechat'] = {'db_dir': str(source.parent.parent)}
            cp.write_text(json.dumps(cfg))
            (root / 'external-boundary/sitecustomize.py').write_text('''import sys, types
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
            config_before = cp.read_bytes()
            core_before = (snap / 'message/message_0.db').read_bytes()
            result, prepared = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(prepared['groups'][0]['state'], 'pending')
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(cp.read_bytes(), config_before)
            self.assertEqual((snap / 'message/message_0.db').read_bytes(), core_before)
            self.assertFalse(list(snap.glob('message/media_*.db')))
            self.assertFalse(list((Path(cfg['paths']['data']) / 'voice-work').glob('job-*')))
            payload = json.loads(Path(prepared['groups'][0]['archive']).read_text())
            self.assertEqual([m['text'] for m in payload['messages']], [TEXT + 'one', TEXT + 'two'])

    def test_timeout_exits_worker_and_restart_reclaims_only_own_finished_jobs(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env, tokens=('hang', 'two'), timeout=1)
            work = Path(cfg['paths']['data']) / 'voice-work'
            work.mkdir(parents=True)
            stale = work / 'job-interrupted'
            stale.mkdir()
            (stale / 'owner.json').write_text(json.dumps({'signature': 'wechat-voice-job-v1',
                'parent_pid': 0, 'worker_pid': 0, 'created_at': 0}))
            (stale / 'private.wav').write_bytes(b'synthetic abandoned audio')
            legacy = work / 'job-user-owned'
            legacy.mkdir()
            (legacy / 'keep.txt').write_text('not owned by the voice runner')
            active = work / 'job-active'
            active.mkdir()
            (active / 'owner.json').write_text(json.dumps({'signature': 'wechat-voice-job-v1',
                'parent_pid': os.getpid(), 'worker_pid': 0, 'created_at': 0}))
            result, prepared = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(prepared['groups'][0]['state'], 'insufficient')
            payload = json.loads(next((Path(cfg['paths']['data']) / '2026-10-25').glob('*.json')).read_text())
            self.assertTrue(all(m['voice']['transcription']['code'] == 'VOICE_TIMEOUT' for m in payload['messages']))
            self.assertFalse(stale.exists())
            self.assertTrue((legacy / 'keep.txt').exists())
            self.assertTrue(active.is_dir())
            self.assertEqual(sorted(p.name for p in work.glob('job-*')), ['job-active', 'job-user-owned'])
            if os.name != 'nt':
                for event in events(ledger):
                    if event['kind'] == 'load':
                        with self.assertRaises(ProcessLookupError):
                            os.kill(event['pid'], 0)
            self.assertTrue((root / 'model-cache/model.bin').is_file())

    def test_missing_model_is_actionable_and_configure_never_downloads_or_loads_it(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env)
            cfg.pop('voice')
            cp.write_text(json.dumps(cfg))
            before = cp.read_bytes()
            status = cli(package, env, 'voice', 'status')
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            self.assertIn('VOICE_MODEL_NOT_CONFIGURED', json.loads(status.stdout)['codes'])
            rejected = cli(package, env, 'voice', 'configure', '--model-dir', str(root / 'missing'))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(cp.read_bytes(), before)
            self.assertFalse(ledger.exists())
            result, prepared = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(next((Path(cfg['paths']['data']) / '2026-10-25').glob('*.json')).read_text())
            self.assertTrue(all(m['voice']['transcription']['code'] == 'VOICE_MODEL_NOT_CONFIGURED' for m in payload['messages']))
            configured = cli(package, env, 'voice', 'configure', '--model-dir', str(root / 'model-cache'))
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            self.assertFalse(ledger.exists(), 'Configuration must not load a model')
            ready = cli(package, env, 'voice', 'status')
            self.assertTrue(json.loads(ready.stdout)['ready'])
            retried = cli(package, env, 'voice', 'retry', '--chat', GROUPS[0], '--date', '2026-10-25')
            self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
            self.assertEqual(json.loads(retried.stdout)['voice']['transcribed'], 2)

    def test_natural_day_archive_uses_transcripts_and_recollection_reuses_successful_text(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env)
            sql_file(snap / 'message/media_0.db', [('UPDATE VoiceInfo SET voice_data=? WHERE local_id=4', (b'cutoff',))])
            for _ in range(2):
                result = cli(package, env, 'archive', '--config', '--date', '2026-10-25')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            messages = endpoint(base, 'messages', date='2026-10-25', username=GROUPS[0])['messages']
            # Natural-day scope includes the planned cutoff message, unlike daily's half-open window.
            self.assertEqual(messages[0]['text'], TEXT + 'two')
            self.assertEqual(sum(e['kind'] == 'load' for e in events(ledger)), 1)

    def test_completed_transcript_survives_later_recording_timeout(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env, tokens=('one', 'hang'), timeout=1)
            result, prepared = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(prepared['groups'][0]['state'], 'pending')
            payload = json.loads(Path(prepared['groups'][0]['archive']).read_text())
            self.assertEqual(payload['messages'][0]['text'], TEXT + 'one')
            self.assertEqual(payload['messages'][1]['voice']['transcription']['code'], 'VOICE_TIMEOUT')
            entry = endpoint(base, 'entry', date='2026-10-25', username=GROUPS[0])
            self.assertEqual(entry['voice_transcription'], {'total': 2, 'transcribed': 1, 'failed': 1})

    @unittest.skipIf(os.name == 'nt', 'Native Windows parent-exit validation remains on device')
    def test_worker_exits_when_parent_is_forcibly_stopped(self):
        import time
        import signal
        with reader() as (root, package, cp, env, base):
            snap, cfg, env, ledger = voice_fixture(root, cp, env, tokens=('hang', 'two'))
            parent = subprocess.Popen([sys.executable, '-B', str(package / 'scripts/fetch.py'),
                'daily', '--until', END], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            worker_pid = None
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    loads = [e for e in events(ledger) if e['kind'] == 'load']
                    if loads:
                        worker_pid = loads[0]['pid']
                        break
                    time.sleep(.03)
                self.assertIsNotNone(worker_pid)
                parent.kill()
                parent.wait(timeout=3)
                exited = False
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        os.kill(worker_pid, 0)
                    except ProcessLookupError:
                        exited = True
                        break
                    time.sleep(.05)
                self.assertTrue(exited, 'Whisper worker outlived its stopped parent')
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=3)
                if worker_pid:
                    try:
                        os.kill(worker_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
