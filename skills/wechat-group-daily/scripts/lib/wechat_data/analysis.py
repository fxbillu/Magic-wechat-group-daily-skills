"""Read-only analysis of frozen material; semantic conclusions remain host-authored."""
from collections import Counter
from datetime import datetime
import hashlib
import json


def sources(payload):
    """Expose stable source IDs, including deterministic IDs for legacy archives."""
    result = []
    for index, message in enumerate(payload.get('messages') or []):
        source_id = message.get('message_id')
        if not source_id and message.get('source_shard') and 'local_id' in message:
            source_id = f"{message['source_shard']}:{message['local_id']}"
        if not source_id:
            digest = hashlib.sha256(json.dumps(message, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            source_id = f'legacy:{index}:{digest}'
        result.append({**message, 'source_id': source_id})
    return result


def search_key(row):
    """A content-bound anchor, not a SQLite rowid that changes after reindexing."""
    values = [row.get('date'), row.get('username'), row.get('local_id'),
              row.get('ts'), row.get('sender_uid') or '', (row.get('text') or '')[:4000]]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def context(payload, date, key, before=8, after=12):
    messages = sources(payload)
    matches = []
    for index, message in enumerate(messages):
        try:
            timestamp = int(datetime.fromisoformat(message.get('time', '')).timestamp())
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        row = {'date': date, 'username': payload['chat']['username'],
               'local_id': message.get('local_id', 0), 'ts': timestamp,
               'sender_uid': message.get('sender_id'), 'text': message.get('text')}
        if search_key(row) == key:
            matches.append(index)
    if len(matches) != 1:
        return None
    index = matches[0]
    start, end = max(0, index - before), min(len(messages), index + after + 1)
    return {'anchor_id': messages[index]['source_id'],
            'source_revision': (payload.get('collection') or {}).get('revision'),
            'scope': 'archive_range' if payload.get('period_mode') == 'rolling' else 'group_day',
            'range': payload.get('range'), 'before_available': index,
            'after_available': len(messages) - index - 1,
            'has_earlier': start > 0, 'has_later': end < len(messages),
            'messages': [{**m, 'is_match': start + i == index}
                         for i, m in enumerate(messages[start:end])]}


def activity(payload):
    messages = sources(payload)
    people, names, chars, hours = Counter(), {}, Counter(), Counter()
    for message in messages:
        identity = message.get('sender_id') or 'name:' + (message.get('sender') or '未知')
        names[identity] = message.get('sender') or '未知'
        people[identity] += 1
        if message.get('type') == 'text':
            chars[identity] += len(message.get('text') or '')
        try:
            hours[datetime.fromisoformat(message.get('time', '')).hour] += 1
        except (ValueError, TypeError):
            pass
    total = len(messages)
    return {'total_messages': total, 'unique_senders': len(people),
            'text_chars': sum(chars.values()),
            'participants': [{'sender_id': identity if not identity.startswith('name:') else None,
                              'name': names[identity], 'messages': count,
                              'text_chars': chars[identity],
                              'share': round(count / total, 4) if total else 0}
                             for identity, count in sorted(people.items(), key=lambda item: (-item[1], item[0]))],
            'by_hour': [{'hour': hour, 'messages': hours[hour]} for hour in range(24)],
            'note': '仅统计本群本次归档消息；发言量不代表贡献或工作完成。'}


def material(payload, *, person='', topic='', before=8, after=12, limit=200):
    """Keyword/person seeds with merged context; no automatic semantic labeling."""
    messages = sources(payload)
    hits = [i for i, m in enumerate(messages)
            if (not topic or topic.casefold() in (m.get('text') or '').casefold())
            and (not person or person == m.get('sender_id') or
                 person.casefold() in (m.get('sender') or '').casefold())]
    selected = hits[:limit]
    ranges = []
    for index in selected:
        lo, hi = max(0, index - before), min(len(messages), index + after + 1)
        if ranges and lo <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], hi)
        else:
            ranges.append([lo, hi])
    chosen = set(selected)
    return {'chat': payload['chat'], 'source_revision': (payload.get('collection') or {}).get('revision'),
            'collection': payload.get('collection'), 'activity': activity(payload),
            'query': {'person': person, 'topic': topic}, 'match_count': len(hits),
            'truncated': len(hits) > len(selected),
            'scope': 'archive_range' if payload.get('period_mode') == 'rolling' else 'group_day',
            'range': payload.get('range'),
            'windows': [{'messages': [{**messages[i], 'is_match': i in chosen} for i in range(lo, hi)],
                         'has_earlier': lo > 0, 'has_later': hi < len(messages)} for lo, hi in ranges]}


