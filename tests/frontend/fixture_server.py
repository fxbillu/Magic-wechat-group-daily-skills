"""Contract-v1 synthetic HTTP peer; never included in the Skill package.

Run from any checkout with Python 3.11+: python3 -B tests/frontend/fixture_server.py
All groups/messages/report documents below are synthetic. No production data access.
"""
import copy
import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

WEB = Path(__file__).resolve().parents[2] / 'skills/wechat-group-daily/scripts/web'
DATE = '2026-10-25'

def entry(username, collection, report, count=None, url=None):
    return dict(username=username, chat='合成同名群', date=DATE, state='ready',
                total=count, unique_senders=1, chars=count, title='',
                collection=dict(state=collection, revision='synthetic-v2', message_count=count,
                    observed_at='2026-10-26T08:30:00+08:00',
                    range={'from': '2026-10-25T00:00:00+08:00', 'to': '2026-10-26T00:00:00+08:00', 'timezone': 'Asia/Shanghai'},
                    coverage={'complete': collection in ('collected', 'empty'), 'issues': []}),
                report=dict(state=report, source_revision='synthetic-v1', composed_at=None,
                    html_url=url, png_url=None, reason_code=None))

ENTRIES = [entry('fixture-missing', 'not_collected', 'pending'),
           entry('fixture-failed', 'failed', 'pending'),
           entry('fixture-empty', 'empty', 'pending', 0),
           entry('fixture-short', 'collected', 'insufficient', 1),
           entry('fixture-pending', 'collected', 'pending', 2),
           entry('fixture-ready', 'collected', 'ready', 2, '/r/synthetic-ready.html'),
           entry('fixture-stale', 'collected', 'stale', 3, '/r/synthetic-old.html'),
           entry('fixture-running', 'running', 'running'),
           entry('fixture-unknown', None, None),
           entry('fixture-broken', 'collected', 'ready', 2),
           entry('fixture-invalid-empty', 'empty', 'pending')]
CHATS = [dict(username=e['username'], chat=e['chat'], followed=True, days=1,
              total=e['total'], reports=0, last_date=DATE, last_state='ready') for e in ENTRIES]
# This newly followed group has no past entries; the UI must not invent a past failure.
CHATS.append(dict(username='fixture-new', chat='后来关注的合成群', followed=True, days=0, total=0, reports=0))
STATUS = dict(schema_version=1, configuration={'state':'configured'},
              reading={'available':True}, first_report={'state':'not_observed','verified_at':None},
              schedule=dict(registered=None, task_id=None, readback_at=None, enabled=None,
                            timezone='Asia/Shanghai', trigger_time='08:15', target_rule='yesterday',
                            planned_at=None, target_date=None, last_scheduled_run=None),
              last_run=None, followed_chats=[{'username':c['username'],'name':c['chat']} for c in CHATS])

def browse(entries):
    day = dict(date=DATE, chats=entries, entries=entries, total=10, reports=1, pending=1, missing=1)
    return dict(overview=dict(reports=2,msgs=10,entries=len(entries),first_date=DATE,last_date=DATE),
                today=day, chats=CHATS, days=[DATE], recent=[dict(day, chats=len(entries))],
                dayrows=[dict(date=DATE,chats=len(entries),total=10,ready=1,pending=1,empty=1)],
                matrix=dict(dates=[DATE],rows=[dict(username=e['username'],chat=e['chat'],cells=[e]) for e in entries]))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        super().end_headers()

    def do_GET(self):
        # Browser profiles may cache earlier fixture peers on the same loopback port.
        # Every test must consume the source currently under test.
        if 'If-Modified-Since' in self.headers:
            del self.headers['If-Modified-Since']
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        one = lambda name, default='': q.get(name, [default])[0]
        entries = copy.deepcopy(ENTRIES)
        scenario = self.server.scenario
        if url.path == '/api/status':
            status = copy.deepcopy(STATUS)
            if scenario == 'unconfigured':
                status.update(configuration={'state':'unconfigured'}, reading={'available':False,'code':'NOT_CONFIGURED','message':'尚未初始化。请在 WorkBuddy 中完成账号与关注群设置。','retryable':False,'next_action':'initialize_in_workbuddy'})
            return self.json(status)
        if url.path == '/api/browse':
            if scenario == 'browse-error':
                return self.json({'error':'合成索引读取失败','code':'FIXTURE_FAILED','retryable':False,'next_action':'repair_reading_index_in_workbuddy'},500)
            if scenario == 'empty':
                data=browse([]); data.update(recent=[],today=None,days=[],dayrows=[],chats=[],matrix={'dates':[],'rows':[]})
                data['overview'].update(entries=0,reports=0,msgs=0,first_date=None,last_date=None)
                return self.json(data)
            return self.json(browse(entries))
        if url.path == '/api/day':
            if one('date') == '2026-10-23':
                time.sleep(1)
            if one('date') == '2026-10-24':
                return self.json({'error':'合成日期读取失败','code':'FIXTURE_FAILED','retryable':True,'next_action':'retry_in_workbuddy'}, 500)
            return self.json(dict(date=one('date'),chats=entries if one('date') == DATE else [],total=10))
        if url.path == '/api/chat':
            if one('username') == 'fixture-average':
                history = [entry('fixture-average','collected','pending',2), entry('fixture-average','empty','pending',0)]
                history[1]['date']='2026-10-24'
                return self.json(dict(username='fixture-average',chat='合成计数群',entries=history))
            if one('username') == 'fixture-delayed':
                time.sleep(1)
            return self.json(dict(username=one('username'),chat='合成同名群',entries=[e for e in entries if e['username']==one('username')]))
        if url.path == '/api/entry':
            if one('username') == 'fixture-delayed':
                time.sleep(1)
            e = next((e for e in entries if e['username']==one('username')), None)
            return self.json(e or {'error':'没有该交点'}, 200 if e else 404)
        if url.path == '/api/messages':
            return self.json(dict(total=1, offset=0, limit=40, has_more=False,
                messages=[dict(time='2026-10-25 09:00:00', sender='合成成员', type='text',text='合成测试消息')]))
        if url.path == '/api/search':
            results = [dict(username='fixture-stale',chat='合成同名群',date=DATE,time='2026-10-25 09:00:00',sender='合成成员',text='合成测试消息')]
            if one('q') != '合成' or one('chat') not in ('', 'fixture-stale') or one('from', DATE) > DATE or one('to', DATE) < DATE:
                results=[]
            return self.json(dict(query=one('q'),count=len(results),truncated=False,results=results))
        if url.path in ('/r/synthetic-ready.html','/r/synthetic-old.html'):
            data = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>合成日报</title><h1>合成可读日报</h1><p>仅供前端验证。</p></html>'.encode()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(data)
            return
        if url.path.startswith('/api/'):
            return self.json({'error':'unknown fixture endpoint'},404)
        if url.path not in ('/app.js','/app.css','/vendor/vue.global.prod.js'):
            self.path='/index.html'
        super().do_GET()

    def json(self, data, status=200):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)

    def log_message(self,*args):
        pass

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8873)
    parser.add_argument('--scenario', choices=['normal','empty','unconfigured','browse-error'],default='normal')
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.scenario=args.scenario
    server.serve_forever()
