"""Per-group report intent, source-bound project summaries and rendering.

Presentation theme and report template are separate: detailed retains the
existing narrative; project organizes work facts without inventing ownership.
"""
from html import escape

from . import analysis

LABELS = {'detailed': '详细版', 'project': '项目工作版'}
STATUSES = ('已布置', '群内反馈已完成', '存在阻塞', '待确认')
SECTIONS = (('summary', '今日工作总结'), ('progress', '推进与交付'),
            ('risks', '阻塞与待确认'), ('next_steps', '后续节点'))


def selected(cfg, username):
    value = next((item.get('report_template', 'detailed') for item in cfg.get('chats', [])
                  if item.get('username') == username), 'detailed')
    if not isinstance(value, str) or value not in LABELS:
        raise ValueError('REPORT_TEMPLATE_INVALID')
    return value


def frozen(payload):
    value = (payload or {}).get('report_template', 'detailed')
    if not isinstance(value, str) or value not in LABELS:
        raise ValueError('REPORT_TEMPLATE_INVALID')
    return value


def configure(cfg, username, template):
    from . import settings
    if template not in LABELS:
        raise ValueError('REPORT_TEMPLATE_INVALID')
    matches = [item for item in cfg['chats'] if item.get('username') == username]
    if len(matches) != 1:
        raise ValueError('REPORT_GROUP_NOT_UNIQUE')
    matches[0]['report_template'] = template
    settings.save(cfg)
    return {'state': 'configured', 'username': username, 'report_template': template,
            'effective': 'future_archives'}


def validate(story, payload):
    """Check structure and source identity, not semantic truth of AI conclusions."""
    errors = []
    expected = frozen(payload)
    if story.get('report_template', 'detailed') != expected:
        errors.append('稿件 report_template 与冻结归档不一致')
    if expected != 'project':
        return errors
    if story.get('username') != payload.get('chat', {}).get('username'):
        errors.append('项目稿需要绑定归档 username')
    if story.get('source_revision') != payload.get('collection', {}).get('revision'):
        errors.append('项目稿 source_revision 与归档不一致')
    if 'lead_title' in story and not isinstance(story['lead_title'], str):
        errors.append('lead_title 必须为文字')
    value = story.get('project')
    if not isinstance(value, dict):
        return errors + ['项目稿需要 project 对象']
    by_id = {item['source_id']: item for item in analysis.sources(payload)
             if isinstance(item.get('text'), str) and item['text'].strip() and
             (item.get('type') == 'text' or (item.get('type') == 'voice' and
                 (item.get('voice') or {}).get('transcription', {}).get('state') == 'transcribed'))}
    for key in ('summary', 'tasks', 'progress', 'risks', 'next_steps'):
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 100:
            errors.append(f'project.{key} 必须为最多100项的数组')
            continue
        if key == 'summary' and not rows:
            errors.append('项目稿需要至少一条有来源的今日总结')
        for index, row in enumerate(rows):
            label = f'project.{key}[{index}]'
            if not isinstance(row, dict):
                errors.append(f'{label} 必须为对象')
                continue
            field = 'title' if key == 'tasks' else 'text'
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f'{label} 缺少 {field}')
            refs = row.get('source_ids')
            if (not isinstance(refs, list) or not refs or len(refs) > 30
                    or any(not isinstance(ref, str) or ref not in by_id for ref in refs)):
                errors.append(f'{label} 需要有效 source_ids')
            if key == 'tasks':
                for name in ('owner', 'deadline', 'progress'):
                    if row.get(name) is not None and not isinstance(row[name], str):
                        errors.append(f'{label}.{name} 必须为文字或 null')
                if row.get('status', '待确认') not in STATUSES:
                    errors.append(f'{label}.status 取值无效')
    return errors


def prepare_story(story, payload):
    """Shared reader cards use a short factual preview, not narrative filler."""
    value = dict(story)
    value['report_template'] = frozen(payload)
    value['group_name'] = payload['chat']['name']
    value['lead_title'] = value.get('lead_title') or f"{payload['chat']['name']} · 项目工作日报"
    summary = story['project'].get('summary') or []
    value['opening'] = '；'.join(row['text'] for row in summary[:3])
    return value


