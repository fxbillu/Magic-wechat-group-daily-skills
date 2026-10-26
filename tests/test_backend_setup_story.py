"""Mechanical first-report checks through the shipped checker CLI."""
import json
import subprocess
import sys
import unittest

from test_readiness import reader
from test_backend_collection import DAY, GROUPS


def manuscript(root, *, wrong_author=False):
    archive = {'chat': {'username': GROUPS[0], 'name': '合成群'},
               'stats': {'total': 2, 'chars': 14, 'unique_senders': 2},
               'messages': [
                   {'local_id': 1, 'source_shard': 'message_0.db', 'time': DAY + ' 09:00:00',
                    'sender': '成员甲', 'sender_id': 'wxid_alpha', 'type': 'text', 'text': '甲的合成原话。'},
                   {'local_id': 1, 'source_shard': 'message_1.db', 'time': DAY + ' 10:00:00',
                    'sender': '成员乙', 'sender_id': 'wxid_beta', 'type': 'text', 'text': '乙的合成原话。'}]}
    story = {'username': GROUPS[0], 'group_name': '合成群', 'date': DAY, 'lead_title': '合成稿',
             'opening': '这' * 150,
             'timeline': [{'no': str(i + 1), 'time': f'{9 + i}:00', 'theme': '合成话题',
                           'story': '这' * 150, 'cast': ['成员甲', '成员乙'], 'quotes': []} for i in range(3)],
             'highlights': [{'name': n, 'tag': '合成角色', 'desc': '合成说明'} for n in ('成员甲', '成员乙')],
             'stats': {'total_messages': 2, 'total_chars': 14, 'unique_senders': 2},
             'footer_quote': {'text': '乙的合成原话。', 'who': '成员乙', 'attr': '成员乙'}}
    story['timeline'][0]['quotes'] = [{'text': '甲的合成原话。', 'who': '成员乙' if wrong_author else '成员甲'}]
    arc, draft = root / 'synthetic-archive.json', root / 'story.json'
    arc.write_text(json.dumps(archive))
    draft.write_text(json.dumps(story))
    return arc, draft, archive, story


def check(package, env, arc, draft):
    return subprocess.run([sys.executable, '-B', str(package / 'scripts/tools/check_story.py'),
                           str(draft), '--archive', str(arc)], env=env, text=True,
                          capture_output=True, timeout=10)


class StoryTest(unittest.TestCase):
    def test_quote_must_match_author_and_text_on_the_same_source_message(self):
        with reader() as (root, package, cp, env, base):
            arc, draft, _, story = manuscript(root, wrong_author=True)
            wrong = check(package, env, arc, draft)
            self.assertEqual(wrong.returncode, 1, wrong.stdout + wrong.stderr)
            self.assertIn('原话与署名', wrong.stdout)
            story['timeline'][0]['quotes'][0]['who'] = '成员甲'
            draft.write_text(json.dumps(story))
            correct = check(package, env, arc, draft)
            self.assertEqual(correct.returncode, 0, correct.stdout + correct.stderr)

    def test_source_identity_and_footer_author_are_checked_when_available(self):
        with reader() as (root, package, cp, env, base):
            arc, draft, _, story = manuscript(root)
            quote = story['timeline'][0]['quotes'][0]
            quote['source_id'] = 'message_1.db:1'
            draft.write_text(json.dumps(story))
            self.assertEqual(check(package, env, arc, draft).returncode, 1)
            quote['source_id'] = 'message_0.db:1'
            story['footer_quote']['who'] = '成员甲'
            draft.write_text(json.dumps(story))
            self.assertEqual(check(package, env, arc, draft).returncode, 1)
            story['footer_quote']['who'] = '成员乙'
            draft.write_text(json.dumps(story))
            self.assertEqual(check(package, env, arc, draft).returncode, 0)


if __name__ == '__main__':
    unittest.main()
