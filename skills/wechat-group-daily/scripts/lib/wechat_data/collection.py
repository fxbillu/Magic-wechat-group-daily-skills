"""Durable collection attempts and version metadata, separate from successful material."""
from datetime import datetime, timezone as datetime_timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import settings


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


class TimezoneUnavailable(ValueError):
    issues = [{'code': 'TIMEZONE_UNAVAILABLE', 'source': 'timezone',
               'message': '配置的时区不可用，请为当前 Python 配置 IANA 时区数据后再采集。',
               'retryable': False, 'next_action': 'repair_timezone_in_workbuddy'}]


def day_range(cfg, start, end):
    timezone = (cfg.get('compose') or {}).get('timezone')
    try:
        zone = datetime_timezone.utc if timezone == 'UTC' else (ZoneInfo(timezone) if timezone else None)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise TimezoneUnavailable('TIMEZONE_UNAVAILABLE') from error
    start = start.replace(tzinfo=zone).astimezone() if zone is None else start.replace(tzinfo=zone)
    end = end.replace(tzinfo=zone).astimezone() if zone is None else end.replace(tzinfo=zone)
    return start, end, {'from': start.isoformat(), 'to': end.isoformat(), 'timezone': timezone}


def revision(payload):
    source = {'username': payload['chat']['username'], 'range': payload.get('range'),
              'messages': payload.get('messages') or []}
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_path(cfg, kind, date, username):
    stem = hashlib.sha256(username.encode()).hexdigest()
    return os.path.join(settings.data_dir(cfg), kind, date, stem + '.json')


def read_record(path):
    try:
        with open(path, encoding='utf-8') as source:
            value = json.load(source)
            return value if isinstance(value, dict) else {}
    except (ValueError, OSError):
        return {}


def failed(cfg, date, chat, start, end, issues):
    from . import archive, db
    try:
        _, _, span = day_range(cfg, start, end)
    except TimezoneUnavailable:
        span = None
    record = {'state': 'failed', 'revision': None, 'message_count': None,
              'observed_at': now(), 'range': span,
              'coverage': {'complete': False, 'issues': issues}}
    archive._atomic_write(record_path(cfg, 'collections', date, chat.username),
                          {'chat': {'username': chat.username, 'name': chat.name},
                           'date': date, 'collection': record})
    db._write(cfg, lambda cn: cn.execute(
        'INSERT INTO entry(date,username,chat,kind) VALUES(?,?,?,?) ON CONFLICT(date,username) DO NOTHING',
        (date, chat.username, chat.name, chat.kind)))


def decorate(cfg, entry):
    """Attach v1 facts without schema writes from a reading request."""
    from . import archive, material
    date, username = entry['date'], entry['username']
    payload = archive.load(cfg, date, username)
    attempt = read_record(record_path(cfg, 'collections', date, username)).get('collection')
    successful = (payload or {}).get('collection')
    # Legacy archives retain provenance but have no verified coverage evidence.
    result = dict(attempt or successful or {
        'state': 'not_collected', 'revision': None, 'message_count': None,
        'observed_at': None, 'range': None, 'coverage': {'complete': False, 'issues': []}})
    if result['state'] == 'failed' and successful:
        result['revision'] = successful['revision']
        result['message_count'] = successful['message_count']
    entry['collection'] = result
    record = read_record(record_path(cfg, 'report-records', date, username))
    root = Path(settings.reports_dir(cfg)).resolve()
    links = {}
    for field, key in (('report_html', 'html_url'), ('report_png', 'png_url')):
        rel = entry.get(field)
        target = (root / rel).resolve() if rel and not os.path.isabs(rel) else None
        valid = target is not None and root in target.parents and target.is_file()
        links[key] = '/r/' + quote(str(rel).replace('\\', '/'), safe='/') if valid else None
        if not valid:
            entry[field] = None
    enough, _ = material.sufficient(entry.get('total') or 0, entry.get('chars') or 0,
                                    entry.get('unique_senders') or 0)
    state = 'pending'
    if links['html_url']:
        state = 'orphan' if not payload else 'ready'
        if payload and (not record.get('source_revision') or
                        record.get('source_revision') != (successful or {}).get('revision')):
            state = 'stale'
    elif payload and successful and not enough:
        state = 'insufficient'
    entry['report'] = {'state': state, 'source_revision': record.get('source_revision'),
                       'composed_at': record.get('composed_at') or entry.get('composed_at'),
                       **links, 'reason_code': 'MATERIAL_INSUFFICIENT' if state == 'insufficient' else None}
