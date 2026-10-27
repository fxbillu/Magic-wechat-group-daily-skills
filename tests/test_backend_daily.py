"""Focused, standard-library CLI checks for the Windows daily workflow."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import unittest

from test_readiness import reader
from test_backend_collection import prepare, cli, GROUPS, sql_file

END = '2026-10-25T21:00:00+00:00'
START = '2026-10-24T21:00:00+00:00'


def fixture(root, cp):
    snap, cfg = prepare(root, cp)
    cfg['chats'] = cfg['chats'][:1]
    cfg['compose'].update(time='21:00', timezone='UTC')
    cp.write_text(json.dumps(cfg))
    table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
    begin, end = (int(datetime.fromisoformat(value).timestamp()) for value in (START, END))
    sql_file(snap / 'message/message_0.db', [
        (f'UPDATE {table} SET create_time=?', (begin - 1,)),
        ('INSERT INTO Name2Id VALUES(?)', ('wxid_beta',)),
        *[(f'INSERT INTO {table} VALUES(?,?,?,1,?)', (i, stamp, sender, '合成窗口消息。' * 50))
          for i, stamp, sender in ((2, begin, 1), (3, end - 1, 2), (4, end, 1))]])
    return snap, cfg


def daily(package, env, *args):
    result = cli(package, env, 'daily', '--until', END, *args)
    return result, json.loads(result.stdout)


class DailyTest(unittest.TestCase):
    def test_one_night_edition_retries_then_continues_after_report(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = fixture(root, cp)
            result, first = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(first['groups']), 1)
            pending = first['groups'][0]
            self.assertEqual(pending['state'], 'pending')
            path = Path(pending['archive'])
            original = path.read_bytes()
            payload = json.loads(original)
            self.assertEqual([m['local_id'] for m in payload['messages']], [2, 3])
            self.assertEqual(payload['range'], {'start': START, 'end': END})
            # Simulate an index publication interrupted after freezing JSON.
            with sqlite3.connect(Path(cfg['paths']['data']) / 'index.db') as connection:
                connection.execute('DELETE FROM message')
                connection.execute('DELETE FROM entry')
            _, repeated = daily(package, env)
            self.assertEqual(repeated['groups'][0]['revision'], pending['revision'])
            self.assertEqual(path.read_bytes(), original)
            _, unfinished = daily(package, env, '--finish')
            self.assertEqual(unfinished['groups'][0]['state'], 'pending')
            story = {'username': GROUPS[0], 'group_name': '合成群', 'date': pending['date'],
                     'source_revision': pending['revision'], 'lead_title': '合成日报',
                     'opening': '合成摘要', 'timeline': [], 'time_range': '模型不能改写统计窗口'}
            draft = root / 'story.json'
            draft.write_text(json.dumps(story))
            rendered = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/render_daily.py'),
                                       str(draft), '--no-png', '--no-avatar'], env=env, text=True,
                                      capture_output=True, timeout=10)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            _, complete = daily(package, env, '--finish')
            self.assertEqual(complete['groups'][0]['state'], 'completed')
            _, repeated = daily(package, env)
            self.assertEqual(repeated['groups'][0]['state'], 'nothing')
            html = next(Path(cfg['paths']['reports']).rglob('*.html')).read_text()
            self.assertIn(START, html)
            self.assertIn(END, html)
            self.assertNotIn('模型不能改写', html)
            protected, published = daily(package, env, '--reopen')
            self.assertEqual(protected.returncode, 0, protected.stderr)
            self.assertEqual(published['groups'][0]['state'], 'nothing')
            next_run = cli(package, env, 'daily', '--until', '2026-10-26T21:00:00+00:00')
            item = json.loads(next_run.stdout)['groups'][0]
            self.assertEqual(item['state'], 'insufficient')
            self.assertEqual(item['start'], END)
            self.assertEqual(len(list(Path(cfg['paths']['reports']).rglob('*.html'))), 1)
            # A quiet edition is not a published report: allow explicit reopening.
            extra_time = int(datetime.fromisoformat('2026-10-26T21:30:00+00:00').timestamp())
            table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
            sql_file(snap / 'message/message_0.db', [(f'INSERT INTO {table} VALUES(5,?,2,1,?)',
                                                    (extra_time, '补入的合成讨论。' * 50))])
            command = ('daily', '--until', '2026-10-26T22:00:00+00:00')
            unchanged = cli(package, env, *command)
            self.assertEqual(json.loads(unchanged.stdout)['groups'][0]['state'], 'nothing')
            reopened = cli(package, env, *command, '--reopen')
            self.assertEqual(reopened.returncode, 0, reopened.stdout + reopened.stderr)
            edition = json.loads(reopened.stdout)['groups'][0]
            self.assertEqual(edition['state'], 'pending')
            self.assertEqual(edition['start'], END)
            self.assertEqual(edition['end'], '2026-10-26T22:00:00+00:00')
            self.assertEqual(len(list(Path(cfg['paths']['reports']).rglob('*.html'))), 1)

    def test_first_failed_run_keeps_start_and_only_configured_groups(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = fixture(root, cp)
            stamp = snap / '.stamp.json'
            original = json.loads(stamp.read_text())
            stale = dict(original, decrypted_at=int(datetime.fromisoformat(END).timestamp()) - 1)
            stamp.write_text(json.dumps(stale))
            result, failed = daily(package, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(failed['groups'][0]['code'], 'SNAPSHOT_INCOMPLETE')
            stamp.write_text(json.dumps(original))
            result = cli(package, env, 'daily', '--until', '2026-10-26T21:00:00+00:00')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            pending = json.loads(result.stdout)['groups'][0]
            self.assertEqual(pending['start'], START)
            self.assertEqual(pending['end'], '2026-10-26T21:00:00+00:00')
            self.assertEqual(len(list(Path(cfg['paths']['data']).glob('2026-*/*.json'))), 1)

    def test_existing_natural_day_archive_is_preserved(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = fixture(root, cp)
            old = cli(package, env, 'archive', '--config', '--date', '2026-10-25')
            self.assertEqual(old.returncode, 0)
            path = next((Path(cfg['paths']['data']) / '2026-10-25').glob('*.json'))
            before = path.read_bytes()
            result, report = daily(package, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report['groups'][0]['code'], 'EXISTING_EDITION_PRESERVED')
            self.assertEqual(path.read_bytes(), before)
            # A historical report must remain protected even if its JSON was lost.
            stem = hashlib.sha256(GROUPS[0].encode()).hexdigest()
            historical = Path(cfg['paths']['reports']) / '2026-10-25' / (stem + '.html')
            historical.parent.mkdir(parents=True, exist_ok=True)
            historical.write_text('保留的旧日报')
            path.unlink()
            _, orphan = daily(package, env)
            self.assertEqual(orphan['groups'][0]['code'], 'EXISTING_EDITION_PRESERVED')
            self.assertEqual(historical.read_text(), '保留的旧日报')


if __name__ == '__main__':
    unittest.main()
