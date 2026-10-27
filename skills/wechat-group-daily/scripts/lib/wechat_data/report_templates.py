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
    esc = lambda value: escape(str(value or ''), quote=True)
    by_id = {item['source_id']: item for item in analysis.sources(payload)}
    def evidence(row):
        lines = []
        for ref in row.get('source_ids') or []:
            item = by_id.get(ref)
            if item:
                lines.append(f'<li><b>{esc(item.get("sender"))}</b> · {esc(item.get("time"))}'
                             f'<p>{esc(item.get("text"))}</p><small>{esc(ref)}</small></li>')
        return '<details><summary>原文依据</summary><ul>' + ''.join(lines) + '</ul></details>'
    project = story['project']
    def section(key, title):
        rows = project.get(key) or []
        if not rows:
            return ''
        return f'<section><h2>{esc(title)}</h2>' + ''.join(
            f'<article><p>{esc(row["text"])}</p>{evidence(row)}</article>' for row in rows) + '</section>'
    tasks = []
    for row in project.get('tasks') or []:
        cells = [('任务／交付物', row['title']), ('责任人', row.get('owner') or '待确认'),
                 ('截止时间', row.get('deadline') or '待确认'), ('群内进展', row.get('progress') or '完成情况未说明'),
                 ('状态', row.get('status', '待确认'))]
        tasks.append('<tr>' + ''.join(f'<td data-label="{esc(label)}">{esc(value)}</td>' for label, value in cells)
                     + '<td data-label="依据">' + evidence(row) + '</td></tr>')
    task_html = ('<table><thead><tr>' + ''.join(f'<th>{label}</th>' for label in
                 ('任务／交付物', '责任人', '截止时间', '群内进展', '状态', '依据'))
                 + '</tr></thead><tbody>' + ''.join(tasks) + '</tbody></table>') if tasks else '<p>本时段未提取到明确布置的任务。</p>'
    from .voice_jobs import summary as voice_summary
    voices = voice_summary(payload)
    notice = (f'<p class="notice">语音转写：{voices["transcribed"]} 条成功，{voices["failed"]} 条未转写。</p>' if voices else '')
    images = sum(message.get('type') == 'image' for message in payload.get('messages', []))
    if images:
        notice += f'<p class="notice">本时段含 {images} 条图片消息，当前未完成图片理解；本报告未概括图片内容。</p>'
    attachments = sum(message.get('type') not in ('text', 'voice', 'image', 'system', 'revoke', 'call')
                      for message in payload.get('messages', []))
    if attachments:
        notice += f'<p class="notice">另有 {attachments} 条附件／卡片等非文字消息，其内容未读取，未纳入工作总结。</p>'
    span = payload.get('range') or {}
    css = '''body{margin:0;background:#f3f1ed;color:#292823;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:36px 28px}header{border-bottom:2px solid #383b36;padding-bottom:20px}h1{font-size:30px;margin:10px 0}h2{font-size:21px;margin:0 0 16px}small,.meta,.notice{color:#686b63}.meta{font-size:14px}section{background:#fff;border:1px solid #dedfd8;border-radius:8px;margin:24px 0;padding:24px}article+article{border-top:1px solid #eee;padding-top:12px}p{margin:8px 0;white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #ddd;padding:12px 8px;overflow-wrap:anywhere}th:first-child{width:24%}th:last-child{width:18%}details{font-size:13px}summary{cursor:pointer;color:#53604b}details ul{padding-left:18px}footer{font-size:13px;color:#686b63}@media(max-width:700px){main{padding:20px 14px}h1{font-size:25px}section{padding:18px}table,tbody,tr,td{display:block}thead{display:none}tr{border-bottom:2px solid #ddd;padding:8px 0}td{border:0;padding:5px 0}td:before{content:attr(data-label) "：";font-weight:600}}'''
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(story["lead_title"])}</title><style>{css}</style></head><body><main>'
            f'<header><div class="meta">项目工作版 · {esc(payload["chat"]["name"])}</div><h1>{esc(story["lead_title"])}</h1>'
            f'<div class="meta">{esc(story.get("date"))} · {esc(span.get("start"))} — {esc(span.get("end"))}</div></header>{notice}'
            + section('summary', '今日工作总结') + '<section><h2>今日布置的任务</h2>' + task_html + '</section>'
            + ''.join(section(key, title) for key, title in SECTIONS if key != 'summary')
            + '<footer>依据本群本时段可读消息整理；责任人与期限以原文为准，群内反馈不等于现场验收。未明确的信息保留待确认。</footer></main></body></html>')
