"""Selected-message speech recognition in an isolated, offline worker.

Only text and source metadata survive a job. Model files and original WeChat
files are never removed; temporary audio and decrypted media belong to the job.
"""
from contextlib import closing
from datetime import datetime
import hashlib
import importlib.util
import re
import json
import math
import os
from pathlib import Path
import sqlite3
import shutil
import time
import subprocess
import sys
import tempfile
import threading

from . import archive, settings


def summary(payload):
    messages = [m for m in payload.get('messages', []) if m.get('type') == 'voice']
    if not messages:
        return None
    done = sum((m.get('voice') or {}).get('transcription', {}).get('state') == 'transcribed'
               for m in messages)
    return {'total': len(messages), 'transcribed': done, 'failed': len(messages) - done}


def _cache_path(cfg, chat, message):
    identity = [cfg.get('wechat', {}).get('account', ''), chat, message.source_shard,
                message.local_id, int(message.ts.timestamp()),
                {key: value for key, value in (message.voice or {}).items() if key != 'transcription'}]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return Path(settings.data_dir(cfg)) / 'voice-text' / (digest + '.json')



def _options(cfg):
    value = cfg.get('voice', {})
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('VOICE_CONFIG_INVALID')
    if 'enabled' in value and not isinstance(value['enabled'], bool):
        raise ValueError('VOICE_CONFIG_INVALID')
    timeout = value.get('timeout_seconds', 300)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise ValueError('VOICE_CONFIG_INVALID')
    if value.get('device', 'cpu') not in ('cpu', 'cuda', 'auto') or not isinstance(value.get('compute_type', 'int8'), str):
        raise ValueError('VOICE_CONFIG_INVALID')
    return value


def status(cfg):
    from . import voice
    try:
        options = _options(cfg)
    except ValueError:
        return {'ready': False, 'codes': ['VOICE_CONFIG_INVALID']}
    codes = []
    if options.get('enabled') is False:
        codes.append('VOICE_DISABLED')
    if not options.get('model_dir'):
        codes.append('VOICE_MODEL_NOT_CONFIGURED')
    else:
        try:
            voice.model_path(options['model_dir'])
        except (OSError, ValueError):
            codes.append('VOICE_MODEL_UNAVAILABLE')
    for module, code in (('pilk', 'VOICE_DECODER_MISSING'), ('faster_whisper', 'VOICE_ASR_MISSING'),
                         ('ctranslate2', 'VOICE_ASR_MISSING')):
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            if code not in codes:
                codes.append(code)
    return {'ready': not codes, 'codes': codes, 'runtime_verified': False}


def configure(cfg, directory, timeout=300):
    from . import voice
    if not Path(directory).expanduser().is_absolute():
        raise ValueError('VOICE_MODEL_UNAVAILABLE')
    source = voice.model_path(directory)
    settings.external_path(source)
    options = dict(cfg.get('voice') or {}, model_dir=source, enabled=True, timeout_seconds=timeout)
    _options(dict(cfg, voice=options))
    cfg['voice'] = options
    settings.save(cfg)
    return {'state': 'configured', **status(cfg)}

