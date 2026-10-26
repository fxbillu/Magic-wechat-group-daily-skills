"""T3 history acceptance through the shipped CLI and real reader HTTP."""
import json
import subprocess
import sys
import unittest

from test_readiness import get, reader
from test_backend_collection import DAY, GROUPS, cli, endpoint, prepare


class HistoryTest(unittest.TestCase):
    def test_keyword_group_date_sender_and_type_filters_combine(self):
        with reader() as (root, package, cp, env, base):
            prepare(root, cp)
            result = cli(package, env, 'archive', '--config', '--date', DAY)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            matches = endpoint(base, 'search', q='合成消息', chat=GROUPS[1],
                               **{'from': DAY, 'to': DAY, 'sender': '成员乙', 'type': 'text'})
            self.assertEqual(matches['count'], 1)
            row = matches['results'][0]
            self.assertEqual((row['username'], row['date'], row['sender'], row['text']),
                             (GROUPS[1], DAY, '成员乙', '乙的合成消息'))
            self.assertEqual(endpoint(base, 'search', q='合成消息', chat=GROUPS[0],
                                      **{'from': DAY, 'to': DAY, 'sender': '成员乙'})['count'], 0)
            self.assertEqual(endpoint(base, 'search', q='合成消息', chat='fixture-')['count'], 0)
            self.assertEqual(endpoint(base, 'search', q='合成消息', chat=GROUPS[1],
                                      **{'from': '2026-10-26', 'to': '2026-10-27'})['count'], 0)

    def test_current_follow_list_does_not_invent_historical_missing_groups(self):
        with reader() as (root, package, cp, env, base):
            _, cfg = prepare(root, cp)
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            new_id = 'fixture-new@chatroom'
            cfg['chats'].append({'username': new_id, 'name': '后来关注的群', 'daily': True})
            cp.write_text(json.dumps(cfg))
            day = endpoint(base, 'day', date=DAY)
            self.assertEqual({row['username'] for row in day['chats']}, set(GROUPS))
            self.assertEqual(day['missing'], 0)
            matrix = endpoint(base, 'browse')['matrix']
            new_row = next(row for row in matrix['rows'] if row['username'] == new_id)
            self.assertEqual(len(new_row['cells']), len(matrix['dates']))
            self.assertIsNone(new_row['cells'][0]['expected'])
            explicit = endpoint(base, 'entry', date=DAY, username=new_id)
            self.assertIsNone(explicit['expected'])
            self.assertEqual(explicit['collection']['state'], 'not_collected')

    def test_effective_date_is_inclusive_and_unfollowing_keeps_actual_history(self):
        with reader() as (root, package, cp, env, base):
            _, cfg = prepare(root, cp)
            self.assertEqual(cli(package, env, 'archive', '--config', '--date', DAY).returncode, 0)
            new_id = 'fixture-new@chatroom'
            cfg['chats'].append({'username': new_id, 'name': '后来关注的群', 'daily': True,
                                 'effective_from': '2026-10-26'})
            cp.write_text(json.dumps(cfg))
            before = endpoint(base, 'day', date=DAY)
            self.assertEqual({row['username'] for row in before['chats']}, set(GROUPS))
            after = endpoint(base, 'day', date='2026-10-26')
            self.assertEqual([row['username'] for row in after['chats']], [new_id])
            self.assertTrue(after['chats'][0]['expected'])
            self.assertEqual(after['missing'], 1)
            self.assertFalse(endpoint(base, 'entry', date=DAY, username=new_id)['expected'])
            matrix = endpoint(base, 'browse')['matrix']
            self.assertFalse(next(row for row in matrix['rows'] if row['username'] == new_id)['cells'][0]['expected'])
            story = root / 'story.json'
            story.write_text(json.dumps({'username': GROUPS[0], 'group_name': '同名群',
                                         'date': DAY, 'lead_title': '取消关注后仍可读的合成稿'}))
            result = subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/render_daily.py'),
                                     str(story), '--no-png', '--no-avatar'], env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report_url = endpoint(base, 'entry', date=DAY, username=GROUPS[0])['report']['html_url']
            cfg['chats'] = [cfg['chats'][-1]]  # remove former groups from current follow list
            cp.write_text(json.dumps(cfg))
            self.assertEqual({row['username'] for row in endpoint(base, 'day', date=DAY)['chats']}, set(GROUPS))
            timeline = endpoint(base, 'chat', username=GROUPS[0])
            self.assertEqual(timeline['entries'][0]['date'], DAY)
            self.assertEqual(timeline['entries'][0]['report']['html_url'], report_url)
            code, html = get(base, report_url)
            self.assertEqual(code, 200)
            self.assertIn('取消关注后仍可读的合成稿', html)
            self.assertEqual(endpoint(base, 'search', q='甲的合成消息', chat=GROUPS[0])['count'], 1)
            cfg['chats'][0]['effective_from'] = '2026-02-31'
            cp.write_text(json.dumps(cfg))
            self.assertEqual(endpoint(base, 'day', date='2026-10-26')['chats'], [])
            self.assertIsNone(endpoint(base, 'entry', date=DAY, username=new_id)['expected'])


if __name__ == '__main__':
    unittest.main()
