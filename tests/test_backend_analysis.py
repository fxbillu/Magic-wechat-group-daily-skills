"""Analysis acceptance through installed CLI, HTTP and actual rendered reports."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import urlencode

from test_readiness import get, reader
from test_backend_collection import DAY, GROUPS, cli, endpoint, prepare, sql_file
from test_backend_decryption import encrypted_fixture, platform_aes_double
from test_backend_setup_story import manuscript, check


def analysis_fixture(root, cp):
    from datetime import datetime
    snap, cfg = prepare(root, cp)
    sql_file(snap / 'contact/contact.db', [
        ('ALTER TABLE contact ADD COLUMN id INTEGER', ()),
        *[('UPDATE contact SET id=? WHERE username=?', (i, u))
          for i, u in [(10, GROUPS[0]), (20, GROUPS[1]), (1, 'wxid_alpha'), (2, 'wxid_beta')]],
    ])
    sql_file(snap / 'contact/contact_fts.db', [
        ('CREATE TABLE chatroom_member_fts_v3(room_id INTEGER, member_id INTEGER, a_group_remark TEXT)', ()),
        ('INSERT INTO chatroom_member_fts_v3 VALUES(10,1,?)', ('小陈·后端',)),
        ('INSERT INTO chatroom_member_fts_v3 VALUES(10,2,?)', ('小陈·后端',)),
        ('INSERT INTO chatroom_member_fts_v3 VALUES(20,2,?)', ('小陈·客户',)),
    ])
    table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
    timestamp = int(datetime(2026, 10, 25, 12).timestamp())
    sql_file(snap / 'message/message_0.db', [
        ('INSERT INTO Name2Id VALUES(?)', ('wxid_beta',)),
        (f'DELETE FROM {table}', ()),
        *[(f'INSERT INTO {table} VALUES(?,?,?,1,?)',
           (i + 1, timestamp + i * 60, 1 if i % 2 == 0 else 2,
            f'合成讨论第{i + 1}条' + ('：对账问题' if i in (10, 12) else '：继续核对。')))
          for i in range(30)],
    ])
    return snap, cfg


def archive_groups(package, env):
    result = cli(package, env, 'archive', '--config', '--date', DAY)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


def render(package, env, draft):
    return subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/render_daily.py'),
                           str(draft), '--no-png', '--no-avatar'], env=env, text=True,
                          capture_output=True, timeout=10)


class AnalysisTest(unittest.TestCase):
    def test_group_cards_are_scoped_and_same_name_people_keep_distinct_ids(self):
        with reader() as (root, package, cp, env, base):
            snap, cfg = analysis_fixture(root, cp)
            archive_groups(package, env)
            first = endpoint(base, 'messages', date=DAY, username=GROUPS[0])
            other = endpoint(base, 'messages', date=DAY, username=GROUPS[1])
            self.assertEqual({m['sender'] for m in first['messages']}, {'小陈·后端'})
            self.assertEqual(other['messages'][0]['sender'], '小陈·客户')
            measured = endpoint(base, 'analysis', date=DAY, username=GROUPS[0])
            self.assertEqual(measured['activity']['unique_senders'], 2)
            self.assertEqual([p['messages'] for p in measured['activity']['participants']], [15, 15])
            self.assertEqual(endpoint(base, 'entry', date=DAY, username=GROUPS[0])['unique_senders'], 2)
            found = endpoint(base, 'search', q='对账问题', sender='wxid_alpha')
            self.assertEqual(found['count'], 2)
            # Unknown FTS schema and a recorded optional failure both safely fall back.
            sql_file(snap / 'contact/contact_fts.db', [('DROP TABLE chatroom_member_fts_v3', ())])
            archive_groups(package, env)
            self.assertEqual(endpoint(base, 'messages', date=DAY, username=GROUPS[0])['messages'][0]['sender'], '成员甲')
            sql_file(snap / 'contact/contact_fts.db', [
                ('CREATE TABLE chatroom_member_fts_v3(room_id INTEGER, member_id INTEGER, a_group_remark TEXT)', ()),
                ('INSERT INTO chatroom_member_fts_v3 VALUES(10,1,?)', ('不应读取的旧名片',)),
            ])
            stamp_path = snap / '.stamp.json'
            stamp = json.loads(stamp_path.read_text())
            stamp['failures']['contact/contact_fts.db'] = 'DECRYPTION_FAILED'
            stamp_path.write_text(json.dumps(stamp))
            archive_groups(package, env)
            self.assertEqual(endpoint(base, 'messages', date=DAY, username=GROUPS[0])['messages'][0]['sender'], '成员甲')

    def test_search_context_survives_reindex_and_keeps_unmatched_replies(self):
        with reader() as (root, package, cp, env, base):
            _, cfg = analysis_fixture(root, cp)
            archive_groups(package, env)
            hit = endpoint(base, 'search', q='对账问题', chat=GROUPS[0], sender='wxid_alpha')['results'][-1]
            params = dict(date=DAY, username=hit['username'], key=hit['context_key'])
            context = endpoint(base, 'context', **params)
            self.assertEqual(len(context['messages']), 21)
            self.assertEqual(sum(m['is_match'] for m in context['messages']), 1)
            self.assertEqual(context['messages'][8]['text'], hit['text'])
            self.assertEqual({m['sender_id'] for m in context['messages']}, {'wxid_alpha', 'wxid_beta'})
            self.assertTrue(context['has_earlier'])
            self.assertTrue(context['has_later'])
            self.assertEqual(cli(package, env, 'reindex').returncode, 0)
            self.assertEqual(endpoint(base, 'context', **params)['anchor_id'], context['anchor_id'])
            self.assertEqual(get(base, '/api/context?' + urlencode({**params, 'username': GROUPS[1]}))[0], 409)
            archive_path = Path(cfg['paths']['data']) / DAY / (hashlib.sha256(GROUPS[0].encode()).hexdigest() + '.json')
            payload = json.loads(archive_path.read_text())
            payload['messages'][10]['text'] = '已变更的原消息'
            archive_path.write_text(json.dumps(payload))
            self.assertEqual(get(base, '/api/context?' + urlencode(params))[0], 409)

    def test_analysis_cli_merges_windows_and_reports_limits_missing_dates_and_bad_ranges(self):
        with reader() as (root, package, cp, env, base):
            analysis_fixture(root, cp)
            archive_groups(package, env)
            result = cli(package, env, 'analyze', '--chat', GROUPS[0], '--date', DAY, '--topic', '对账问题')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            body = json.loads(result.stdout)
            self.assertTrue(body['complete'])
            self.assertEqual(body['days'][0]['match_count'], 2)
            self.assertEqual(len(body['days'][0]['windows']), 1)
            self.assertEqual(body['days'][0]['activity']['total_messages'], 30)
            limited = json.loads(cli(package, env, 'analyze', '--chat', GROUPS[0], '--date', DAY,
                                     '--topic', '对账问题', '--limit', '1').stdout)
            self.assertFalse(limited['complete'])
            self.assertTrue(limited['days'][0]['truncated'])
            missing = cli(package, env, 'analyze', '--chat', GROUPS[0], '--start', DAY, '--end', '2026-10-26')
            self.assertEqual(missing.returncode, 1)
            self.assertEqual(json.loads(missing.stdout)['missing_dates'], ['2026-10-26'])
            for extra in [('--date', '2026-02-31'), ('--start', '2026-10-27', '--end', DAY),
                          ('--start', '2020-01-01', '--end', DAY), ('--date', DAY, '--end', DAY)]:
                bad = cli(package, env, 'analyze', '--chat', GROUPS[0], *extra)
                self.assertEqual(bad.returncode, 2, bad.stdout + bad.stderr)
                self.assertNotIn('Traceback', bad.stderr)

    def test_default_decryption_attempts_optional_group_cards_without_blocking_core(self):
        with reader() as (root, package, cp, env, base):
            snap, _ = prepare(root, cp)
            source, key = root / 'encrypted', bytes(range(32))
            targets = ['contact/contact.db', 'message/message_0.db', 'message/message_1.db',
                       'contact/contact_fts.db', 'message/message_fts.db']
            for rel in targets:
                encrypted_fixture(source / rel, key)
            (source / 'contact/contact_fts.db').write_bytes(b'incompatible optional database')
            keys = root / 'keys.json'
            keys.write_text(json.dumps({rel: {'enc_key': key.hex()} for rel in targets}))
            command = [sys.executable, '-B', str(package / 'scripts/tools/safe_decrypt.py'),
                       '--db-dir', str(source), '--keys', str(keys), '--output', str(snap)]
            adapted = platform_aes_double(root, env)
            result = subprocess.run(command, env=adapted, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            stamp = json.loads((snap / '.stamp.json').read_text())
            self.assertIn('contact/contact_fts.db', stamp['failures'])
            self.assertNotIn('message/message_fts.db', stamp['files'])
            self.assertNotIn('contact/contact_fts.db', stamp['required'])
            (source / 'contact/contact_fts.db').unlink()
            encrypted_fixture(source / 'contact/contact_fts.db', key)
            result = subprocess.run(command, env=adapted, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((snap / 'contact/contact_fts.db').exists())

    def test_analysis_quotes_and_people_bind_to_sources_before_render(self):
        with reader() as (root, package, cp, env, base):
            _, cfg = prepare(root, cp)
            archive_groups(package, env)
            arc, draft, payload, story = manuscript(root)
            story['analysis'] = {
                'topics': [{'title': '合成话题', 'summary': '甲提出了合成事项。', 'source_ids': ['message_0.db:1']}],
                'people': [{'sender_id': 'wxid_alpha', 'name': '成员甲', 'summary': '甲提出问题。', 'source_ids': ['message_0.db:1']}],
                'quotes': [{'who': '成员甲', 'text': '甲的合成原话。', 'source_id': 'message_0.db:1'}]}
            draft.write_text(json.dumps(story))
            self.assertEqual(check(package, env, arc, draft).returncode, 0)
            legacy_highlights = story.pop('highlights')
            draft.write_text(json.dumps(story))
            self.assertEqual(check(package, env, arc, draft).returncode, 0)
            story['highlights'] = legacy_highlights
            for change in ('quote', 'person', 'source', 'shape', 'overview', 'followups'):
                broken = json.loads(json.dumps(story))
                if change == 'quote': broken['analysis']['quotes'][0]['text'] = '润色后的假金句'
                if change == 'person': broken['analysis']['people'][0]['sender_id'] = 'wxid_beta'
                if change == 'source': broken['analysis']['topics'][0]['source_ids'] = ['missing']
                if change == 'shape': broken['analysis']['quotes'][0]['source_id'] = []
                if change == 'overview': broken['analysis']['overview'] = {'summary': '未绑定的总述', 'source_ids': ['missing']}
                if change == 'followups': broken['analysis']['followups'] = [{'title': '未绑定的待确认项', 'summary': '不能默认完成', 'source_ids': ['missing']}]
                draft.write_text(json.dumps(broken))
                invalid = check(package, env, arc, draft)
                self.assertEqual(invalid.returncode, 1, invalid.stdout + invalid.stderr)
                self.assertNotIn('Traceback', invalid.stderr)
            # Use the real collected archive to verify renderer + reader sidecar integration.
            archive_path = Path(cfg['paths']['data']) / DAY / (hashlib.sha256(GROUPS[0].encode()).hexdigest() + '.json')
            actual = json.loads(archive_path.read_text())
            m = actual['messages'][0]
            story['source_revision'] = actual['collection']['revision']
            story['analysis']['quotes'][0].update(text=m['text'], who=m['sender'], source_id=m['message_id'], source_ids=[[]])
            story['activity'] = {'participants': [{'name': '伪造统计', 'messages': 999, 'share': 1}]}
            draft.write_text(json.dumps(story))
            self.assertEqual(render(package, env, draft).returncode, 0)
            body = endpoint(base, 'analysis', date=DAY, username=GROUPS[0])
            self.assertEqual(body['analysis']['state'], 'ready')
            self.assertEqual(body['activity']['total_messages'], 1)
            self.assertEqual(body['analysis']['topics'][0]['evidence'][0]['text'], m['text'])
            html_url = endpoint(base, 'entry', date=DAY, username=GROUPS[0])['report']['html_url']
            html = get(base, html_url)[1]
            self.assertIn('原文金句', html)
            self.assertIn('人物动态', html)
            self.assertNotIn('伪造统计', html)
            before = html
            story['analysis']['quotes'][0]['text'] = '伪造'
            draft.write_text(json.dumps(story))
            self.assertEqual(render(package, env, draft).returncode, 1)
            self.assertEqual(get(base, html_url)[1], before)
            # A real recollection changes material: old report stays, analysis is marked stale.
            snap = Path(cfg['paths']['decrypted'])
            table = 'Msg_' + hashlib.md5(GROUPS[0].encode()).hexdigest()
            sql_file(snap / 'message/message_0.db', [(f'UPDATE {table} SET message_content=?', ('甲的更新消息',))])
            archive_groups(package, env)
            stale = endpoint(base, 'analysis', date=DAY, username=GROUPS[0])
            self.assertEqual(stale['analysis']['state'], 'stale')
            self.assertEqual(stale['analysis']['quotes'], [])

    def test_overview_layout_uses_real_followups_and_keeps_legacy_fallback(self):
        with reader() as (root, package, cp, env, base):
            _, cfg = analysis_fixture(root, cp)
            archive_groups(package, env)
            path = Path(cfg['paths']['data']) / DAY / (hashlib.sha256(GROUPS[0].encode()).hexdigest() + '.json')
            payload = json.loads(path.read_text())
            ref = payload['messages'][10]['message_id']
            story = {'username': GROUPS[0], 'group_name': '同名群', 'date': DAY,
                     'source_revision': payload['collection']['revision'], 'lead_title': '合成总览',
                     'opening': '合成的故事开场。', 'highlights': [{'name': '旧人物高光', 'desc': '兼容旧稿'}],
                     'analysis': {'overview': {'summary': '合成总述，待核对。', 'source_ids': [ref]},
                                  'topics': [{'title': f'合成话题{i}', 'label': '待确认', 'summary': '原始讨论仍需确认。', 'source_ids': [ref]} for i in range(4)],
                                  'followups': [{'title': '核对结果', 'summary': '仍需相关人员确认。', 'source_ids': [ref]}],
                                  'people': [{'name': '小陈·后端', 'sender_id': 'wxid_alpha', 'summary': '提出了问题。', 'source_ids': [ref]}]}}
            draft = root / 'overview.json'
            draft.write_text(json.dumps(story))
            self.assertEqual(render(package, env, draft).returncode, 0)
            entry = endpoint(base, 'entry', date=DAY, username=GROUPS[0])
            html = get(base, entry['report']['html_url'])[1]
            self.assertLess(html.index('<dl class="overview-metrics">'), html.index('<section class="overview"'))
            self.assertLess(html.index('<section class="overview"'), html.index('id="story"'))
            self.assertIn('更多话题 · 1 条', html)
            self.assertEqual(html.count('合成话题3'), 1)
            self.assertIn('待确认与下一步', html)
            self.assertIn('核对原文', html)
            self.assertNotIn('来源：message_', html)
            self.assertNotIn('旧人物高光', html)
            body = endpoint(base, 'analysis', date=DAY, username=GROUPS[0])
            self.assertEqual(body['analysis']['overview']['summary'], '合成总述，待核对。')
            self.assertEqual(body['analysis']['followups'][0]['evidence'][0]['source_id'], ref)
            # A legacy manuscript does not inherit example tasks or need new fields.
            story.pop('analysis')
            draft.write_text(json.dumps(story))
            self.assertEqual(render(package, env, draft).returncode, 0)
            html = get(base, entry['report']['html_url'])[1]
            self.assertIn('旧人物高光', html)
            self.assertNotIn('<section class="followup">', html)

    def test_context_and_overview_preserve_the_daily_rolling_window(self):
        from test_backend_daily import fixture, daily, START, END
        with reader() as (root, package, cp, env, base):
            _, cfg = fixture(root, cp)
            result, body = daily(package, env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            pending = body['groups'][0]
            payload = json.loads(Path(pending['archive']).read_text())
            message = payload['messages'][0]
            story = {'username': GROUPS[0], 'group_name': '合成群', 'date': pending['date'],
                     'source_revision': pending['revision'], 'lead_title': '跨日接续总览',
                     'opening': '合成窗口内的讨论。', 'time_range': '模型不能改写范围',
                     'analysis': {'overview': {'summary': '跨日讨论，结果待核对。', 'source_ids': [message['message_id']]},
                                  'followups': [{'title': '核对事项', 'summary': '继续核对本窗口讨论。', 'source_ids': [message['message_id']]}]}}
            draft = root / 'rolling.json'
            draft.write_text(json.dumps(story))
            self.assertEqual(render(package, env, draft).returncode, 0)
            hit = endpoint(base, 'search', q='合成窗口消息', chat=GROUPS[0])['results'][0]
            context = endpoint(base, 'context', date=hit['date'], username=hit['username'], key=hit['context_key'])
            self.assertEqual(context['scope'], 'archive_range')
            self.assertEqual(context['range'], {'start': START, 'end': END})
            self.assertEqual(len(context['messages']), 2)
            html = get(base, endpoint(base, 'entry', date=pending['date'], username=GROUPS[0])['report']['html_url'])[1]
            self.assertIn(START, html)
            self.assertIn(END, html)
            self.assertNotIn('模型不能改写范围', html)
            self.assertEqual(endpoint(base, 'analysis', date=pending['date'], username=GROUPS[0])['activity']['total_messages'], 2)
            self.assertEqual(daily(package, env, '--finish')[1]['groups'][0]['state'], 'completed')

    def test_new_read_apis_do_not_initialize_an_unconfigured_install(self):
        with reader(read_only=True) as (root, package, cp, env, base):
            for name in ('context', 'analysis'):
                code, body = get(base, '/api/' + name + '?' + urlencode({'username': GROUPS[0], 'date': DAY}))
                self.assertEqual(code, 503)
                self.assertEqual(json.loads(body)['code'], 'NOT_CONFIGURED')
            self.assertFalse(cp.exists())


if __name__ == '__main__':
    unittest.main()