def enrich(cfg, chat, messages):
    """Recognize only selected messages; per-message failures preserve placeholders."""
    todo = []
    cache_paths = {}
    for message in messages:
        if message.base != 34 or (message.voice or {}).get('transcription', {}).get('state') == 'transcribed':
            continue
        path = _cache_path(cfg, chat, message)
        try:
            cached = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached = {}
        message.voice = dict(message.voice or {})
        if cached.get('state') == 'transcribed' and isinstance(cached.get('text'), str) and cached['text'].strip():
            message.text = cached['text']
            message.voice['transcription'] = {'state': 'transcribed', 'engine': 'whisper'}
        else:
            ident = f'{message.source_shard}:{message.local_id}'
            todo.append({'id': ident, 'local_id': message.local_id, 'time': int(message.ts.timestamp())})
            cache_paths[ident] = path
    if not todo:
        return
    try:
        options = _options(cfg)
    except ValueError:
        options = {'enabled': True}
        code = 'VOICE_CONFIG_INVALID'
    else:
        code = None
    if not code and options.get('enabled') is False:
        code = 'VOICE_DISABLED'
    model = options.get('model_dir')
    if not code and not model:
        code = 'VOICE_MODEL_NOT_CONFIGURED'
    if code:
        results = {item['id']: {'state': 'failed', 'code': code} for item in todo}
    else:
        results = _run(cfg, chat, todo, options)
    for message in messages:
        ident = f'{message.source_shard}:{message.local_id}'
        if message.base != 34 or ident not in cache_paths:
            continue
        value = results.get(ident) or {'state': 'failed', 'code': 'VOICE_WORKER_FAILED'}
        if value.get('state') == 'transcribed' and isinstance(value.get('text'), str) and value['text'].strip():
            message.text = value['text'].strip()
            message.voice['transcription'] = {'state': 'transcribed', 'engine': 'whisper'}
            archive._atomic_write(str(cache_paths[ident]), {'state': 'transcribed', 'text': message.text})
        else:
            message.voice['transcription'] = {'state': 'failed', 'code': value.get('code', 'VOICE_WORKER_FAILED')}



def _alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is not proof of exit.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _reclaim(root):
    for folder in root.glob('job-*'):
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            owner = json.loads((folder / 'owner.json').read_text(encoding='utf-8'))
            if (owner.get('signature') != 'wechat-voice-job-v1'
                    or time.time() - owner['created_at'] < 30
                    or _alive(owner.get('parent_pid')) or _alive(owner.get('worker_pid'))):
                continue
            shutil.rmtree(folder)
        except (OSError, ValueError, KeyError, TypeError):
            continue

def _run(cfg, chat, tasks, options):
    root = Path(settings.data_dir(cfg)) / 'voice-work'
    if root.is_symlink():
        return {item['id']: {'state': 'failed', 'code': 'VOICE_WORKSPACE_UNSAFE'} for item in tasks}
    root.mkdir(parents=True, exist_ok=True)
    _reclaim(root)
    try:
        timeout = max(1, min(3600, float(options.get('timeout_seconds', 300))))
    except (ValueError, TypeError):
        return {item['id']: {'state': 'failed', 'code': 'VOICE_CONFIG_INVALID'} for item in tasks}
    with tempfile.TemporaryDirectory(prefix='job-', dir=root) as temp:
        folder = Path(temp)
        (folder / 'owner.json').write_text(json.dumps({'signature': 'wechat-voice-job-v1',
            'parent_pid': os.getpid(), 'worker_pid': 0, 'created_at': time.time()}), encoding='utf-8')
        request = {'chat': chat, 'tasks': tasks, 'snapshot': settings.decrypted_dir(cfg),
                   'source': cfg.get('wechat', {}).get('db_dir'), 'keys': settings.keys_file(cfg),
                   'model_dir': options['model_dir'], 'timeout_seconds': timeout, 'device': options.get('device', 'cpu'),
                   'compute_type': options.get('compute_type', 'int8')}
        (folder / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        env = dict(os.environ, TMP=str(folder), TEMP=str(folder), TMPDIR=str(folder))
        lib = str(Path(__file__).resolve().parents[1])
        env['PYTHONPATH'] = lib + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        try:
            process = subprocess.run([sys.executable, '-B', '-c',
                'from wechat_data.voice_jobs import worker_main; worker_main()', str(folder)],
                env=env, cwd=folder, capture_output=True, timeout=timeout)
            if process.returncode == 124:
                raise subprocess.TimeoutExpired('voice worker', timeout)
            if process.returncode:
                raise ValueError()
            result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except subprocess.TimeoutExpired:
            code = 'VOICE_TIMEOUT'
        except (OSError, ValueError):
            code = 'VOICE_WORKER_FAILED'
        try:
            partial = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
            if not isinstance(partial, dict):
                partial = {}
        except (OSError, ValueError):
            partial = {}
        return {item['id']: partial.get(item['id'], {'state': 'failed', 'code': code}) for item in tasks}



def _prepare_media(request, folder):
    """Decrypt media into the job, without changing the core snapshot stamp."""
    source = request.get('source')
    if not source:
        return sorted(path for path in Path(request['snapshot']).glob('message/media_*.db')
                      if re.fullmatch(r'media_\d+\.db', path.name) and not path.is_symlink())
    files = sorted(path for path in Path(source).glob('message/media_*.db')
                   if re.fullmatch(r'media_\d+\.db', path.name) and not path.is_symlink())
    if not files:
        return []
    keys = json.loads(Path(request['keys']).read_text(encoding='utf-8'))
    keys = {key.replace('\\', '/'): value for key, value in keys.items()}
    module_path = Path(__file__).resolve().parents[2] / 'tools/safe_decrypt.py'
    spec = importlib.util.spec_from_file_location('voice_media_decrypt', module_path)
    decryptor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decryptor)
    media = folder / 'media'
    media.mkdir()
    ready = []
    for path in files:
        key = keys.get('message/' + path.name, {}).get('enc_key')
        if not key:
            continue
        destination = media / path.name
        try:
            info = decryptor.decrypt_one(str(path), str(destination), bytes.fromhex(key), quiet=True,
                                         workspace=str(media))
        except (OSError, ValueError):
            continue
        if info['ok']:
            ready.append(destination)
    return ready


