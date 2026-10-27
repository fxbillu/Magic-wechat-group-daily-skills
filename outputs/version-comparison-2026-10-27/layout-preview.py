"""Proposed overview-first layout; changes review artifacts, never product source."""
import html
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'runtime/after'
sys.path.insert(0, str(ROOT / 'skill/scripts/tools'))
sys.path.insert(0, str(ROOT / 'skill/scripts/lib'))
import render_daily


def esc(value):
    return html.escape(str(value or ''))


def main():
    sample = json.loads((HERE / 'sample.json').read_text())
    reports = list((ROOT / 'synthetic-data/reports' / sample['day']).glob('*.story.json'))
    story = json.loads(reports[0].read_text())
    archive = next((ROOT / 'synthetic-data/data' / sample['day']).glob('*.json'))
    payload = json.loads(archive.read_text())
    sources = {m['message_id']: m for m in payload['messages']}
    original = render_daily.render_html(story)
    activity = story['activity']
    topics = story.get('analysis', {}).get('topics', [])
    top = max(activity['by_hour'], key=lambda item: item['messages'])

    def evidence(refs):
        body = ''.join(f'<p><span>{esc(sources[ref]["time"][11:16])} · {esc(sources[ref]["sender"])}</span><br>{esc(sources[ref]["text"])}</p>' for ref in refs if ref in sources)
        return f'<details class="evidence"><summary>核对原文 · {len(refs)} 条</summary>{body}</details>'

    topic_rows = ''
    for index, topic in enumerate(topics[:3]):
        # This is a hand-authored review label, not inferred task state.
        status = ['范围共识', '阅读口径', '待验证'][index]
        summary = topic['summary'].split('。')[0] + '。'
        topic_rows += f'<article class="topic-brief"><div class="topic-head"><h3>{esc(topic["title"])}</h3><span class="topic-state">{status}</span></div><p>{esc(summary)}</p>{evidence(topic["source_ids"])}</article>'
    participants = ''
    for item in activity['participants'][:5]:
        participants += f'<li><div><span>{esc(item["name"])}</span><b>{item["messages"]}<small> 条 · {item["share"] * 100:.1f}%</small></b></div><meter min="0" max="1" value="{item["share"]}" aria-label="{esc(item["name"])}的发言占比">{item["share"] * 100:.1f}%</meter></li>'
    table = ''.join(f'<tr><th scope="row">{esc(p["name"])}</th><td>{p["messages"]}</td><td>{p["text_chars"]}</td><td>{p["share"] * 100:.1f}%</td></tr>' for p in activity['participants'])
    followup = f'''<section class="followup"><h2>待确认与下一步</h2>
      <p><b>读报反馈</b>许宁准备安排值班同事参与，反馈尚未收集。</p>
      <p><b>真实运行</b>Windows 兼容、模型准确性和到点执行仍待验证。</p>
      {evidence(['message_0.db:25', 'message_0.db:33', 'message_0.db:35'])}</section>'''
    overview = f'''<section class="overview" id="overview"><div class="overview-heading"><h2>今日总览</h2><span>先看发生了什么，再读完整经过</span></div>
      <div class="overview-grid"><div class="overview-topics">{topic_rows}</div><aside>
        <section class="distribution" id="activity"><h2>活跃分布</h2><p class="aside-note">{top['hour']:02d} 时讨论最多 · {top['messages']} 条</p><ul>{participants}</ul>
          <details class="activity-detail"><summary>展开完整活跃统计</summary><table><thead><tr><th>成员</th><th>消息</th><th>文字</th><th>占比</th></tr></thead><tbody>{table}</tbody></table><p>发言量仅说明讨论分布。</p></details>
        </section>{followup}</aside></div></section>'''
    hero = f'''<header class="report-head"><p class="report-meta">{esc(story['group_name'])} · {esc(story['date'])} · {esc(story['time_range'])}</p>
      <h1>{esc(story['lead_title']).replace(chr(10), '<br>')}</h1><p class="report-deck">先确认两个试点场景，再核对数据状态；读报反馈与真实运行留在下一步验证。</p>
      <dl class="overview-metrics"><div><dt>消息</dt><dd>{activity['total_messages']}<small> 条</small></dd></div><div><dt>发言人数</dt><dd>{activity['unique_senders']}<small> 人</small></dd></div><div><dt>文本量</dt><dd>{activity['text_chars']:,}<small> 字</small></dd></div><div><dt>较活跃时段</dt><dd>{top['hour']:02d}<small> 时 · {top['messages']} 条</small></dd></div></dl>
      <nav class="report-nav" aria-label="日报目录"><a href="#overview">今日总览</a><a href="#activity">活跃分布</a><a href="#story">完整故事线</a><a href="#people">人物动态</a><a href="#quotes">原文金句</a></nav></header>'''
    # Preserve the source-rendered narrative, Q&A and literal quotes.
    body = original.split('<section class="timeline">', 1)[1].split('  <div class="produced">', 1)[0]
    body = '<section class="timeline">' + body
    body = re.sub(r'<div class="sec-title">今日高光</div><div class="hl-grid">[\s\S]*?</div>\s*<div class="sec-title">问答沉淀</div>', '<div class="sec-title">问答沉淀</div>', body, count=1)
    for label in ('话题分析', '活跃统计'):
        body = re.sub(r'<section><h2 class="sec-title">' + label + r'</h2>[\s\S]*?</section>', '', body, count=1)
    body = re.sub(r'<div class="stats">[\s\S]*?</div>\s*<div class="footer">', '<div class="footer">', body, count=1)
    body = body.replace('<section><h2 class="sec-title">人物动态', '<section id="people"><h2 class="sec-title">人物动态', 1)
    body = body.replace('<section><h2 class="sec-title">原文金句', '<section id="quotes"><h2 class="sec-title">原文金句', 1)
    people_html = ''.join(f'<article class="qa"><h3 class="qa-q">{esc(row["name"])}</h3><p>{esc(row["summary"])}</p>{evidence(row["source_ids"])}</article>' for row in story['analysis']['people'])
    quotes_html = ''.join(f'<article class="qa"><blockquote>“{esc(row["text"])}”</blockquote><p class="sop-meta">{esc(row["who"])}</p>{evidence([row["source_id"]])}</article>' for row in story['analysis']['quotes'])
    body = re.sub(r'<section id="people">[\s\S]*?</section>', '<section id="people"><h2 class="sec-title">人物动态</h2>' + people_html + '</section>', body, count=1)
    body = re.sub(r'<section id="quotes">[\s\S]*?</section>', '<section id="quotes"><h2 class="sec-title">原文金句</h2>' + quotes_html + '</section>', body, count=1)
    # Technical IDs stay available through evidence in the reader, not as a visual label.
    body = re.sub(r'<p class="sop-meta">来源：[^<]*</p>', '', body)
    body = re.sub(r'( · message_\d+\.db:\d+)+', '', body)
    css = '''
    .page{width:min(1080px,100%);padding:36px 44px 44px}.masthead{padding-bottom:16px}.brand{font-size:24px}.vol{font-size:11px;letter-spacing:.06em}.report-head{padding:26px 0 0}.report-meta{font:12px/1.6 var(--font-mono);color:var(--muted);margin:0 0 14px}.report-head h1{font-family:var(--font-head);font-size:40px;line-height:1.28;font-weight:600;letter-spacing:-.025em;margin-bottom:14px}.report-deck{font-size:15px;line-height:1.8;color:var(--body-text);max-width:62ch}.overview-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:22px 0;margin-top:22px;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);gap:14px}.overview-metrics dt{font:12px/1.6 var(--font-mono);color:var(--muted);margin-bottom:6px}.overview-metrics dd{font:600 29px/1.2 var(--font-mono);font-variant-numeric:tabular-nums;color:var(--ink)}.overview-metrics dd small{font-size:12px;font-weight:400;color:var(--muted)}.report-nav{display:flex;gap:20px;flex-wrap:wrap;padding:14px 0;border-bottom:var(--mast-rule);font:12px/1.6 var(--font-mono)}.report-nav a{color:var(--accent);text-decoration:none;text-underline-offset:4px}.report-nav a:hover{text-decoration:underline}.overview{padding:28px 0 24px;border-bottom:var(--mast-rule)}.overview-heading{display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin-bottom:16px}.overview-heading h2{font:600 21px/1.4 var(--font-head)}.overview-heading span{font:11px/1.6 var(--font-mono);color:var(--muted)}.overview-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:28px}.overview-grid aside{border-left:1px solid var(--rule);padding-left:24px}.topic-brief{padding:14px 0;border-bottom:1px solid var(--rule)}.topic-brief:first-child{padding-top:0}.topic-brief:last-child{border-bottom:0}.topic-head{display:flex;gap:10px;justify-content:space-between;align-items:start}.topic-head h3{font:600 16px/1.65 var(--font-head)}.topic-state{white-space:nowrap;font:10px/1.6 var(--font-mono);color:var(--accent);padding-top:3px}.topic-brief>p{font-size:14px;line-height:1.85;color:var(--body-text);margin-top:6px}.distribution h2,.followup h2{font:600 16px/1.6 var(--font-head)}.aside-note{font:11px/1.6 var(--font-mono);color:var(--muted);margin:4px 0 14px}.distribution ul{list-style:none}.distribution li{margin:0 0 12px}.distribution li div{display:flex;gap:8px;justify-content:space-between;font:12px/1.6 var(--font-mono)}.distribution li b{white-space:nowrap;font-variant-numeric:tabular-nums;font-weight:500}.distribution li small{font-size:10px;font-weight:400;color:var(--muted)}meter{display:block;width:100%;height:5px;margin-top:5px;appearance:none;border:0;border-radius:0;background:var(--rule)}meter::-webkit-meter-bar{background:var(--rule);border:0;border-radius:0}meter::-webkit-meter-optimum-value{background:var(--accent);border-radius:0}.activity-detail{font:11px/1.7 var(--font-mono);margin-top:10px}.activity-detail table{border-collapse:collapse;width:100%;margin-top:10px}.activity-detail th,.activity-detail td{padding:5px;text-align:left;border-bottom:1px solid var(--rule);font-weight:400}.activity-detail p{margin-top:8px;color:var(--muted)}.followup{margin-top:24px;padding-top:18px;border-top:1px solid var(--rule)}.followup>p{font-size:12px;line-height:1.85;margin-top:12px;color:var(--body-text)}.followup b{display:block;font-size:12px;font-weight:600;color:var(--ink)}.evidence{font:11px/1.7 var(--font-mono);margin-top:8px}.evidence summary,.activity-detail summary{color:var(--accent);cursor:pointer}.evidence p{margin-top:10px;color:var(--body-text)}.evidence p span{color:var(--muted)}.story-intro{padding-top:30px}.story-intro h2{font:600 23px/1.5 var(--font-head);margin-bottom:12px}.story-intro>p{font-size:14px;line-height:1.9;color:var(--body-text)}.node{padding:28px 0}.sec-title{font-size:18px;letter-spacing:0;padding-top:30px}.theme{font-size:24px}.produced{margin-top:30px;letter-spacing:.05em}a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}::selection{background:#e9d1ba;color:var(--ink)}
    @media(max-width:680px){.page{padding:22px 20px 30px}.masthead{align-items:start;gap:12px}.brand{font-size:20px}.vol{font-size:10px;max-width:46%;text-align:right}.report-head h1{font-size:31px}.report-deck{font-size:14px}.overview-metrics{gap:12px;grid-template-columns:repeat(2,minmax(0,1fr));padding:18px 0}.overview-metrics dd{font-size:25px}.report-nav{gap:10px 16px}.overview-heading{display:block}.overview-heading span{display:block;margin-top:5px}.overview-grid{grid-template-columns:minmax(0,1fr);gap:20px}.overview-grid aside{border-left:0;border-top:1px solid var(--rule);padding:20px 0 0}.topic-head{display:block}.topic-state{display:inline-block;margin-top:3px}.distribution li div{font-size:13px}.theme{font-size:21px}.node .cast{row-gap:8px}.page p,.page h3{overflow-wrap:anywhere}}
    '''
    full = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>先看总览 · 日报布局预览</title><style>{render_daily.build_css('magazine')}{css}</style></head><body><main class="page"><div class="masthead"><div class="brand">Magic 群日报</div><div class="vol">布局预览 · 合成示例<br>{esc(story['date'])}</div></div>{hero}{overview}<section class="story-intro" id="story"><h2>完整故事线</h2><p>{esc(story['opening'])}</p></section>{body}<footer class="produced">全部为虚构示例 · 总览前置布局待确认 · 尚未发布</footer></main></body></html>'''
    (HERE / 'pages/after-report.html').write_text(full)
    # The actual reader preview opens this same proposed report.
    report_file = reports[0].with_name(reports[0].name.replace('.story.json', '.html'))
    report_file.write_text(full)

    app = ROOT / 'skill/scripts/web/app.js'
    script = app.read_text()
    replacement = '''const AnalysisPanel = {
      props: ["username", "date"],
      setup(props) {
        const state = reactive({ loading: false, error: "", data: null });
        async function load() { state.loading=true;state.error="";try {state.data=await getJSON("/api/analysis?"+new URLSearchParams({username:props.username,date:props.date}));}catch(e){state.error=e.message;}finally{state.loading=false;} }
        const peak=computed(()=>(state.data?.activity.by_hour||[]).filter(h=>h.messages).sort((a,b)=>b.messages-a.messages||a.hour-b.hour).slice(0,1).map(h=>String(h.hour).padStart(2,"0")+"时 · "+h.messages+"条").join(""));
        load();return {state,load,peak,num};
      },
      template: `<section class="analysis-panel overview-panel"><h2 class="overview-title">今日总览</h2>
        <p v-if="state.loading" role="status">正在读取总览…</p><div v-else-if="state.error" class="banner err">{{state.error}} <button type="button" class="btn" @click="load">重试</button></div>
        <template v-else-if="state.data">
          <p v-if="state.data.collection?.state==='failed'" class="banner err">本次采集失败，以下总览来自上次成功素材。</p>
          <div class="preview-metrics"><div><span>消息</span><b>{{num(state.data.activity.total_messages)}}<small> 条</small></b></div><div><span>发言人数</span><b>{{num(state.data.activity.unique_senders)}}<small> 人</small></b></div><div><span>文本量</span><b>{{num(state.data.activity.text_chars)}}<small> 字</small></b></div></div>
          <p class="note" v-if="peak">较活跃时段：{{peak}}。发言量不代表贡献或工作完成。</p>
          <template v-if="state.data.analysis.state==='ready'"><h3 class="preview-section-title">主要话题与下一步</h3>
            <article class="preview-topic" v-for="(row,i) in state.data.analysis.topics || []" :key="i"><h4>{{row.title}}</h4><p>{{row.summary}}</p><details class="source-evidence"><summary>核对原文 · {{row.evidence.length}} 条</summary><p v-for="m in row.evidence" :key="m.source_id"><span class="note">{{m.time}} · {{m.sender}}</span><br>{{m.text}}</p></details></article>
          </template>
          <p v-else class="note">{{state.data.analysis.state==='stale'?'素材已更新，原分析待重新生成。':state.data.analysis.state==='invalid'?'原分析未通过来源校验。':'旧稿尚无话题分析，仍可阅读已有日报。'}}</p>
          <details class="preview-activity"><summary>展开活跃统计明细</summary><table class="activity-table"><thead><tr><th>成员</th><th>消息</th><th>占比</th></tr></thead><tbody><tr v-for="p in state.data.activity.participants" :key="p.sender_id||p.name"><th>{{p.name}}</th><td>{{p.messages}}</td><td>{{(p.share*100).toFixed(1)}}%</td></tr></tbody></table><p class="note">{{state.data.activity.note}}</p></details>
          <p class="note">下方完整日报保留故事线、人物动态、原文金句与问答。</p>
        </template></section>`,
    };

    '''
    script = re.sub(r'const AnalysisPanel = \{[\s\S]*?(?=  const DetailView =)', replacement, script, count=1)
    app.write_text(script)
    css_path = ROOT / 'skill/scripts/web/app.css'
    css_path.write_text(css_path.read_text().split('/* Review-only overview-first composition. */', 1)[0] + '''
    /* Review-only overview-first composition. */
    .kv{display:none}.overview-panel{border-top:0}.overview-panel h2.overview-title{margin:0 0 14px;font-size:20px}.preview-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-top:1px solid var(--rule-strong);border-bottom:1px solid var(--rule-strong);padding:16px 0;gap:10px}.preview-metrics span{display:block;font-size:12px;color:var(--ink-body)}.preview-metrics b{display:block;font-size:26px;line-height:1.5;font-weight:600;font-variant-numeric:tabular-nums}.preview-metrics small{font-size:12px;font-weight:400;color:var(--ink-body)}.preview-section-title{margin-top:24px!important}.preview-topic{padding:14px 0;border-bottom:1px solid var(--rule)}.preview-topic h4{font-size:15px;margin:0 0 6px}.preview-topic p{font-size:14px;line-height:1.8}.preview-activity{margin:18px 0}.preview-activity summary{cursor:pointer;padding:8px 0;color:var(--brick);font-size:13px}.preview-topic .source-evidence summary{font-size:12px}
    ''')
    print('Applied proposed overview-first layout to preview copies only.')


if __name__ == '__main__':
    main()
