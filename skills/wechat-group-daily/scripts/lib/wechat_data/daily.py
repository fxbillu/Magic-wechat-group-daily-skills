"""One scheduled edition per group; frozen pending work survives retries."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from . import archive, collection, db, guard, material, settings
from .chat import ChatResolver
from .messages import CoverageError, MessageReader


class DailyError(ValueError):
    pass


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise DailyError('TIMEZONE_REQUIRED')
    return result


def cutoff(cfg, until):
    zone = ZoneInfo(cfg['compose']['timezone'])
    now = datetime.now(zone)
    if until:
        end = instant(until).astimezone(zone).replace(microsecond=0)
        if end > now:
            raise DailyError('FUTURE_CUTOFF')
        return end
    clock = cfg['compose'].get('time')
    if not isinstance(clock, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
        raise DailyError('CONFIRM_DAILY_TIME')
    hour, minute = map(int, clock.split(':'))
    end = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return end if now >= end else end - timedelta(days=1)


@contextmanager
def run_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / 'run.lock.db', timeout=0)
    try:
        try:
            connection.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError:
            raise DailyError('DAILY_BUSY') from None
        yield
    finally:
        connection.rollback()
        connection.close()


def load_state(path):
    if not path.exists():
        return {'version': 1}
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('version') != 1:
            raise ValueError()
        if state.get('completed_to'):
            instant(state['completed_to'])
        if state.get('pending'):
            pending = state['pending']
            if instant(pending['start']) >= instant(pending['end']):
                raise ValueError()
            if datetime.fromisoformat(pending['date']).date().isoformat() != pending['date']:
                raise ValueError()
        return state
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise DailyError('DAILY_STATE_INVALID') from None


def initial_start(cfg, username, end):
    # Only a current, readable report is evidence of successful old processing.
    if db.exists(cfg):
        for entry in db.by_chat(cfg, username, limit=10000)['entries']:
            if entry.get('report', {}).get('state') != 'ready':
                continue
            span = entry.get('collection', {}).get('range') or {}
            try:
                previous = instant(span['to']).astimezone(end.tzinfo)
            except (ValueError, TypeError, KeyError):
                continue
            if previous <= end:
                return previous
    return end - timedelta(days=1)


def settle(cfg, username, state):
    pending = state.get('pending')
    if not pending:
        return False
    payload = archive.load(cfg, pending['date'], username)
    if (not payload or payload.get('period_mode') != 'rolling'
            or payload.get('range') != {'start': pending['start'], 'end': pending['end']}
            or payload.get('collection', {}).get('revision') != pending['revision']):
        raise DailyError('PENDING_MATERIAL_CHANGED')
    entry = db.get_entry(cfg, pending['date'], username)
    if not entry:
        # Recover publication interrupted after JSON but before indexing.
        rel = Path(archive.archive_path(cfg, pending['date'], username)).relative_to(
            Path(settings.data_dir(cfg))).as_posix()
        db.save_archive(cfg, pending['date'], payload, rel)
        entry = db.get_entry(cfg, pending['date'], username)
    if not entry or entry.get('collection', {}).get('state') == 'failed':
        return False
    enough, _ = material.sufficient(payload['stats']['total'], payload['stats']['chars'],
                                   payload['stats']['unique_senders'])
    if entry.get('report', {}).get('state') != 'ready' and enough:
        return False
    reason = 'reported' if entry.get('report', {}).get('state') == 'ready' else (
        'empty' if not payload['messages'] else 'insufficient')
    state.update(completed_to=pending['end'], completed_date=pending['date'], reason=reason)
    state.pop('pending')
    return True


def prepare(cfg, until=None, finish=False):
    end = cutoff(cfg, until)
    chats = settings.active_chats(cfg)
    if not chats:
        raise DailyError('NO_FOLLOWED_GROUPS')
    root = Path(settings.data_dir(cfg)) / 'daily-state'
    results = []
    with run_lock(root):
        for configured in chats:
            username = configured['username']
            path = root / (hashlib.sha256(username.encode()).hexdigest() + '.json')
            try:
                state = load_state(path)
                settled = settle(cfg, username, state)
                if settled:
                    archive._atomic_write(str(path), state)
                if finish:
                    results.append({'username': username, 'state': 'completed' if settled else (
                        'pending' if state.get('pending') else 'nothing'), **state})
                    continue
                if state.get('pending'):
                    results.append({'username': username, 'state': 'pending', **state['pending']})
                    continue
                if state.get('completed_date', '') >= end.date().isoformat():
                    results.append({'username': username, 'state': 'nothing', 'completed_to': state['completed_to']})
                    continue
                start_value = state.get('completed_to') or state.get('started_from')
                start = instant(start_value).astimezone(end.tzinfo) if start_value else initial_start(cfg, username, end)
                if configured.get('effective_from'):
                    effective = datetime.fromisoformat(configured['effective_from']).replace(tzinfo=end.tzinfo)
                    start = max(start, effective)
                if start >= end:
                    results.append({'username': username, 'state': 'nothing', 'completed_to': start.isoformat()})
                    continue
                if not state.get('started_from'):
                    state['started_from'] = start.isoformat()
                    archive._atomic_write(str(path), state)
                if end - start > timedelta(days=7):
                    raise DailyError('CATCHUP_RANGE_REQUIRES_CONFIRMATION')
                date = end.date().isoformat()
                existing = archive.load(cfg, date, username)
                stem = hashlib.sha256(username.encode()).hexdigest()
                old_report = collection.record_path(cfg, 'report-records', date, username)
                artifacts = Path(settings.reports_dir(cfg)) / date
                old_entry = db.get_entry(cfg, date, username) if db.exists(cfg) else None
                if not existing and (Path(archive.archive_path(cfg, date, username)).exists()
                        or (old_entry and old_entry.get('report', {}).get('html_url'))
                        or Path(old_report).exists() or any(
                        (artifacts / (stem + suffix)).exists() for suffix in ('.html', '.png', '.story.json'))):
                    raise DailyError('EXISTING_EDITION_PRESERVED')
                if existing and (existing.get('period_mode') != 'rolling' or existing.get('range') != {
                        'start': start.isoformat(), 'end': end.isoformat()}):
                    raise DailyError('EXISTING_EDITION_PRESERVED')
                directory = settings.decrypted_dir(cfg)
                coverage = guard.coverage(directory)
                if not coverage['complete']:
                    raise DailyError('DECRYPTION_INCOMPLETE')
                if not guard.check(directory, target_end=end.timestamp())['fresh']:
                    raise DailyError('SNAPSHOT_INCOMPLETE')
                if not existing:
                    chat = ChatResolver(directory).get(username)
                    with MessageReader(directory) as reader:
                        messages = reader.fetch(chat, start, end)
                        stats = reader.summarize(messages)
                    archive.save(cfg, date, chat, messages, stats, start, end, period_mode='rolling')
                payload = archive.load(cfg, date, username)
                state['pending'] = {'date': date, 'start': start.isoformat(), 'end': end.isoformat(),
                                    'revision': payload['collection']['revision'],
                                    'archive': archive.archive_path(cfg, date, username)}
                archive._atomic_write(str(path), state)
                if settle(cfg, username, state):
                    archive._atomic_write(str(path), state)
                    results.append({'username': username, 'state': state['reason'],
                                    'start': start.isoformat(), 'end': end.isoformat()})
                else:
                    results.append({'username': username, 'state': 'pending', **state['pending']})
            except (DailyError, CoverageError, OSError, sqlite3.Error, LookupError) as error:
                results.append({'username': username, 'state': 'failed',
                                'code': str(error) if isinstance(error, DailyError) else 'DAILY_SOURCE_UNREADABLE'})
    return {'mode': 'once_daily', 'cutoff': end.isoformat(), 'groups': results}