def _audio(files, chat, task):
    matches = []
    for path in files:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
            cid = connection.execute('SELECT rowid FROM Name2Id WHERE user_name=?', (chat,)).fetchone()
            if cid is None:
                continue
            columns = {row[1] for row in connection.execute('PRAGMA table_info(VoiceInfo)')}
            sql = 'SELECT voice_data FROM VoiceInfo WHERE chat_name_id=? AND local_id=?'
            values = [cid[0], task['local_id']]
            if 'create_time' in columns:
                sql += ' AND create_time=?'
                values.append(task['time'])
            matches.extend(bytes(row[0]) for row in connection.execute(sql, values) if row[0])
    # Multiple source rows must agree; never silently choose another recording.
    unique = set(matches)
    if len(unique) > 1:
        raise ValueError('VOICE_AUDIO_AMBIGUOUS')
    return next(iter(unique)) if unique else None


def _watch_worker(parent_pid, timeout, stopped):
    deadline = time.monotonic() + timeout
    while not stopped.wait(.2):
        if time.monotonic() >= deadline or not _alive(parent_pid):
            # The process boundary is the final native-memory cleanup fallback.
            os._exit(124)

def worker_main():
    """Serialize ASR workers and expose ownership for safe crash recovery."""
    folder = Path(sys.argv[1])
    tempfile.tempdir = str(folder)
    request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
    owner = json.loads((folder / 'owner.json').read_text(encoding='utf-8'))
    owner['worker_pid'] = os.getpid()
    archive._atomic_write(str(folder / 'owner.json'), owner)
    stopped = threading.Event()
    watchdog = threading.Thread(target=_watch_worker, args=(owner['parent_pid'], request['timeout_seconds'], stopped), daemon=True)
    watchdog.start()
    lease = sqlite3.connect(folder.parent / 'worker.lock.db', timeout=0)
    try:
        try:
            lease.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError:
            results = {task['id']: {'state': 'failed', 'code': 'VOICE_BUSY'} for task in request['tasks']}
        else:
            results = _transcribe_request(request, folder)
    finally:
        lease.rollback()
        lease.close()
        stopped.set()
        watchdog.join(timeout=1)
    (folder / 'result.json').write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')


