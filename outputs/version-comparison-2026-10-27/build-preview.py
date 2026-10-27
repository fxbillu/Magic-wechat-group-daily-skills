"""Build a review-only old/new demo from the same synthetic conversation."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASE_COMMIT = (json.loads((HERE / 'sample.json').read_text())['baseline_commit'] if (HERE / 'sample.json').exists()
               else subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip())
SKILL = Path('skills/wechat-group-daily')
DAY = '2026-10-26'
GROUP = 'demo-store-pilot@chatroom'
PEOPLE = [
    ('demo-lin', '小林', '林予 · 产品'),
    ('demo-chen', '小陈', '陈启 · 开发'),
    ('demo-xu', '许宁', '许宁 · 门店运营'),
    ('demo-zhou', '周然', '周然 · 项目负责人'),
]
MESSAGES = [
    ('09:05', 0, '这周先做一个小范围试点：一间演示门店，只看前台交接和收档异常。今天先把这两个场景说清楚。'),
    ('09:08', 2, '前台最容易漏的是上一班留下的交接异常。只记一句“已交接”，下一班其实不知道该接着做什么。'),
    ('09:12', 0, '那条目需要有问题、当前处理和接下来找谁，先不加销售预测和自动排班。'),
    ('09:15', 3, '先把每天能不能稳定看完一份日报跑通，再谈扩到更多门店。'),
    ('09:19', 1, '这两个场景可以先复用现在的归档和阅读页。我今天先查采集结果与日报状态的展示。'),
    ('09:24', 2, '我准备三条脱敏样例：上一班留了一箱待核对物料、收档时发现一笔退款待确认，以及第二天需要追问的交接问题。'),
    ('09:28', 0, '样例中不要放客人姓名、手机号或真实订单号，保留判断问题需要的信息就好。'),
    ('09:33', 2, '收到，我先把样例发在群里供大家看；这仍然是演示材料，不代表真实门店已经开始试用。'),
    ('09:38', 1, '我需要知道同一件事的回复怎样接起来，最好把前后的解释也保留，不只给一条关键词命中。'),
    ('09:44', 0, '日报主线还是讲清发生了什么、谁回应、产生了什么决定。附加分析放在正文之后。'),
    ('09:51', 3, '按这个范围往下做。扩店和其他场景先不排进本周试点，这只是范围决定，不是门店合作结果。'),
    ('10:02', 0, '上午先达成两个共识：范围缩小到两个场景；前台提出问题后，日报里要保留后续回应。'),
    ('14:10', 1, '检查采集状态时发现一个容易误读的地方：如果这次取数失败，页面不能写成当天没有消息。'),
    ('14:13', 0, '这里要把“采集成功但零消息”和“没有取到数据”分开。两种情况给读者的下一步不同。'),
    ('14:16', 1, '采集失败不是零消息，这两个状态必须分开。'),
    ('14:20', 2, '如果昨天已经有一份日报，今天重试失败，是不是还能看昨天留下的那份？不然门店会以为内容丢了。'),
    ('14:24', 1, '已有旧稿继续可读，同时提示本次采集失败；后面素材有变化时，再标记这份稿需要更新。'),
    ('14:29', 0, '这个做法合适。不要用“成功”覆盖失败，也不要因为这次没取到数据就把旧链接清空。'),
    ('14:35', 1, '搜索也沿用同一份冻结归档。关键词周围的回复需要一起读，避免把对方后来的纠正漏掉。'),
    ('14:39', 2, '对，门店说“已处理”后面常会补一句“但还差负责人确认”，只摘前半句就会误解。'),
    ('14:43', 0, '写稿时可以把问题和待确认项整理出来；只在聊天里说过“处理了”，不能自动写成实际验收完成。'),
    ('14:48', 1, '我会用合成消息检查这几种状态和旧稿链接，今天的检查不算 Windows 真机取数验证。'),
    ('14:54', 3, '验收口径就按这个来：界面能读、原文对应、实际门店反馈，要分别说明。'),
    ('15:00', 0, '下午先把采集失败、零消息、旧稿保留这三种情况写进演示说明，给大家一起看。'),
    ('17:05', 2, '我明天可以安排一个值班同事读演示日报，主要看能不能在两分钟内找到还要跟进的事。'),
    ('17:09', 0, '明天先用一份日报，问三个问题：漏了什么、哪一句不好理解、看完接下来会做什么。'),
    ('17:12', 1, '我整理一个候选阅读入口，配置和历史保持原来的位置；先看这轮效果再决定是否更新。'),
    ('17:16', 0, '新版本加话题、人物和原文金句，活跃数字从消息里算，别让模型猜。'),
    ('17:20', 2, '人物栏目写谁提出了问题、谁补了解释就够了，不要把发言最多的人直接写成贡献最大。'),
    ('17:24', 3, '发言量用来看讨论分布，实际进展仍然找负责人确认。'),
    ('17:29', 1, '每条分析留原文来源。素材重采以后发生变化，旧分析先提示更新，不能继续当作新的结论。'),
    ('17:34', 0, '金句只挑原话，不替群里的人润色一句更漂亮的话；话题分析再负责用自己的语言概括。'),
    ('17:39', 2, '我负责收集明天读报的反馈；现在还没有反馈结果，日报里请保留“待验证”。'),
    ('17:44', 0, '我负责汇总反馈并决定下一轮改动，陈启跟进技术问题，许宁安排值班同事参与。'),
    ('17:49', 1, '技术侧需要继续看真实 Windows 兼容、模型稿件准确性，以及是否实际到点执行；不能拿截图当这些都已完成。'),
    ('17:55', 3, '今天先交付可阅读的演示和差异说明。等看完并确认效果，再更新。'),
]


def run(command, env):
    result = subprocess.run([sys.executable, '-B', *map(str, command)], env=env,
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def build(version):
    root = HERE / 'runtime' / version
    package = root / 'skill'
    package.mkdir(parents=True, exist_ok=True)
    if version == 'before':
        manifest = json.loads(subprocess.check_output(['git', 'show', f'{BASE_COMMIT}:{SKILL}/references/release-files.json'], cwd=REPO))
    else:
        manifest = json.loads((REPO / SKILL / 'references/release-files.json').read_text())
    for rel in manifest['files']:
        target = package / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if version == 'before':
            target.write_bytes(subprocess.check_output(['git', 'show', f'{BASE_COMMIT}:{SKILL}/{rel}'], cwd=REPO))
        else:
            shutil.copyfile(REPO / SKILL / rel, target)
    state = root / 'synthetic-data'
    snap = state / 'decrypted'
    (snap / 'contact').mkdir(parents=True, exist_ok=True)
    (snap / 'message').mkdir(parents=True, exist_ok=True)
    # A fresh fixture only; no personal paths, accounts or key extraction.
    for file in snap.rglob('*.db'):
        file.unlink()
    with sqlite3.connect(snap / 'contact/contact.db') as cn:
        cn.execute('CREATE TABLE contact(id INTEGER PRIMARY KEY,username TEXT,nick_name TEXT,remark TEXT)')
        cn.execute('INSERT INTO contact VALUES(10,?,?,?)', (GROUP, '演示门店试点群', ''))
        for index, (identity, nickname, card) in enumerate(PEOPLE, 1):
            cn.execute('INSERT INTO contact VALUES(?,?,?,?)', (index, identity, nickname, ''))
    with sqlite3.connect(snap / 'contact/contact_fts.db') as cn:
        cn.execute('CREATE TABLE chatroom_member_fts_v3(room_id INTEGER,member_id INTEGER,a_group_remark TEXT)')
        for index, (_, _, card) in enumerate(PEOPLE, 1):
            cn.execute('INSERT INTO chatroom_member_fts_v3 VALUES(10,?,?)', (index, card))
    table = 'Msg_' + hashlib.md5(GROUP.encode()).hexdigest()
    with sqlite3.connect(snap / 'message/message_0.db') as cn:
        cn.execute('CREATE TABLE Name2Id(user_name TEXT)')
        cn.executemany('INSERT INTO Name2Id VALUES(?)', [(p[0],) for p in PEOPLE])
        cn.execute(f'CREATE TABLE {table}(local_id INTEGER,create_time INTEGER,real_sender_id INTEGER,local_type INTEGER,message_content TEXT)')
        for index, (clock, person, text) in enumerate(MESSAGES, 1):
            cn.execute(f'INSERT INTO {table} VALUES(?,?,?,1,?)',
                       (index, int(datetime.fromisoformat(DAY + 'T' + clock + ':00').timestamp()), person + 1, text))
    stamp = {'schema_version': 2, 'decrypted_at': int(time.time()), 'source_dir': '',
             'required': ['contact/contact.db', 'message/message_0.db'], 'failures': {},
             'files': {rel: {'verified_at': int(time.time())} for rel in ['contact/contact.db', 'message/message_0.db', 'contact/contact_fts.db']}}
    (snap / '.stamp.json').write_text(json.dumps(stamp))
    cfg = {'paths': {key: str(state / key) for key in ['root', 'data', 'reports', 'decrypted', 'secrets']},
           'compose': {'timezone': 'Asia/Shanghai', 'theme': 'magazine'},
           'chats': [{'username': GROUP, 'name': '演示门店试点群', 'daily': True, 'effective_from': DAY}]}
    config = root / 'preview-config.json'
    config.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    env = dict(os.environ, WECHAT_DAILY_CONFIG=str(config), TZ='Asia/Shanghai', PYTHONDONTWRITEBYTECODE='1')
    run([package / 'scripts/fetch.py', 'archive', '--config', '--date', DAY], env)
    archive = state / 'data' / DAY / (hashlib.sha256(GROUP.encode()).hexdigest() + '.json')
    payload = json.loads(archive.read_text())
    messages = payload['messages']
    display = lambda person: PEOPLE[person][2 if version == 'after' else 1]
    quote = lambda index: {'who': messages[index - 1]['sender'], 'text': messages[index - 1]['text'], 'source_id': messages[index - 1]['message_id']}
    opening = '上午九点，演示门店试点群没有急着增加场景，而是先把范围收窄到前台交接和收档异常。许宁指出，下一班真正需要的，是问题的当前处理和接下来找谁。下午，讨论转向采集失败与零消息的区别，以及旧日报应该怎样保留。到了傍晚，大家把明天的读报反馈和各自分工说清楚：先看一份日报能否帮助值班同事找到待跟进事项，再决定下一轮更新。今天达成的是范围、阅读方式和验收口径的共识，真实门店反馈仍待收集。'
    paragraphs = [
        '九点零五分，产品先把试点收窄到一间演示门店的两个场景：前台交接和收档异常。许宁随后解释，上一班只写“已交接”，并不能让下一班知道问题当前怎样、接下来该找谁。产品据此明确，条目需要保留问题、当前处理和下一步联系人，暂不加入销售预测和自动排班。陈启提出复用现有归档与阅读页，并希望一起保留关键词前后的解释。上午最后确认的是两个场景的范围和完整回应的阅读方式；群里准备的仍是脱敏演示材料，尚不能写成真实门店已经试用。',
        '下午两点十分，陈启提出一个容易误读的状态：取数失败时，页面不能显示当天没有消息。产品把“采集成功但零消息”和“没有取到数据”分开，许宁则追问，重试失败以后旧日报是否还能打开。陈启给出的处理是保留已有旧稿，同时提示本次失败，素材发生变化以后再标记待更新。讨论随后延伸到搜索：关键词周围的回复要一起保留，避免漏掉后来的纠正。大家还明确，群里说过“处理了”并不等于实际验收完成，合成消息检查也不能代替 Windows 真机验证。',
        '傍晚五点零五分，许宁提出安排一名值班同事阅读演示日报，看能否在两分钟内找到仍需跟进的事。产品把反馈问题限定为漏了什么、哪句难懂、读完会做什么，并提出增加话题、人物和原文金句栏目。陈启负责整理候选入口，许宁收集读报反馈，产品汇总后决定下一轮改动。周然提醒，发言量只能说明讨论分布，实际进展还要向负责人确认。当天交付的是可阅读的演示与差异说明，读报反馈、真实兼容、模型准确性和到点执行都没有被提前记作完成。',
    ]
    story = {'username': GROUP, 'group_name': '演示门店试点群', 'date': DAY,
             'source_revision': payload['collection']['revision'], 'time_range': '09:05 → 17:55',
             'lead_title': '先缩小试点，\n再把日报读完整', 'opening': opening,
             'timeline': [{'no': f'{i + 1:02d}', 'time': clock, 'badge': badge, 'theme': title,
                           'cast': [display(p) for p in cast], 'story': paragraphs[i], 'quotes': [quote(ref)], 'output': output}
                          for i, (clock, badge, title, cast, ref, output) in enumerate([
                              ('09:05', '定范围的人', '先做好两件事，不把试点铺开', [0, 2, 3], 4, '范围共识：一间演示门店、两个场景；保留问题的后续回应。'),
                              ('14:10', '守住来源的人', '采集失败，不能写成没有消息', [1, 0, 2], 15, '阅读口径：失败、零消息、旧稿待更新分别表达。'),
                              ('17:05', '接住下一步的人', '先收一份读报反馈，再决定更新', [2, 0, 1, 3], 30, '待验证：明天读报反馈；技术侧继续核对真实环境。')])],
             'highlights': [
                 {'name': display(0), 'tag': '把范围收住', 'desc': '明确两个试点场景，并把下一轮反馈问题与分工说清楚。'},
                 {'name': display(1), 'tag': '把状态说准', 'desc': '区分采集失败与零消息，提出保留旧稿和原文上下文。'},
                 {'name': display(2), 'tag': '带来门店视角', 'desc': '指出交接信息缺口，并准备安排值班同事读报反馈。'},
                 {'name': display(3), 'tag': '守住验收口径', 'desc': '提醒先跑通阅读，并把讨论与实际结果分别确认。'},
             ],
             'qas': [{'q': '这次采集失败以后，已有日报还能看吗？', 'asker': display(2),
                      'answers': [{'who': display(1), 'text': '已有旧稿继续可读，并明确提示本次失败；素材变化以后再标记待更新。'}]}],
             'stats': {'total_messages': payload['stats']['total'], 'unique_senders': payload['stats']['unique_senders'], 'total_chars': payload['stats']['chars']},
             'footer_quote': {**quote(36), 'attr': display(3) + ' · 17:55'}}
    if version == 'after':
        story['analysis'] = {
            'overview': {'summary': '先确认两个试点场景，再核对数据状态；读报反馈与真实运行留在下一步验证。', 'source_ids': [messages[i - 1]['message_id'] for i in [1, 13, 25, 35]]},
            'followups': [
                {'title': '读报反馈', 'summary': '许宁准备安排值班同事参与，反馈尚未收集。', 'source_ids': [messages[i - 1]['message_id'] for i in [25, 33]]},
                {'title': '真实运行', 'summary': 'Windows 兼容、模型准确性和到点执行仍待验证。', 'source_ids': [messages[34]['message_id']]},
            ],
            'topics': [
                {'title': '试点范围：先确认两个场景', 'summary': '已在群内确认以一间演示门店的前台交接、收档异常为本轮范围。暂不加入销售预测和自动排班。这里只形成了范围共识，真实试用还没有发生。', 'source_ids': [messages[i - 1]['message_id'] for i in [1, 3, 8, 11]]},
                {'title': '阅读可靠性：失败、零消息与旧稿分开', 'summary': '大家确认采集失败应明确提示，已有旧稿继续可读；不能因为本轮失败就清空旧链接。搜索需要连同前后回应一起读，避免把“处理了”误写成实际验收完成。', 'source_ids': [messages[i - 1]['message_id'] for i in [13, 17, 19, 21]]},
                {'title': '下一步：先收读报反馈，再决定更新', 'summary': '许宁准备安排值班同事读一份演示日报，产品负责汇总“漏了什么、哪句难懂、下一步做什么”。反馈尚未收集，技术兼容与实际到点执行仍待验证。', 'source_ids': [messages[i - 1]['message_id'] for i in [25, 26, 33, 35, 36]]},
            ],
            'people': [
                {'sender_id': PEOPLE[p][0], 'name': display(p), 'summary': summary,
                 'source_ids': [messages[i - 1]['message_id'] for i in refs]}
                for p, summary, refs in [
                    (0, '收窄试点范围，明确日报要保留讨论的后续回应；安排下一轮反馈问题并负责汇总。', [1, 10, 26, 34]),
                    (1, '指出失败与零消息的区别，提出旧稿保留和搜索上下文的处理方式；真实环境验证仍需继续。', [13, 17, 19, 35]),
                    (2, '说明门店交接的实际信息需求，准备脱敏样例，并认领下一轮读报反馈。', [2, 6, 25, 33]),
                ]
            ],
            'quotes': [quote(4), quote(15), quote(30)],
        }
    draft = root / 'demo-story.json'
    draft.write_text(json.dumps(story, ensure_ascii=False, indent=2))
    print(version, 'opening/story lengths:', len(opening), [len(p) for p in paragraphs])
    print(run([package / 'scripts/tools/check_story.py', draft, '--archive', archive], env).splitlines()[-1])
    run([package / 'scripts/tools/render_daily.py', draft, '--no-png', '--no-avatar'], env)
    html_path = state / 'reports' / DAY / (hashlib.sha256(GROUP.encode()).hexdigest() + '.html')
    page = html_path.read_text()
    page = page.replace('<section class="timeline">', '<section class="timeline" id="review-story">', 1)
    page = page.replace('<div class="stats">', '<div id="review-end"></div><div class="stats">', 1)
    if version == 'after':
        page = page.replace('<section><h2 class="sec-title">话题分析', '<section id="review-extra"><h2 class="sec-title">话题分析', 1)
    (HERE / 'pages').mkdir(exist_ok=True)
    (HERE / 'pages' / (version + '-report.html')).write_text('\n'.join(line.rstrip() for line in page.splitlines()) + '\n')
    # Only preview copies receive an auto-open helper; product files stay untouched.
    index_path = package / 'scripts/web/index.html'
    helper = '''<script>
const reviewMode = new URLSearchParams(location.search).get('review');
if(reviewMode){const observer=new MutationObserver(()=>{const el=document.querySelector(reviewMode==='context'?'.search-context':'.analysis-panel');if(el){el.open=true;observer.disconnect();}});observer.observe(document.documentElement,{childList:true,subtree:true});}
</script>'''
    index_path.write_text(index_path.read_text().replace('</body>', helper + '</body>'))
    return {'group': GROUP, 'day': DAY, 'messages': len(MESSAGES), 'participants': len(PEOPLE)}


if __name__ == '__main__':
    before = build('before')
    after = build('after')
    (HERE / 'sample.json').write_text(json.dumps({'synthetic': True, 'baseline_commit': BASE_COMMIT, **after}, ensure_ascii=False, indent=2))
    print('Built both reports with actual renderers; the new version uses the integrated overview-first layout.')
