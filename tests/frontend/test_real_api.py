"""T1/T3 live integration: public CLI -> real Python HTTP -> shipped browser UI.

Synthetic plaintext SQLite stands at the Windows snapshot boundary. No mock HTTP,
fetch patches, private product calls, real WeChat data, or fixture_server imports.
Run: python3 -B -m unittest discover -s tests/frontend -p 'test_real_api.py' -v
Optional WECHAT_T1_EVIDENCE_DIR copies synthetic screenshots/HTTP outcomes there.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlencode
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
# Reuse synthetic input construction and public-process/HTTP helpers, not product internals.
from test_backend_collection import prepare, sql_file, cli, endpoint, DAY, GROUPS
from test_readiness import reader, get


class RealApiFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space = 'wechat-t1-live-' + uuid.uuid4().hex[:10]
        cls.evidence = tempfile.TemporaryDirectory(prefix='wechat-t1-live-',dir='/tmp')
        cls.outcomes = []

    @classmethod
    def tearDownClass(cls):
        cleanup = subprocess.run(['ego-browser','nodejs'], input=f'const task=await taskSpace("{cls.space}");await task.finish({{keep:[]}});', text=True,capture_output=True,timeout=30)
        target = os.environ.get('WECHAT_T1_EVIDENCE_DIR')
        if target:
            destination = Path(target).resolve()
            destination.mkdir(parents=True,exist_ok=True)
            for file in Path(cls.evidence.name).glob('*.png'):
                shutil.copyfile(file,destination/file.name)
            (destination/'outcomes.json').write_text(json.dumps(cls.outcomes,ensure_ascii=False,indent=2)+'\n')
        cls.evidence.cleanup()
        if cleanup.returncode:
            raise RuntimeError(cleanup.stdout+cleanup.stderr)

    def browser(self,base,phase,**kwargs):
        inputs = dict(space=self.space, base=base, phase=phase, day=DAY, groups=GROUPS,
                      evidence=self.evidence.name,**kwargs)
        script='const input='+json.dumps(inputs,ensure_ascii=False)+';\n'+(HERE/'real-api-browser.mjs').read_text()
        result=subprocess.run(['ego-browser','nodejs'],input=script,text=True,capture_output=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.outcomes.append(dict(check='browser',phase=phase,result='passed'))

    def archive(self,package,env,*args,success=True):
        result=cli(package,env,'archive',*args)
        if success:
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        else:
            self.assertNotEqual(result.returncode,0,result.stdout)
        return result

    def test_same_name_rename_empty_stale_failure_and_reindex_through_live_ui(self):
        import hashlib
        with reader() as (root,package,config,env,base):
            snap,cfg=prepare(root,config)
            self.archive(package,env,'--config','--date',DAY)
            self.archive(package,env,'--config','--date','2026-10-24')
            for u,sender,message in zip(GROUPS,['成员甲','成员乙'],['甲的合成消息','乙的合成消息']):
                payload=endpoint(base,'messages',date=DAY,username=u)
                self.assertEqual(payload['messages'][0]['sender'],sender)
                self.assertEqual(payload['messages'][0]['text'],message)
            self.browser(base,'initial')
            story=root/'story.json'
            story.write_text(json.dumps(dict(username=GROUPS[0],group_name='同名群',date=DAY,lead_title='合成联调日报甲',opening='仅验证公共渲染与真实前端阅读，不是模型产稿验收。')))
            result=subprocess.run([sys.executable,'-B',str(package/'scripts/tools/render_daily.py'),str(story),'--no-png','--no-avatar'],env=env,text=True,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            ready=endpoint(base,'entry',date=DAY,username=GROUPS[0])
            self.assertEqual(ready['report']['state'],'ready')
            html_url=ready['report']['html_url']
            self.assertIsNotNone(html_url)
            self.assertIn('合成联调日报甲',get(base,html_url)[1])
            self.assertIsNone(endpoint(base,'entry',date=DAY,username=GROUPS[1])['report']['html_url'])
            self.browser(base,'ready',name='同名群',html_url=html_url)
            sql_file(snap/'contact/contact.db',[('UPDATE contact SET nick_name=? WHERE username=?',('改名后的合成群',GROUPS[0]))])
            table='Msg_'+hashlib.md5(GROUPS[0].encode()).hexdigest()
            sql_file(snap/'message/message_0.db',[(f'UPDATE {table} SET message_content=?',('甲的更新合成消息',))])
            self.archive(package,env,'--config','--date',DAY)
            stale=endpoint(base,'entry',date=DAY,username=GROUPS[0])
            self.assertEqual(stale['username'],GROUPS[0])
            self.assertEqual(stale['chat'],'改名后的合成群')
            self.assertNotEqual(stale['collection']['revision'],ready['collection']['revision'])
            self.assertEqual(stale['report']['state'],'stale')
            self.assertEqual(stale['report']['html_url'],html_url)
            self.browser(base,'stale',name=stale['chat'],html_url=html_url)
            (snap/'message/message_1.db').write_bytes(b'broken synthetic SQLite shard')
            self.archive(package,env,'--config','--date',DAY,success=False)
            failed=endpoint(base,'entry',date=DAY,username=GROUPS[0])
            self.assertEqual(failed['collection']['state'],'failed')
            self.assertFalse(failed['collection']['coverage']['complete'])
            self.assertEqual(failed['report'],stale['report'])
            self.assertEqual(endpoint(base,'messages',date=DAY,username=GROUPS[0])['messages'][0]['text'],'甲的更新合成消息')
            self.browser(base,'failed',name=failed['chat'],html_url=html_url)
            self.assertEqual(cli(package,env,'reindex').returncode,0)
            rebuilt=endpoint(base,'entry',date=DAY,username=GROUPS[0])
            self.assertEqual(rebuilt['collection'],failed['collection'])
            self.assertEqual(rebuilt['report'],failed['report'])
            self.assertEqual(endpoint(base,'messages',date=DAY,username=GROUPS[1])['messages'][0]['text'],'乙的合成消息')
            self.browser(base,'reindexed',name=rebuilt['chat'],html_url=html_url)
            self.outcomes.append(dict(check='CLI/HTTP',same_name_and_rename='passed',empty_vs_uncollected='passed',source_shard_sender='passed',stale_html_preserved='passed',failed_retry_kept_material='passed',reindex='passed'))

    def test_first_failure_409_and_timezone_unavailable_are_not_empty(self):
        for phase in ['first-failure','timezone']:
            with self.subTest(phase=phase),reader() as (root,package,config,env,base):
                snap,cfg=prepare(root,config)
                if phase=='first-failure':
                    (snap/'message/message_1.db').write_bytes(b'broken synthetic SQLite shard')
                else:
                    env=dict(env,PYTHONTZPATH=str(root/'missing-timezone-data'))
                self.archive(package,env,'--config','--date',DAY,success=False)
                self.assertEqual(cli(package,env,'reindex').returncode,0)
                record=endpoint(base,'entry',date=DAY,username=GROUPS[0])
                self.assertEqual(record['collection']['state'],'failed')
                code,body=get(base,'/api/messages?'+urlencode(dict(date=DAY,username=GROUPS[0])))
                self.assertEqual(code,409,body)
                self.assertEqual(json.loads(body)['code'],'COLLECTION_FAILED')
                if phase=='timezone':
                    issue=record['collection']['coverage']['issues'][0]
                    self.assertEqual(issue['code'],'TIMEZONE_UNAVAILABLE')
                    self.assertFalse(issue['retryable'])
                    self.assertIsNone(record['collection']['range'])
                self.browser(base,phase)
                self.outcomes.append(dict(check='CLI/HTTP',phase=phase,http_messages=409,code='COLLECTION_FAILED',result='passed'))

    def test_t3_f10_combined_filters_match_stable_group_and_survive_reload(self):
        with reader() as (root,package,config,env,base):
            prepare(root,config)
            self.archive(package,env,'--config','--date',DAY)
            for username,text in zip(GROUPS,['甲的合成消息','乙的合成消息']):
                result=endpoint(base,'search',q='合成消息',chat=username,**{'from':DAY,'to':DAY})
                self.assertEqual(result['count'],1)
                self.assertEqual((result['results'][0]['username'],result['results'][0]['text']),(username,text))
            self.assertEqual(endpoint(base,'search',q='合成消息',chat='fixture-')['count'],0)
            self.assertEqual(endpoint(base,'search',q='合成消息',chat=GROUPS[0],**{'from':'2026-10-26','to':'2026-10-27'})['count'],0)
            self.browser(base,'search-filter')
            self.outcomes.append(dict(check='T3/F10',http_status=200,exact_groups=2,partial_id_matches=0,out_of_range_matches=0,result='passed'))

    def test_t3_expected_scope_and_unfollowing_keep_actual_history(self):
        with reader() as (root,package,config,env,base):
            _,cfg=prepare(root,config)
            self.archive(package,env,'--config','--date',DAY)
            self.archive(package,env,'--config','--date','2026-10-24')
            self.archive(package,env,'--chats',GROUPS[1],'--date','2026-10-26')
            known='fixture-known@chatroom'
            unknown='fixture-unknown@chatroom'
            cfg['chats'].extend([
                dict(username=known,name='有生效日的合成群',daily=True,effective_from='2026-10-26'),
                dict(username=unknown,name='旧范围未知的合成群',daily=True),
            ])
            config.write_text(json.dumps(cfg))
            self.assertEqual({e['username'] for e in endpoint(base,'day',date=DAY)['chats']},set(GROUPS))
            self.assertIs(endpoint(base,'entry',date=DAY,username=known)['expected'],False)
            self.assertIsNone(endpoint(base,'entry',date=DAY,username=unknown)['expected'])
            active=endpoint(base,'day',date='2026-10-26')['chats']
            self.assertEqual({e['username'] for e in active},{GROUPS[1],known})
            self.assertIs(next(e for e in active if e['username']==known)['expected'],True)
            self.browser(base,'scope',known=known,unknown=unknown)
            story=root/'story.json'
            story.write_text(json.dumps(dict(username=GROUPS[0],group_name='同名群',date=DAY,lead_title='合成联调日报甲')))
            result=subprocess.run([sys.executable,'-B',str(package/'scripts/tools/render_daily.py'),str(story),'--no-png','--no-avatar'],env=env,text=True,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=endpoint(base,'entry',date=DAY,username=GROUPS[0])['report']
            cfg['chats'][0]['daily']=False
            cfg['chats']=[c for c in cfg['chats'] if c['username']!=GROUPS[1]]
            config.write_text(json.dumps(cfg))
            future=endpoint(base,'day',date='2026-10-27')['chats']
            self.assertEqual([e['username'] for e in future],[known])
            for username in GROUPS:
                self.assertTrue(endpoint(base,'chat',username=username)['entries'])
            self.assertEqual(endpoint(base,'entry',date=DAY,username=GROUPS[0])['report'],report)
            self.assertEqual(get(base,report['html_url'])[0],200)
            self.browser(base,'unfollowed',html_url=report['html_url'])
            self.outcomes.append(dict(check='T3/scope',effective_day_inclusive=True,unknown_scope_not_debt=True,unfollowed_or_removed_history_preserved=True,result='passed'))


if __name__=='__main__':
    unittest.main()
