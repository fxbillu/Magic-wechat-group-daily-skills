"""Public CLI -> Python reader -> real browser checks for archived analysis."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from test_readiness import reader
from test_backend_collection import DAY, GROUPS, endpoint
from test_backend_analysis import analysis_fixture, archive_groups, render


class AnalysisBrowserTest(unittest.TestCase):
    def test_context_cards_activity_and_source_bound_analysis(self):
        space = 'wechat-analysis-' + uuid.uuid4().hex[:10]
        with reader() as (root, package, cp, env, base), tempfile.TemporaryDirectory(prefix='wechat-analysis-', dir='/tmp') as evidence:
            _, cfg = analysis_fixture(root, cp)
            archive_groups(package, env)
            path = Path(cfg['paths']['data']) / DAY / (hashlib.sha256(GROUPS[0].encode()).hexdigest() + '.json')
            payload = json.loads(path.read_text())
            m = payload['messages'][10]
            story = {'username': GROUPS[0], 'group_name': '同名群', 'date': DAY,
                     'source_revision': payload['collection']['revision'],
                     'lead_title': '合成数据：对账讨论日报', 'opening': '仅用于界面与来源核验的合成样例。',
                     'analysis': {
                         'overview': {'summary': '本次围绕对账问题展开，结果仍待确认。', 'source_ids': [m['message_id']]},
                         'topics': [{'title': '对账问题', 'summary': '两位同名成员继续核对对账问题。', 'source_ids': [m['message_id']]}],
                         'followups': [{'title': '确认对账结果', 'summary': '相关人员仍需核对结果。', 'source_ids': [m['message_id']]}],
                         'people': [{'sender_id': 'wxid_alpha', 'name': '小陈·后端',
                                     'summary': '提出对账问题并继续讨论。', 'source_ids': [m['message_id']]}],
                         'quotes': [{'who': m['sender'], 'text': m['text'], 'source_id': m['message_id']}]}}
            draft = root / 'story.json'
            draft.write_text(json.dumps(story))
            result = render(package, env, draft)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(endpoint(base, 'analysis', date=DAY, username=GROUPS[0])['analysis']['state'], 'ready')
            inputs = dict(space=space, base=base, day=DAY, group=GROUPS[0], evidence=evidence)
            script = 'const input=' + json.dumps(inputs) + ';\n' + (HERE / 'analysis-browser.mjs').read_text()
            try:
                checked = subprocess.run(['ego-browser', 'nodejs'], input=script, text=True,
                                         capture_output=True, timeout=90)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            finally:
                cleanup = subprocess.run(['ego-browser', 'nodejs'], input=f'const task=await taskSpace("{space}");await task.finish({{keep:[]}});',
                                         text=True, capture_output=True, timeout=30)
                destination = os.environ.get('WECHAT_ANALYSIS_EVIDENCE_DIR')
                if destination:
                    target = Path(destination)
                    target.mkdir(parents=True, exist_ok=True)
                    for image in Path(evidence).glob('*.png'):
                        shutil.copyfile(image, target / image.name)
                self.assertEqual(cleanup.returncode, 0, cleanup.stdout + cleanup.stderr)


if __name__ == '__main__':
    unittest.main()