def render_html(story, payload):
    """Render the work brief in the product's existing paper-and-ink identity."""
    from datetime import datetime
    from pathlib import Path
    import re
    from .voice_jobs import summary as voice_summary

    def esc(value):
        return escape(str(value or ''), quote=True)

    def stamp(value):
        try:
            return datetime.fromisoformat(value).strftime('%Y.%m.%d %H:%M')
        except (ValueError, TypeError):
            return str(value or '')

    by_id = {item['source_id']: item for item in analysis.sources(payload)}

    def evidence(row):
        rows = [by_id[ref] for ref in row.get('source_ids') or [] if ref in by_id]
        if not rows:
            return ''
        lines = []
        for item in rows:
            voice = ' · 语音转写' if item.get('type') == 'voice' else ''
            lines.append(f'<li><div class="source-meta"><b>{esc(item.get("sender"))}</b>'
                         f'<span>{esc(stamp(item.get("time")))}{voice}</span></div>'
                         f'<p>{esc(item.get("text"))}</p><small>{esc(item["source_id"])}</small></li>')
        return (f'<details class="evidence"><summary>核对原文 · {len(rows)} 条</summary>'
                '<ol>' + ''.join(lines) + '</ol></details>')

    def deadline(value):
        if not value:
            return '<span class="unconfirmed">待确认</span>'
        # Typographic split only: retain the original deadline wording and order.
        match = re.fullmatch(r'(.+?[^\d:])\s*(\d{1,2}:\d{2}.*)', value)
        if match:
            return f'<span class="deadline-date">{esc(match[1])}</span><strong>{esc(match[2])}</strong>'
        return f'<strong class="deadline-phrase">{esc(value)}</strong>'

    def section(key, title):
        rows = project.get(key) or []
        if not rows:
            return ''
        return (f'<section class="work-section {key}" aria-labelledby="{key}-title">'
                f'<h2 id="{key}-title">{title}</h2>'
                + ''.join(f'<article><p>{esc(row["text"])}</p>{evidence(row)}</article>' for row in rows)
                + '</section>')

    project = story['project']
    tasks = project.get('tasks') or []
    status_classes = {'已布置': 'assigned', '群内反馈已完成': 'reported',
                      '存在阻塞': 'blocked', '待确认': 'unconfirmed'}
    task_rows = []
    for index, row in enumerate(tasks):
        state = row.get('status', '待确认')
        tone = status_classes.get(state, 'unconfirmed')
        owner = esc(row.get('owner')) if row.get('owner') else '<span class="unconfirmed">待确认</span>'
        progress = (esc(row['progress']) if row.get('progress') else
                    '<span class="unconfirmed">完成情况未说明</span>')
        task_rows.append(
            f'<tr class="task-row {tone}" id="task-{index}">'
            f'<th scope="row"><h3>{esc(row["title"])}</h3>{evidence(row)}</th>'
            f'<td class="task-deadline">{deadline(row.get("deadline"))}</td>'
            f'<td class="task-owner">{owner}</td>'
            f'<td class="task-state"><span class="status {tone}">{esc(state)}</span></td>'
            f'<td class="task-progress">{progress}</td></tr>')
    if task_rows:
        task_html = ('<div class="task-table-wrap"><table class="task-table">'
                     '<caption class="sr-only">本时段提取的任务、原文期限、责任人与群内进展</caption>'
                     '<colgroup><col class="task-col"><col class="due-col"><col class="owner-col">'
                     '<col class="state-col"><col class="progress-col"></colgroup><thead><tr>'
                     '<th scope="col">任务／交付物</th><th scope="col">原文截止时间</th>'
                     '<th scope="col">责任人</th><th scope="col">群内状态</th>'
                     '<th scope="col">进展与阻塞</th></tr></thead><tbody>'
                     + ''.join(task_rows) + '</tbody></table></div>')
    else:
        task_html = '<p class="empty-state">本时段未提取到明确布置的任务，可展开工作总览的原文核对。</p>'

    active = [(index, row) for index, row in enumerate(tasks)
              if row.get('status') != '群内反馈已完成']
    dated = [(index, row) for index, row in active if row.get('deadline')]
    unknown = sum(not row.get('deadline') for _, row in active)
    schedule = ''.join(
        f'<li><a href="#task-{index}"><div class="schedule-deadline">{deadline(row["deadline"])}</div>'
        f'<div class="schedule-task">{esc(row["title"])}<span>{esc(row.get("owner") or "责任人待确认")}</span></div></a></li>'
        for index, row in dated[:3])
    if schedule:
        schedule = '<ul class="deadline-list">' + schedule + '</ul>'
        if len(dated) > 3:
            schedule += f'<p class="schedule-note">其余 {len(dated) - 3} 项期限见下方任务清单。</p>'
    elif active:
        schedule = '<p class="schedule-empty">待推进任务的期限尚未明确。</p>'
    elif tasks:
        schedule = '<p class="schedule-empty">本轮任务均已有群内完成反馈，仍需结合实际情况核对。</p>'
    else:
        schedule = '<p class="schedule-empty">本时段没有明确任务期限。</p>'
    if unknown:
        schedule += f'<p class="schedule-note">另有 {unknown} 项任务的期限待确认。</p>'
    schedule += '<a class="schedule-link" href="#tasks">查看任务与责任人</a>'
    summary = ''.join(f'<article><p>{esc(row["text"])}</p>{evidence(row)}</article>'
                      for row in project.get('summary') or [])
    counts = []
    for state in ('已布置', '存在阻塞', '待确认', '群内反馈已完成'):
        count = sum(row.get('status', '待确认') == state for row in tasks)
        if count:
            counts.append(f'<span class="{status_classes[state]}">{esc(state)} <b>{count}</b> 项</span>')
    status_line = '<div class="status-line">' + ''.join(counts) + '</div>' if counts else ''

    notices = []
    voices = voice_summary(payload)
    if voices:
        notices.append(f'语音 {voices["transcribed"]} 条已转写，{voices["failed"]} 条未转写；识别文字请结合原文核对。')
    images = sum(message.get('type') == 'image' for message in payload.get('messages', []))
    if images:
        notices.append(f'{images} 条图片消息尚未完成图片理解，图片内容未纳入总结。')
    attachments = sum(message.get('type') not in ('text', 'voice', 'image', 'system', 'revoke', 'call')
                      for message in payload.get('messages', []))
    if attachments:
        notices.append(f'{attachments} 条附件／卡片等非文字消息的内容尚未读取，未纳入总结。')
    notice = ('<aside class="coverage" aria-label="内容覆盖范围"><h2>内容覆盖说明</h2>'
              + ''.join(f'<p>{esc(text)}</p>' for text in notices) + '</aside>') if notices else ''
    span = payload.get('range') or {}
    period = f'{stamp(span.get("start"))} — {stamp(span.get("end"))}'
    try:
        offset = datetime.fromisoformat(span['end']).strftime('%z')
        zone = f'UTC{offset[:3]}:{offset[3:]}' if offset else '未标注时区'
    except (ValueError, TypeError, KeyError):
        zone = '未标注时区'
    css = (Path(__file__).resolve().parents[2] / 'assets/project-report.css').read_text(encoding='utf-8')
    project_details = (section('progress', '推进与交付') + section('risks', '阻塞与待确认')
                       + section('next_steps', '后续节点'))
    details_html = (f'<div class="project-details" id="project-details">{project_details}</div>'
                    if project_details else '')
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{esc(story["lead_title"])}</title><style>{css}</style></head><body>'
        '<a class="skip-link" href="#tasks">跳到任务清单</a><main class="work-report">'
        '<header class="masthead"><div class="brand">Magic 群日报</div>'
        f'<div class="edition"><span>{esc(payload["chat"]["name"])}</span>'
        f'<span>项目工作版 · <time>{esc(story.get("date"))}</time></span></div></header>'
        '<div class="report-overview"><section class="work-overview" aria-labelledby="report-title">'
        f'<h1 id="report-title">{esc(story["lead_title"])}</h1>'
        f'<div class="period">统计范围：{esc(period)}<span>{esc(zone)} · 不含截止时刻</span></div>'
        f'<div class="overview-copy"><h2>今日工作总览</h2>{summary}</div></section>'
        '<aside class="schedule" aria-labelledby="schedule-title"><h2 id="schedule-title">任务截止安排</h2>'
        '<p class="schedule-caption">按原文记录 · 不含已反馈完成的任务</p>'
        f'{schedule}</aside></div>'
        '<section class="tasks" id="tasks" aria-labelledby="tasks-title">'
        f'<div class="section-heading"><h2 id="tasks-title">任务与责任清单</h2>'
        f'<p>本时段提取 {len(tasks)} 项任务</p></div>{status_line}{task_html}</section>'
        f'{details_html}{notice}<footer><p>依据本群本时段可读消息整理；责任人与期限以原文为准。</p>'
        '<p>群内完成反馈不等于现场验收，未明确的信息保留待确认。</p></footer></main></body></html>')