def _transcribe_request(request, folder):
    from . import voice
    results = {}
    transcriber = voice.WhisperTranscriber(model_dir=request['model_dir'],
        device=request['device'], compute_type=request['compute_type'])
    try:
        try:
            media = _prepare_media(request, folder)
            if not media:
                raise ValueError('VOICE_MEDIA_UNAVAILABLE')
        except (OSError, ValueError, sqlite3.Error):
            media = []
            results = {task['id']: {'state': 'failed', 'code': 'VOICE_MEDIA_UNAVAILABLE'} for task in request['tasks']}
        try:
            if not results:
                transcriber._ensure()
        except (ImportError, NotImplementedError):
            results = {task['id']: {'state': 'failed', 'code': 'VOICE_DEPENDENCY_MISSING'} for task in request['tasks']}
        except Exception:
            results = {task['id']: {'state': 'failed', 'code': 'VOICE_MODEL_UNAVAILABLE'} for task in request['tasks']}
        if not results:
            for task in request['tasks']:
                try:
                    audio = _audio(media, request['chat'], task)
                    if not audio:
                        results[task['id']] = {'state': 'failed', 'code': 'VOICE_AUDIO_MISSING'}
                        continue
                    text = transcriber.transcribe(audio)
                    results[task['id']] = ({'state': 'transcribed', 'text': text} if text else
                        {'state': 'failed', 'code': 'VOICE_NO_SPEECH'})
                except (ImportError, NotImplementedError):
                    results[task['id']] = {'state': 'failed', 'code': 'VOICE_DEPENDENCY_MISSING'}
                except Exception:
                    results[task['id']] = {'state': 'failed', 'code': 'VOICE_TRANSCRIPTION_FAILED'}
                finally:
                    archive._atomic_write(str(folder / 'result.json'), results)
    finally:
        transcriber.close()
    return results


def retry_archive(cfg, chat, date):
    """Revise only failed voice dictionaries, preserving all other source fields."""
    from . import daily
    from .messages import Message
    try:
        if datetime.strptime(date, '%Y-%m-%d').date().isoformat() != date:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('VOICE_DATE_INVALID') from None
    if chat not in {item['username'] for item in settings.active_chats(cfg)}:
        raise ValueError('VOICE_GROUP_NOT_FOLLOWED')
    with daily.run_lock(Path(settings.data_dir(cfg)) / 'daily-state'):
        payload = archive.load(cfg, date, chat)
        if not payload:
            raise ValueError('VOICE_ARCHIVE_NOT_FOUND')
        selected = [(index, item) for index, item in enumerate(payload['messages'])
                    if item.get('type') == 'voice' and
                    (item.get('voice') or {}).get('transcription', {}).get('state') != 'transcribed']
        changed = False
        if selected:
            if not isinstance(payload.get('collection'), dict):
                raise ValueError('VOICE_ARCHIVE_UNVERIFIED')
            zone = datetime.fromisoformat(payload['range']['start']).tzinfo
            messages = []
            for _, item in selected:
                stamp = datetime.fromisoformat(item['time'])
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=zone)
                messages.append(Message(local_id=item['local_id'], ts=stamp, sender=item['sender'],
                    sender_username=item.get('sender_id', ''), base=34, sub=item.get('sub_type', 0),
                    text=item['text'], voice=item.get('voice'), source_shard=item.get('source_shard', '')))
            enrich(cfg, chat, messages)
            added_chars = 0
            for (index, original), message in zip(selected, messages):
                updated = dict(original, text=message.text, voice=message.voice)
                if updated != original:
                    payload['messages'][index] = updated
                    changed = True
                    if (message.voice or {}).get('transcription', {}).get('state') == 'transcribed':
                        added_chars += len(message.text)
            if changed:
                payload['stats']['chars'] += added_chars
                archive.revise_material(cfg, date, payload)
                daily.revise_material(cfg, date, chat, payload)
        return {'state': 'updated' if changed else 'unchanged', 'date': date,
                'revision': (payload.get('collection') or {}).get('revision'),
                'archive': archive.archive_path(cfg, date, chat), 'voice': summary(payload)}
