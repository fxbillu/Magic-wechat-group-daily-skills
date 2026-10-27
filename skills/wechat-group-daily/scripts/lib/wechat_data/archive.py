"""归档层：采集与呈现之间的唯一中间产物

没有它，"采集和日报不同步"只是一句口号——日报只能即时消费采集结果，
采集挂了就什么都出不来，也没法补生成、没法换模型重新提炼。

结构（按「日期 × 群」组织，一个群一份日报）：

    data/
      2026-10-24/
        <群ID的sha256>.json  ← 该群当天的结构化消息
        <另一个群ID的sha256>.json
      index.json                        ← 索引：日期 → 群 → 文件
      state.json                        ← 增量游标、最近运行状态

单个归档文件的结构与 `render.to_json` 完全一致，因此归档可以直接喂给渲染层。
"""
import hashlib
import json
import os
import tempfile
import time

from . import collection, db, settings

INDEX_NAME = "index.json"
STATE_NAME = "state.json"


def safe_name(s: str) -> str:
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    s = s.strip().strip(".")
    return s[:80] or "chat"


def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(path))
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def day_dir(cfg: dict, date: str) -> str:
    return os.path.join(settings.data_dir(cfg), date)


def archive_path(cfg: dict, date: str, username: str) -> str:
    stem = hashlib.sha256(username.encode("utf-8")).hexdigest()
    return os.path.join(day_dir(cfg, date), stem + ".json")


# ---------------------------------------------------------------- 单日归档

def save(cfg: dict, date: str, chat, msgs, stats, start, end, *, period_mode=None) -> str:
    """写入一个群某天的归档，并更新索引与状态"""
    payload = {
        "chat": {
            "username": chat.username,
            "name": chat.name,
            "kind": chat.kind,
            "is_group": chat.is_group,
        },
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "stats": {
            "total": stats.total,
            "text": stats.text_count,
            "chars": stats.chars,
            "unique_senders": stats.unique_senders,
            "senders": dict(sorted(stats.senders.items(), key=lambda x: -x[1])),
            "types": stats.types,
        },
        "messages": [m.to_dict() for m in msgs],
        "archived_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    from .report_templates import selected
    payload['report_template'] = selected(cfg, chat.username)
    if period_mode:
        payload['period_mode'] = period_mode
    _, _, span = collection.day_range(cfg, start, end)
    payload['collection'] = {
        'state': 'collected' if msgs else 'empty', 'revision': collection.revision(payload),
        'message_count': len(msgs), 'observed_at': collection.now(),
        'range': span, 'coverage': {'complete': True, 'issues': []},
    }
    path = archive_path(cfg, date, chat.username)
    _atomic_write(path, payload)
    _atomic_write(collection.record_path(cfg, 'collections', date, chat.username),
                  {'date': date, 'chat': payload['chat'], 'collection': payload['collection']})
    rel = os.path.relpath(path, settings.data_dir(cfg)).replace("\\", "/")
    db.save_archive(cfg, date, payload, rel)
    db.dump_json(cfg)
    cursor = read_state(cfg)
    cursor.setdefault("collect", {})[f"{date}|{chat.username}"] = payload["archived_at"]
    write_state(cfg, cursor)
    return path


def revise_material(cfg: dict, date: str, payload: dict) -> None:
    """Persist a recoverable text revision without a new collection attempt."""
    previous = payload['collection']['revision']
    current = collection.revision(payload)
    payload['collection'] = dict(payload['collection'], revision=current)
    payload['voice_revision'] = {'pending': True, 'previous_revision': previous, 'revision': current}
    _atomic_write(archive_path(cfg, date, payload['chat']['username']), payload)
    resume_voice_revision(cfg, date, payload)


def resume_voice_revision(cfg: dict, date: str, payload: dict) -> bool:
    """Idempotently finish an interrupted JSON → index → pending-state revision."""
    marker = payload.get('voice_revision') or {}
    if marker.get('pending') is not True:
        return False
    successful = payload.get('collection') or {}
    current = marker.get('revision')
    if current != successful.get('revision') or current != collection.revision(payload):
        raise ValueError('VOICE_REVISION_INVALID')
    username = payload['chat']['username']
    attempt_path = collection.record_path(cfg, 'collections', date, username)
    attempt = collection.read_record(attempt_path)
    latest = attempt.get('collection') or {}
    if (latest.get('state') != 'failed'
            and latest.get('revision') in (marker.get('previous_revision'), current)
            and latest.get('observed_at') == successful.get('observed_at')
            and latest.get('range') == successful.get('range')):
        attempt['collection'] = dict(latest, revision=current)
        _atomic_write(attempt_path, attempt)
    # Preserve actual coverage, failures, collection timestamps and collect cursors.
    path = archive_path(cfg, date, username)
    rel = os.path.relpath(path, settings.data_dir(cfg)).replace('\\', '/')
    db.save_archive(cfg, date, payload, rel)
    db.dump_json(cfg)
    from . import daily
    daily.revise_material(cfg, date, username, payload)
    payload['voice_revision'] = dict(marker, pending=False)
    _atomic_write(path, payload)
    return True


def sources_of_day(cfg, date):
    sources = []
    directory = day_dir(cfg, date)
    if not os.path.isdir(directory):
        return sources
    for name in sorted(os.listdir(directory)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding='utf-8') as source:
                payload = json.load(source)
            if not isinstance(payload, dict) or not isinstance(payload.get('chat'), dict):
                raise ValueError('Invalid archive')
            sources.append((path, payload))
        except (ValueError, OSError):
            sources.append((path, None))
    return sources


def choose_source(cfg, date, username, candidates):
    """Canonical ID file wins; disagreeing legacy copies need an explicit choice."""
    canonical = archive_path(cfg, date, username)
    for path, payload in candidates:
        if path == canonical:
            return path, payload
    if not candidates:
        return None
    first = candidates[0][1]
    if all(payload == first for _, payload in candidates):
        return candidates[0]
    return None


def load(cfg: dict, date: str, identity: str) -> dict | None:
    canonical = archive_path(cfg, date, identity)
    if os.path.isfile(canonical):
        try:
            with open(canonical, encoding='utf-8') as source:
                payload = json.load(source)
            if payload.get('chat', {}).get('username') == identity:
                return payload
        except (ValueError, AttributeError, OSError):
            return None
    sources = [(path, payload) for path, payload in sources_of_day(cfg, date) if payload]
    by_id = [(path, payload) for path, payload in sources
             if payload['chat'].get('username') == identity]
    if by_id:
        chosen = choose_source(cfg, date, identity, by_id)
        return chosen[1] if chosen else None
    matches = [payload for _, payload in sources if payload['chat'].get('name') == identity]
    return matches[0] if len(matches) == 1 else None


def has(cfg: dict, date: str, identity: str) -> bool:
    return load(cfg, date, identity) is not None


def list_days(cfg: dict) -> list:
    """已归档的日期，倒序"""
    root = settings.data_dir(cfg)
    if not os.path.isdir(root):
        return []
    days = []
    for name in os.listdir(root):
        if len(name) == 10 and name[4] == "-" and os.path.isdir(os.path.join(root, name)):
            days.append(name)
    return sorted(days, reverse=True)


def list_chats_of_day(cfg: dict, date: str) -> list:
    d = day_dir(cfg, date)
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))


