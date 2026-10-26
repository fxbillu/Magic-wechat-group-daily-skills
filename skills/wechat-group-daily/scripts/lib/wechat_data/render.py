"""输出渲染：把消息列表转换成不同形态

设计原则：数据层产出的结构是唯一真相，渲染只是视图。
- text  : 给人和 AI 读，一行一条，信息密度最高
- json  : 给程序读，含完整元数据
- markdown : 带层级，便于人工浏览
"""
import json
from datetime import datetime

from .chat import Chat
from .messages import FetchStats, Message


def _header(chat: Chat, stats: FetchStats, start: datetime, end: datetime) -> str:
    from datetime import timedelta
    last = end - timedelta(seconds=1)   # 半开区间，展示时回退一秒
    span = start.strftime("%Y-%m-%d") if start.date() == last.date() else \
        f"{start:%Y-%m-%d} ~ {last:%Y-%m-%d}"
    types = ", ".join(f"{k} {v}" for k, v in
                      sorted(stats.types.items(), key=lambda x: -x[1])[:6])
    return (
        f"# {chat.name} ({chat.username})\n"
        f"# {span} | 共 {stats.total} 条 | {stats.unique_senders} 人发言 | 约 {stats.chars} 字\n"
        f"# 类型: {types}\n"
    )


def to_text(chat: Chat, msgs: list[Message], stats: FetchStats,
            start: datetime, end: datetime, show_date: bool = False) -> str:
    lines = [_header(chat, stats, start, end), "#" + "-" * 60]
    for m in msgs:
        t = m.ts_str[5:16] if not show_date else m.ts_str
        lines.append(f"[{t}] {m.sender}: {m.text}")
    return "\n".join(lines) + "\n"


def to_json(chat: Chat, msgs: list[Message], stats: FetchStats,
            start: datetime, end: datetime) -> str:
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
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_markdown(chat: Chat, msgs: list[Message], stats: FetchStats,
                start: datetime, end: datetime) -> str:
    lines = [
        f"## {chat.name}",
        "",
        f"- 会话：`{chat.username}`（{'群' if chat.is_group else '私聊'}）",
        f"- 区间：{start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M}",
        f"- 规模：{stats.total} 条 / {stats.unique_senders} 人 / 约 {stats.chars} 字",
        "",
        "### 发言排行",
        "",
    ]
    for name, n in sorted(stats.senders.items(), key=lambda x: -x[1])[:10]:
        lines.append(f"- {name}: {n}")
    lines += ["", "### 记录", ""]
    cur = None
    for m in msgs:
        if m.ts.hour != cur:
            cur = m.ts.hour
            lines.append(f"\n**{m.ts:%H}:00**\n")
        lines.append(f"- `{m.ts:%H:%M}` **{m.sender}**：{m.text}")
    return "\n".join(lines) + "\n"


RENDERERS = {
    "text": to_text,
    "txt": to_text,
    "json": to_json,
    "md": to_markdown,
    "markdown": to_markdown,
}


def render(fmt: str, *args, **kwargs) -> str:
    fn = RENDERERS.get(fmt)
    if not fn:
        raise ValueError(f"不支持的格式: {fmt}（可选 {', '.join(RENDERERS)}）")
    return fn(*args, **kwargs)