def validate(value, payload):
    """Check source binding, not the semantic truth of a model's interpretation."""
    if not isinstance(value, dict):
        return ['analysis 必须是对象']
    errors = []
    by_id = {}
    for m in sources(payload):
        by_id.setdefault(m['source_id'], []).append(m)
    for kind in ('topics', 'people', 'quotes', 'followups', 'overview'):
        rows = ([value[kind]] if kind in value else []) if kind == 'overview' else value.get(kind, [])
        if not isinstance(rows, list) or len(rows) > 20:
            errors.append(f'analysis.{kind} 必须为最多 20 项的数组')
            continue
        for index, row in enumerate(rows):
            label = f'analysis.{kind}[{index}]'
            if not isinstance(row, dict):
                errors.append(f'{label} 必须为对象')
                continue
            if kind == 'quotes':
                ref = row.get('source_id')
                matches = (by_id.get(ref) or []) if isinstance(ref, str) else []
                if len(matches) != 1 or not row.get('text') or not any(
                        row.get('text') == m.get('text') and row.get('who') == m.get('sender')
                        and (not row.get('sender_id') or row['sender_id'] == m.get('sender_id')) for m in matches):
                    errors.append(f'{label} 金句原话、署名和 source_id 须匹配同一条源消息')
                continue
            refs = row.get('source_ids')
            if not isinstance(refs, list) or not refs or any(
                    not isinstance(ref, str) or len(by_id.get(ref, [])) != 1 for ref in refs):
                errors.append(f'{label} 需要唯一有效的 source_ids')
                continue
            if not isinstance(row.get('summary'), str) or not row['summary'].strip():
                errors.append(f'{label} 缺少 summary')
            if kind in ('topics', 'followups') and (not isinstance(row.get('title'), str) or not row['title'].strip()):
                errors.append(f'{label} 缺少 title')
            if 'label' in row and (not isinstance(row['label'], str) or len(row['label']) > 12):
                errors.append(f'{label} label 须为最多 12 字的文字')
            if kind == 'people':
                identity = row.get('sender_id')
                own = [m for ref in refs for m in by_id[ref] if identity and m.get('sender_id') == identity]
                if not own or not row.get('name') or not all(
                        m.get('sender_id') == identity and m.get('sender') == row['name']
                        for ref in refs for m in by_id[ref]):
                    errors.append(f'{label} 人物姓名、sender_id 和本人发言来源须一致')
    return errors


def saved(cfg, entry, payload):
    """Read validated optional analysis from the existing report's story sidecar."""
    from pathlib import Path
    from . import settings
    state = 'pending'
    value = {}
    rel = entry.get('report_html') if entry else None
    root = Path(settings.reports_dir(cfg)).resolve()
    target = (root / rel).with_suffix('.story.json').resolve() if rel else None
    if target is not None and root in target.parents and target.is_file():
        try:
            story = json.loads(target.read_text(encoding='utf-8'))
            if 'analysis' in story:
                same = (story.get('username') == payload['chat']['username'] and
                        story.get('date') == entry['date'] and
                        story.get('source_revision') == (payload.get('collection') or {}).get('revision'))
                state = 'ready' if same and not validate(story['analysis'], payload) else 'stale' if not same else 'invalid'
                if state == 'ready':
                    value = story['analysis']
        except (OSError, ValueError, TypeError, AttributeError):
            state = 'invalid'
    return {'state': state, **with_evidence(value, payload)}


def with_evidence(value, payload):
    """Project validated semantic fields onto actual archive rows for all readers."""
    result = {}
    by_id = {m['source_id']: m for m in sources(payload)}
    for kind in ('topics', 'people', 'quotes', 'followups', 'overview'):
        result[kind] = []
        rows = ([value[kind]] if kind in value else []) if kind == 'overview' else value.get(kind, [])
        for row in rows:
            refs = [row['source_id']] if kind == 'quotes' else row['source_ids']
            evidence = [{key: by_id[ref].get(key) for key in ('source_id', 'time', 'sender', 'text')}
                        for ref in refs if ref in by_id]
            result[kind].append({**row, 'evidence': evidence})
    result['overview'] = result['overview'][0] if result['overview'] else None
    return result
