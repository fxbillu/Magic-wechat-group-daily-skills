"""Overview-first report composition from measured activity and validated sources."""
from html import escape


def esc(value):
    return escape(str(value or ''))


def evidence(row):
    messages = row.get('evidence') or []
    if not messages:
        return ''
    body = ''.join(f'<p><span>{esc(m.get("time"))} · {esc(m.get("sender"))}</span><br>{esc(m.get("text"))}</p>' for m in messages)
    return f'<details class="evidence"><summary>核对原文 · {len(messages)} 条</summary>{body}</details>'


def topic(row):
    label = f'<span class="topic-state">{esc(row["label"])}</span>' if row.get('label') else ''
    return f'<article class="topic-brief"><div class="topic-head"><h3>{esc(row.get("title"))}</h3>{label}</div><p>{esc(row.get("summary"))}</p>{evidence(row)}</article>'


def render_front(story, content, activity):
    participants = activity.get('participants') or []
    hourly = activity.get('by_hour') or []
    peak = max(hourly, key=lambda item: item['messages']) if hourly else None
    peak = peak if peak and peak['messages'] else None
    stats = story.get('stats') or {}
    values = [(activity.get('total_messages', stats.get('total_messages')), '消息', '条'),
              (activity.get('unique_senders', stats.get('unique_senders')), '发言人数', '人'),
              (activity.get('text_chars', stats.get('total_chars')), '文本量', '字')]
    metrics = ''.join(f'<div><dt>{label}</dt><dd>{value:,}<small> {unit}</small></dd></div>'
                      for value, label, unit in values if isinstance(value, (int, float)))
    metrics += f'<div><dt>较活跃时段</dt><dd>{peak["hour"]:02d}<small> 时 · {peak["messages"]} 条</small></dd></div>' if peak else ''
    metrics = f'<dl class="overview-metrics">{metrics}</dl>' if metrics else ''
    topics = content.get('topics') or []
    followups = content.get('followups') or []
    summary = (content.get('overview') or {}).get('summary')
    opening = story.get('opening') or summary
    intro = f'<p class="opening">{esc(opening)}</p>' if opening else ''
    nav = []
    if topics or participants or followups:
        nav.append(('overview', '今日总览'))
    if participants:
        nav.append(('activity', '活跃分布'))
    nav.append(('story', '完整故事线'))
    if content.get('people'):
        nav.append(('people', '人物动态'))
    if content.get('quotes'):
        nav.append(('quotes', '原文金句'))
    links = ''.join(f'<a href="#{key}">{label}</a>' for key, label in nav)
    hero = f'<header class="report-head lead"><div class="eyebrow">Today&#x27;s Story · 今日故事</div><h1 class="title">{esc(story.get("lead_title")).replace(chr(10), "<br>")}</h1>{intro}</header>{metrics}<nav class="report-nav" aria-label="日报目录">{links}</nav>'
    topic_rows = ''.join(topic(row) for row in topics[:3])
    if len(topics) > 3:
        topic_rows += f'<details class="more-topics"><summary>更多话题 · {len(topics) - 3} 条</summary>{"".join(topic(row) for row in topics[3:])}</details>'
    distribution = ''
    if participants:
        bars = ''.join(f'<li><div><span>{esc(p["name"])}</span><b>{p["messages"]}<small> 条 · {p["share"] * 100:.1f}%</small></b></div><meter min="0" max="1" value="{p["share"]}" aria-label="{esc(p["name"])}的发言占比">{p["share"] * 100:.1f}%</meter></li>' for p in participants[:5])
        rows = ''.join(f'<tr><th scope="row">{esc(p["name"])}<small class="member-id">{esc(p.get("sender_id"))}</small></th><td>{p["messages"]}</td><td>{p["text_chars"]}</td><td>{p["share"] * 100:.1f}%</td></tr>' for p in participants)
        peak_text = f'<p class="aside-note">{peak["hour"]:02d} 时讨论最多 · {peak["messages"]} 条</p>' if peak else ''
        distribution = f'<section class="distribution" id="activity"><h2>活跃分布</h2>{peak_text}<ul>{bars}</ul><details class="activity-detail"><summary>展开完整活跃统计</summary><table><thead><tr><th scope="col">成员</th><th scope="col">消息</th><th scope="col">文字</th><th scope="col">占比</th></tr></thead><tbody>{rows}</tbody></table><p>{esc(activity.get("note"))}</p></details></section>'
    followup_html = ''
    if followups:
        followup_html = '<section class="followup"><h2>待确认与下一步</h2>' + ''.join(f'<article><p><b>{esc(row.get("title"))}</b>{esc(row.get("summary"))}</p>{evidence(row)}</article>' for row in followups) + '</section>'
    overview = ''
    if topic_rows or distribution or followup_html:
        if topic_rows and (distribution or followup_html):
            body = f'<div class="overview-grid"><div class="overview-topics">{topic_rows}</div><aside>{distribution}{followup_html}</aside></div>'
        else:
            body = f'<div class="overview-single">{topic_rows}{distribution}{followup_html}</div>'
        overview = f'<section class="overview" id="overview"><div class="overview-heading"><h2>今日总览</h2><span>先看发生了什么，再读完整经过</span></div>{body}</section>'
    return hero + overview


def render_details(content):
    result = ''
    for key, title in (('people', '人物动态'), ('quotes', '原文金句')):
        rows = ''
        for row in content.get(key) or []:
            if key == 'people':
                rows += f'<article class="qa"><h3 class="qa-q">{esc(row.get("name"))}</h3><p>{esc(row.get("summary"))}</p>{evidence(row)}</article>'
            else:
                rows += f'<article class="qa"><blockquote>“{esc(row.get("text"))}”</blockquote><p class="sop-meta">{esc(row.get("who"))}</p>{evidence(row)}</article>'
        if rows:
            result += f'<section id="{key}"><h2 class="sec-title">{title}</h2>{rows}</section>'
    return result
