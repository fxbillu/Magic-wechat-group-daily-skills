"""微信数据获取层

把「取哪个群/人、哪段时间的聊天记录」这类需求收敛成一个稳定的接口，
与下游的日报生成、检索、分析彻底解耦。

前置条件：数据库已解密到某个目录（默认项目下 decrypted/），
解密由 tools/wcdb_key_tool_windows.py 负责，本层只读。

典型用法：

    from wechat_data import fetch, ChatResolver

    # 一行拿数据
    chat, msgs, stats, start, end = fetch("示例群", date="2026-10-24")

    # 或者分步控制
    resolver = ChatResolver()
    chat = resolver.resolve("示例群", kind="group")
    with MessageReader() as reader:
        msgs = reader.fetch(chat, start, end)

    # 浏览已归档的日报（走派生索引，毫秒级）
    b = browse()
    b["today"]    # 当日总览
    b["chats"]    # 群列表 + 画像
    b["matrix"]   # 全景矩阵

分层：

    采集  fetch() / MessageReader   读解密库，产出消息
    归档  archive.save()            落盘 data/<date>/<chat>.json
    索引  db.save_archive()         写 data/index.db（派生，可 rebuild）
    浏览  browse() / db.by_day()    两个轴切同一份数据
"""
from .chat import AmbiguousChat, Chat, ChatResolver
from .messages import FetchStats, Message, MessageReader
from . import archive, config, content, db, guard, render, settings, voice


def parse_range(date=None, start=None, end=None):
    """把 date / start-end 统一成 (datetime, datetime) 半开区间"""
    from datetime import datetime, timedelta

    def _d(s):
        return datetime.strptime(s, "%Y-%m-%d")

    if date:
        s = _d(date)
        return s, s + timedelta(days=1)
    if start:
        s = _d(start)
        e = _d(end) + timedelta(days=1) if end else s + timedelta(days=1)
        return s, e
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today, today + timedelta(days=1)


def fetch(chat, date=None, start=None, end=None, kind=None,
          db_dir=None, limit=None, reader: MessageReader | None = None):
    """取一个会话在某段时间的消息

    返回 (Chat, list[Message], FetchStats, start, end)
    """
    resolver = ChatResolver(db_dir)
    target = resolver.resolve(chat, kind=kind) if isinstance(chat, str) else chat
    s, e = parse_range(date, start, end)

    own = reader is None
    r = reader or MessageReader(db_dir)
    try:
        msgs = r.fetch(target, s, e, limit=limit)
        stats = r.summarize(msgs)
    finally:
        if own:
            r.close()
    return target, msgs, stats, s, e


def browse(cfg: dict | None = None) -> dict:
    """浏览层入口：一次拿到三个视图需要的全部数据

    读的是派生索引（data/index.db），不碰原始库。
    """
    from datetime import date as _date
    cfg = cfg or settings.load()
    days = archive.list_days(cfg)
    today = days[0] if days else _date.today().isoformat()
    return {
        "overview": db.overview(cfg),
        "today": db.by_day(cfg, today),
        "chats": db.list_chats(cfg),
        "matrix": db.matrix(cfg, 14),
        "days": days,
    }


__all__ = [
    "Chat", "ChatResolver", "AmbiguousChat",
    "Message", "MessageReader", "FetchStats",
    "fetch", "parse_range", "browse",
    "archive", "config", "content", "db", "guard", "render", "settings", "voice",
]
