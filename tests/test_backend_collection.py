"""T1 acceptance at shipped CLI and real HTTP, using synthetic SQLite."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from urllib.parse import urlencode

from test_readiness import reader, get

DAY = '2026-10-25'
GROUPS = ['fixture-a@chatroom', 'fixture-b@chatroom']


def sql_file(path, statements):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as cn:
        with cn:
            for sql, values in statements:
                cn.execute(sql, values)


def prepare(root, config_path, names=('同名群', '同名群')):
    state = root / 'personal'
    snap = state / 'decrypted'
    sql_file(snap / 'contact/contact.db', [
        ('CREATE TABLE contact(username TEXT, nick_name TEXT, remark TEXT)', ()),
        *[('INSERT INTO contact VALUES(?,?,?)', (u, name, '')) for u, name in zip(GROUPS, names)],
        ('INSERT INTO contact VALUES(?,?,?)', ('wxid_alpha', '成员甲', '')),
        ('INSERT INTO contact VALUES(?,?,?)', ('wxid_beta', '成员乙', '')),
    ])
    timestamp = int(datetime(2026, 10, 25, 12).timestamp())
    for i, u in enumerate(GROUPS):
        table = 'Msg_' + hashlib.md5(u.encode()).hexdigest()
        sql_file(snap / f'message/message_{i}.db', [
            ('CREATE TABLE Name2Id(user_name TEXT)', ()),
            ('INSERT INTO Name2Id VALUES(?)', ('wxid_alpha' if i == 0 else 'wxid_beta',)),
            (f'CREATE TABLE {table}(local_id INTEGER, create_time INTEGER, real_sender_id INTEGER, local_type INTEGER, message_content TEXT)', ()),
            (f'INSERT INTO {table} VALUES(1,?,1,1,?)', (timestamp, '甲的合成消息' if i == 0 else '乙的合成消息')),
        ])
    config_path.parent.mkdir(exist_ok=True)
    cfg = {'paths': {key: str(state / key) for key in ('root', 'data', 'reports', 'decrypted', 'secrets')},
           'compose': {'timezone': 'Asia/Shanghai'},
           'chats': [{'username': u, 'name': n, 'daily': True} for u, n in zip(GROUPS, names)]}
    config_path.write_text(json.dumps(cfg), encoding='utf-8')
    import time
    (snap / '.stamp.json').write_text(json.dumps({
        'schema_version': 2, 'decrypted_at': int(time.time()), 'source_dir': '',
        'required': ['contact/contact.db', 'message/message_0.db', 'message/message_1.db'],
        'files': {rel: {'verified_at': int(time.time())} for rel in
                  ('contact/contact.db', 'message/message_0.db', 'message/message_1.db')},
        'failures': {},
    }))
    return snap, cfg


def cli(package, env, *args):
    return subprocess.run([sys.executable, '-B', str(package / 'scripts/fetch.py'), *args],
                          env=env, cwd=package.parent, text=True, capture_output=True, timeout=15)


def endpoint(base, name, **params):
    code, body = get(base, '/api/' + name + '?' + urlencode(params))
    if code != 200:
        raise AssertionError((code, body))
    return json.loads(body)


class CollectionTest(unittest.TestCase):
    def test_same_name_and_renamed_groups_keep_identity_after_reindex(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for u, text in zip(GROUPS, ('甲的合成消息', '乙的合成消息')):
                self.assertEqual(endpoint(base, 'messages', date=DAY, username=u)['messages'][0]['text'], text)
            result = cli(package, env, 'reindex')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(endpoint(base, 'day', date=DAY)['chats']), 2)
            sql_file(snap / 'contact/contact.db', [('UPDATE contact SET nick_name=? WHERE username=?', ('改名群', GROUPS[0]))])
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(endpoint(base, 'entry', date=DAY, username=GROUPS[0])['chat'], '改名群')
            self.assertEqual(len(list((Path(cfg['paths']['data']) / DAY).glob('*.json'))), 2)

    def test_each_shard_resolves_its_own_repeated_sender_rowid(self):
        with reader() as (root, package, cp, env, base):
            prepare(root, cp)
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(endpoint(base, 'messages', date=DAY, username=GROUPS[0])['messages'][0]['sender'], '成员甲')
            self.assertEqual(endpoint(base, 'messages', date=DAY, username=GROUPS[1])['messages'][0]['sender'], '成员乙')

    def test_broken_shard_fails_visibly_and_preserves_last_success(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertEqual(result.returncode, 0, result.stderr)
            (snap / 'message/message_1.db').write_bytes(b'broken SQLite fixture')
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(entry['collection']['state'], 'failed')
            self.assertFalse(entry['collection']['coverage']['complete'])
            self.assertEqual(entry['collection']['coverage']['issues'][0]['code'], 'SHARD_QUERY_FAILED')
            self.assertEqual(endpoint(base, 'messages', date=DAY, username=GROUPS[0])['total'], 1)
            self.assertNotIn(str(root), json.dumps(entry))

    def test_successful_zero_messages_is_recorded_separately_from_not_collected(self):
        with reader() as (root, package, cp, env, base):
            prepare(root, cp)
            result = cli(package, env, 'archive', '--config', '--date', '2026-10-24', '--allow-stale')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            empty = endpoint(base, 'entry', date='2026-10-24', username=GROUPS[0])
            self.assertEqual(empty['collection']['state'], 'empty')
            self.assertEqual(empty['collection']['message_count'], 0)
            self.assertTrue(empty['collection']['coverage']['complete'])
            self.assertEqual(empty['collection']['range'], {
                'from': '2026-10-24T00:00:00+08:00', 'to': '2026-10-25T00:00:00+08:00',
                'timezone': 'Asia/Shanghai'})
            self.assertIsNotNone(empty['collection']['revision'])
            self.assertEqual(empty['report']['state'], 'insufficient')
            missing = endpoint(base, 'entry', date='2026-10-23', username=GROUPS[0])
            self.assertEqual(missing['collection']['state'], 'not_collected')
            self.assertIsNone(missing['collection']['message_count'])

    def test_report_links_and_material_versions_survive_recollection_and_reindex(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            story = root / 'story.json'
            story.write_text(json.dumps({'username': GROUPS[0], 'group_name': '同名群',
                                         'date': DAY, 'lead_title': '合成日报甲', 'opening': '仅验证渲染与登记'}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/render_daily.py'),
                                     str(story), '--no-png', '--no-avatar'], env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(entry['report']['state'], 'ready')
            source = entry['collection']['revision']
            self.assertEqual(entry['report']['source_revision'], source)
            html_url = entry['report']['html_url']
            self.assertIn('合成日报甲', get(base, html_url)[1])
            self.assertIsNone(entry['report']['png_url'])
            self.assertIsNone(endpoint(base, 'entry', date=DAY, username=GROUPS[1])['report']['html_url'])
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            unchanged = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(unchanged['collection']['revision'], source)
            self.assertEqual(unchanged['report']['state'], 'ready')
            table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
            sql_file(snap / 'message/message_0.db', [(f'UPDATE {table} SET message_content=?', ('更新后的合成消息',))])
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            changed = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertNotEqual(changed['collection']['revision'], source)
            self.assertEqual(changed['report']['state'], 'stale')
            self.assertEqual(changed['report']['html_url'], html_url)
            self.assertEqual(cli(package, env, 'reindex').returncode, 0)
            self.assertEqual(endpoint(base, 'entry', date=DAY, username=GROUPS[0])['report'], changed['report'])

    def test_failure_before_first_success_survives_reindex_and_never_looks_empty(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            (snap / 'message/message_1.db').write_bytes(b'broken SQLite fixture')
            result = cli(package, env, 'archive', '--config', '--date', DAY)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(cli(package, env, 'reindex').returncode, 0)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(entry['collection']['state'], 'failed')
            code, body = get(base, '/api/messages?' + urlencode({'date': DAY, 'username': GROUPS[0]}))
            self.assertEqual(code, 409, body)
            self.assertEqual(json.loads(body)['code'], 'COLLECTION_FAILED')
            for row in endpoint(base, 'browse')['matrix']['rows']:
                self.assertEqual(row['cells'][0]['collection']['state'], 'failed')

    def test_public_assessment_reads_stable_archive_identity(self):
        with reader() as (root, package, cp, env, base):
            prepare(root, cp, names=('甲/乙', '甲:乙'))
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            self.assertEqual(cli(package, env, 'reindex').returncode, 0)
            for username in GROUPS:
                result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/check_story.py'),
                                         '--assess', username, '--date', DAY], env=env,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(endpoint(base, 'day', date=DAY)['chats']), 2)

    def test_legacy_archives_keep_source_identity_and_ambiguous_names_require_choice(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            directory = Path(cfg['paths']['data']) / DAY
            for i, path in enumerate(sorted(directory.glob('*.json'))):
                path.rename(directory / f'旧资料-{i}.json')
            self.assertEqual(cli(package, env, 'reindex').returncode, 0)
            for username in GROUPS:
                self.assertEqual(endpoint(base, 'messages', date=DAY, username=username)['total'], 1)
            story = root / 'ambiguous-story.json'
            story.write_text(json.dumps({'group_name': '同名群', 'date': DAY}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/render_daily.py'),
                                     str(story), '--no-png', '--no-avatar'], env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertFalse(Path(cfg['paths']['reports']).exists())
            unknown = directory / '缺少身份.json'
            unknown.write_text(json.dumps({'chat': {'name': '同名群'}, 'messages': []}))
            result = cli(package, env, 'reindex')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(unknown.exists())
            self.assertEqual(len(endpoint(base, 'day', date=DAY)['chats']), 2)

    def test_reindex_does_not_replace_canonical_material_with_an_old_named_copy(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            directory = Path(cfg['paths']['data']) / DAY
            payload = next(json.loads(path.read_text()) for path in directory.glob('*.json')
                           if json.loads(path.read_text())['chat']['username'] == GROUPS[0])
            payload['messages'][0]['text'] = '过期的旧副本'
            (directory / '旧群名.json').write_text(json.dumps(payload))
            self.assertEqual(cli(package, env, 'reindex').returncode, 0)
            results = endpoint(base, 'search', q='甲的合成消息')['results']
            self.assertEqual(len(results), 1)
            self.assertEqual(endpoint(base, 'messages', date=DAY, username=GROUPS[0])['messages'][0]['text'], '甲的合成消息')
            self.assertTrue((directory / '旧群名.json').exists())

    def test_missing_iana_timezone_data_is_a_durable_actionable_failure(self):
        with reader() as (root, package, cp, env, base):
            prepare(root, cp)
            env = dict(env, PYTHONTZPATH=str(root / 'no-timezone-database'))
            result = cli(package, env, 'archive', '--config', '--date', DAY)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('Traceback', result.stderr)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(entry['collection']['state'], 'failed')
            issue = entry['collection']['coverage']['issues'][0]
            self.assertEqual(issue['code'], 'TIMEZONE_UNAVAILABLE')
            self.assertEqual(issue['next_action'], 'repair_timezone_in_workbuddy')
            self.assertFalse(issue['retryable'])

    def test_snapshot_must_cover_configured_timezone_day_end(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp)
            cfg['compose']['timezone'] = 'America/New_York'
            cp.write_text(json.dumps(cfg))
            env = dict(env, TZ='UTC')
            stamp = json.loads((snap / '.stamp.json').read_text())
            cutoff = int(datetime.fromisoformat('2026-10-26T02:00:00+00:00').timestamp())
            stamp['decrypted_at'] = cutoff
            for meta in stamp['files'].values():
                meta['verified_at'] = cutoff
            (snap / '.stamp.json').write_text(json.dumps(stamp))
            result = cli(package, env, 'archive', '--config', '--date', DAY, '--allow-stale')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            self.assertEqual(entry['collection']['state'], 'failed')
            self.assertEqual(entry['collection']['range']['to'], '2026-10-26T00:00:00-04:00')
            self.assertEqual(entry['collection']['coverage']['issues'][0]['code'], 'SNAPSHOT_INCOMPLETE')
            cutoff = int(datetime.fromisoformat('2026-10-26T04:00:00+00:00').timestamp())
            stamp['decrypted_at'] = cutoff
            for meta in stamp['files'].values():
                meta['verified_at'] = cutoff
            (snap / '.stamp.json').write_text(json.dumps(stamp))
            result = cli(package, env, 'archive', '--config', '--date', DAY)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(endpoint(base, 'entry', date=DAY, username=GROUPS[0])['collection']['state'], 'collected')

    def test_failed_name_selection_never_creates_a_name_as_group_id(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = prepare(root, cp, names=('单一名称群', '另一个群'))
            (snap / '.stamp.json').unlink()
            result = cli(package, env, 'archive', '--chats', '单一名称群', '--date', DAY)
            self.assertNotEqual(result.returncode, 0)
            day = endpoint(base, 'day', date=DAY)
            self.assertEqual({row['username'] for row in day['chats']}, set(GROUPS))
            self.assertEqual(endpoint(base, 'entry', date=DAY, username=GROUPS[0])['collection']['state'], 'failed')
            result = cli(package, env, 'archive', '--chats', '无法确认的群名', '--date', DAY)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual({row['username'] for row in endpoint(base, 'day', date=DAY)['chats']}, set(GROUPS))


if __name__ == '__main__':
    unittest.main()