# ---------------------------------------------------------------- 索引

def index_path(cfg: dict) -> str:
    return os.path.join(settings.data_dir(cfg), INDEX_NAME)


def read_index(cfg: dict) -> dict:
    """索引内容（兼容旧接口）

    真正的索引在 index.db；这里把 entry 表按旧格式吐出来，
    让仍在用 `read_index()` 的代码不必改。
    """
    if not db.exists(cfg):
        return {"updated_at": "", "entries": []}
    entries = []
    for e in db._query_entries(cfg):
        entries.append({
            "date": e["date"],
            "chat": e["chat"],
            "username": e["username"],
            "file": e["data_file"],
            "total": e["total"],
            "chars": e["chars"],
            "unique_senders": e["unique_senders"],
            "archived_at": e["archived_at"],
        })
    return {"updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "entries": entries}


def update_index(cfg: dict, date: str, chat, payload: dict, path: str) -> dict:
    """[兼容] 写入索引。实际由 db.save_archive 完成，不再整文件读写。"""
    rel = os.path.relpath(path, settings.data_dir(cfg)).replace("\\", "/")
    db.save_archive(cfg, date, payload, rel)
    return read_index(cfg)


def rebuild_index(cfg: dict) -> dict:
    """按磁盘实际文件全量重建索引（索引损坏或手工删文件后修复）"""
    r = db.rebuild(cfg)
    db.dump_json(cfg)
    return {"updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "entries": read_index(cfg)["entries"], **r}


# ---------------------------------------------------------------- 状态 / 游标

def state_path(cfg: dict) -> str:
    return os.path.join(settings.data_dir(cfg), STATE_NAME)


def read_state(cfg: dict) -> dict:
    p = state_path(cfg)
    if not os.path.exists(p):
        return {"collect": {}, "compose": {}, "cursor": {}}
    try:
        st = json.load(open(p, encoding="utf-8"))
        st.setdefault("collect", {})
        st.setdefault("compose", {})
        st.setdefault("cursor", {})
        return st
    except (json.JSONDecodeError, OSError):
        return {"collect": {}, "compose": {}, "cursor": {}}


def write_state(cfg: dict, state: dict) -> None:
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _atomic_write(state_path(cfg), state)


def last_collect_of(cfg: dict, date: str, username: str):
    return read_state(cfg).get("collect", {}).get(f"{date}|{username}")


def cleanup(cfg: dict, keep_days: int | None = None) -> list:
    """清理超过保留期的归档目录"""
    keep = keep_days if keep_days is not None else (cfg.get("retention", {}) or {}).get("data_days", 30)
    if not keep or keep <= 0:
        return []
    import datetime
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep)).isoformat()
    removed = []
    root = settings.data_dir(cfg)
    for date in list_days(cfg):
        if date < cutoff:
            d = day_dir(cfg, date)
            import shutil
            try:
                shutil.rmtree(d)
                removed.append(date)
            except OSError:
                pass
    if removed:
        rebuild_index(cfg)
    return removed


def summary(cfg: dict) -> str:
    if not db.exists(cfg):
        days = list_days(cfg)
        if not days:
            return "归档目录为空"
        return (f"已归档 {len(days)} 天（{days[-1]} ~ {days[0]}），索引未建立，"
                f"运行 `python fetch.py reindex` 重建")
    o = db.overview(cfg)
    if not o.get("entries"):
        return "归档目录为空"
    return (f"已归档 {o['days']} 天（{o['first_date']} ~ {o['last_date']}），"
            f"{o['chats']} 个会话，{o['entries']} 份，{o['msgs']} 条消息，"
            f"其中 {o['reports']} 份已出日报")
