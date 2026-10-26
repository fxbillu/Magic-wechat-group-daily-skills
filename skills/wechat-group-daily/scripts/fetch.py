#!/usr/bin/env python3
"""微信聊天记录获取 CLI

把「取哪个群/人、哪一天」这件事做成一条命令，输出交给下游任意消费。

用法：
    # 看有哪些群（按最近消息排序）
    python fetch.py list --kind group --active

    # 搜会话
    python fetch.py search "示例群"

    # 导某群某天的记录
    python fetch.py export --chat "示例群" --date 2026-10-24
    python fetch.py export --chat "张三" --start 2026-10-20 --end 2026-10-24 --format json

    # 只看统计，不出内容
    python fetch.py stat --chat "示例群" --date 2026-10-24

    # 一次导出多个群
    python fetch.py export --chats "群A,群B" --date 2026-10-24 --outdir out

输出目录默认 out/，文件名 <会话名>_<日期>.<ext>
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from wechat_data import (AmbiguousChat, ChatResolver, MessageReader,  # noqa: E402
                         config, render)
from wechat_data import parse_range  # noqa: E402
from wechat_data import material  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))


def _safe(name: str) -> str:
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "chat"


def cmd_list(args):
    resolver = ChatResolver(args.db_dir)
    pools = []
    if args.kind in (None, "group"):
        pools += resolver.groups()
    if args.kind in (None, "friend"):
        pools += resolver.friends()
    if args.kind == "all" or args.kind is None:
        seen = {c.username for c in pools}
        pools += [c for c in resolver.all() if c.username not in seen]

    if args.active:
        with MessageReader(args.db_dir) as r:
            rows = []
            for c in pools:
                if not r.has_messages(c):
                    continue
                last = r.last_message_time(c)
                if last:
                    rows.append((last, c))
        rows.sort(key=lambda x: x[0], reverse=True)
        rows = rows[: args.limit]
        print(f"{'最后消息':<18}{'会话':<40}用户名")
        for last, c in rows:
            print(f"{last:%Y-%m-%d %H:%M}    {c.name:<40}{c.username}")
    else:
        for c in pools[: args.limit]:
            print(c)


def cmd_search(args):
    resolver = ChatResolver(args.db_dir)
    hits = resolver.search(args.keyword, kind=args.kind)
    if not hits:
        print(f"没有匹配「{args.keyword}」的会话")
        return 1
    print(f"匹配 {len(hits)} 个：")
    for c in hits[:20]:
        print(f"  {c}")
    return 0


def _write(chat, msgs, stats, start, end, fmt, out_path):
    text = render.render(fmt, chat, msgs, stats, start, end)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


def cmd_export(args):
    resolver = ChatResolver(args.db_dir)
    start, end = parse_range(args.date, args.start, args.end)
    targets = [t.strip() for t in (args.chats or args.chat or "").split(",") if t.strip()]
    if not targets:
        print("请用 --chat 指定一个会话，或 --chats 指定多个（逗号分隔）")
        return 1

    outdir = args.outdir or os.path.join(ROOT, "out")
    ext = {"text": "txt", "txt": "txt", "json": "json", "md": "md", "markdown": "md"}
    tag = args.date or (f"{args.start}_{args.end}" if args.end else args.start
                        or datetime.now().strftime("%Y-%m-%d"))

    ok = 0
    with MessageReader(args.db_dir) as reader:
        for kw in targets:
            try:
                chat = resolver.resolve(kw, kind=args.kind)
            except LookupError as e:
                print(f"[跳过] {e}")
                continue
            msgs = reader.fetch(chat, start, end, limit=args.limit)
            stats = reader.summarize(msgs)
            if not msgs:
                print(f"[空] {chat.name} 在该时间段没有消息")
                continue
            out = os.path.join(outdir, f"{_safe(chat.name)}_{tag}.{ext.get(args.format, 'txt')}")
            _write(chat, msgs, stats, start, end, args.format, out)
            print(f"[OK] {chat.name}: {stats.total} 条 / {stats.unique_senders} 人 / "
                  f"约 {stats.chars} 字 -> {out}")
            ok += 1
    return 0 if ok else 2


def cmd_stat(args):
    _, msgs, stats, start, end = _fetch_one(args)
    if not msgs:
        print("该时间段没有消息")
        return 2
    print(f"消息 {stats.total} 条，文本 {stats.text_count} 条，约 {stats.chars} 字")
    print(f"发言 {stats.unique_senders} 人")
    print("\n类型分布：")
    for k, v in sorted(stats.types.items(), key=lambda x: -x[1]):
        print(f"  {k:<12}{v}")
    print("\n发言排行：")
    for name, n in sorted(stats.senders.items(), key=lambda x: -x[1])[:15]:
        print(f"  {name:<20}{n}")
    return 0


def _date_list(args):
    from datetime import date as _d
    from datetime import timedelta
    if getattr(args, "date", None):
        return [args.date]
    if getattr(args, "days", None):
        d0 = _d.today() - timedelta(days=1)
        return [(d0 - timedelta(days=i)).isoformat() for i in range(args.days)]
    if getattr(args, "start", None):
        s = datetime.strptime(args.start, "%Y-%m-%d").date()
        e = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else s
        out, cur = [], s
        while cur <= e:
            out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out
    return [(_d.today() - timedelta(days=1)).isoformat()]


def cmd_archive(args):
    """采集并落盘到归档层——这是采集与日报解耦的关键"""
    from wechat_data import ChatResolver, MessageReader, archive as ar, parse_range
    from wechat_data import settings as st

    cfg = st.require()
    if args.config:
        chats = [c["name"] for c in (cfg.get("chats") or []) if c.get("daily", True)]
        if not chats:
            print("[错误] 配置里没有监控群，请先运行 tools/setup.py", file=sys.stderr)
            return 1
    else:
        chats = [x.strip() for x in (args.chats or "").split(",") if x.strip()]
    if not chats:
        print("[错误] 用 --config 或 --chats 指定要采集的群", file=sys.stderr)
        return 1

    dates = _date_list(args)
    data_root = cfg["paths"]["data"]
    resolver = ChatResolver(args.db_dir)
    saved = 0

    with MessageReader(args.db_dir) as reader:
        for date in dates:
            s, e = parse_range(date=date)
            for kw in chats:
                try:
                    chat = resolver.resolve(kw, kind="group")
                except LookupError as ex:
                    print(f"[跳过] {kw}: {ex}", file=sys.stderr)
                    continue
                msgs = reader.fetch(chat, s, e)
                if not msgs:
                    print(f"[空] {date}  {chat.name}")
                    continue
                stats = reader.summarize(msgs)
                p = ar.save(cfg, date, chat, msgs, stats, s, e)
                saved += 1
                print(f"[归档] {date}  {chat.name}  {stats.total} 条 / "
                      f"{stats.unique_senders} 人 -> {os.path.relpath(p, data_root)}")

    print(f"\n完成：{saved} 份归档" + (f"，目录 {data_root}" if saved else ""))
    return 0 if saved else 2


def cmd_status(args):
    """一眼看清：配置、归档、数据新鲜度"""
    from wechat_data import archive as ar, guard
    from wechat_data import settings as st

    cfg = st.require()
    print("=" * 56)
    print(st.summary(cfg))
    print("-" * 56)
    print(ar.summary(cfg))
    d = st.decrypted_dir(cfg)
    if os.path.isdir(d):
        r = guard.check(d, 24)
        mark = "OK" if r["fresh"] else "⚠"
        print(f"数据新鲜度  {mark}  {r['reason']}")
    else:
        print(f"数据新鲜度  ⚠  解密目录不存在: {d}")
    print("=" * 56)
    return 0


def cmd_reindex(args):
    """从磁盘 json 全量重建索引（index.db 是可删的派生索引）"""
    from wechat_data import db
    from wechat_data import settings as st

    cfg = st.require()
    r = db.rebuild(cfg, verbose=args.verbose)
    p = db.dump_json(cfg)
    print(f"重建完成：{r['entries']} 份归档 / {r['messages']} 条消息"
          + (f"，{r['broken']} 个文件损坏已跳过" if r["broken"] else ""))
    print(f"索引    {db.db_path(cfg)}")
    print(f"导出    {p}")
    return 0


def cmd_views(args):
    """不开服务，用文本预览三个视图（验证查询逻辑）"""
    from wechat_data import browse, db
    from wechat_data import settings as st

    cfg = st.require()
    b = browse(cfg)
    o = b["overview"]
    print("=" * 60)
    print(f"归档  {o['days']} 天（{o['first_date']} ~ {o['last_date']}）"
          f" / {o['chats']} 个会话 / {o['entries']} 份 / {o['msgs']} 条"
          f" / {o['reports']} 份日报")

    print("-" * 60)
    today = b["today"]["chats"]
    need = sum(1 for c in today if c["state"] in ("ready", "pending"))
    empty = sum(1 for c in today if c["state"] == "empty")
    tail = f" · {empty} 个群素材不足，不出报" if empty else ""
    print(f"[当日总览] {b['today']['date']}  "
          f"{b['today']['total']} 条 · 需出 {need} 份，"
          f"已出 {b['today']['reports']} 份{tail}")
    for c in today:
        mark = {"ready": "✓", "pending": "·", "missing": "-",
                "orphan": "!", "empty": "◦"}[c["state"]]
        title = (c.get("title") or "").replace("\n", " ")[:26]
        if c["state"] == "empty":
            enough, why = material.sufficient(c["total"], c["chars"],
                                              c["unique_senders"])
            title = f"素材不足：{why}"
        print(f"  {mark} {c['chat'][:20]:<22}{c['total']:>5}条  "
              f"{c['state']:<8}{title}")

    print("-" * 60)
    print("[全景矩阵] 最近 14 天")
    m = b["matrix"]
    print("             " + " ".join(d[5:] for d in m["dates"]))
    for row in m["rows"]:
        cells = " ".join(f"{c['total']:>4}" if c["total"] else "   ·"
                         for c in row["cells"])
        print(f"  {row['chat'][:11]:<12}{cells}")

    print("-" * 60)
    print("[群时间线] 示例")
    for c in b["chats"][:3]:
        t = db.by_chat(cfg, c["username"], 5)
        print(f"  {c['chat'][:20]}  均 {t['avg']} 条/天 · 最近 {t['last_date']}")
        for e in t["entries"]:
            print(f"     {e['date']}  {e['total']:>4}条  {e['state']}")
    return 0


def _fetch_one(args):
    from wechat_data import fetch as _fetch
    return _fetch(args.chat, date=args.date, start=args.start, end=args.end,
                  kind=args.kind, db_dir=args.db_dir, limit=args.limit)


def _check_freshness(db_dir: str, max_age: float, allow_stale: bool,
                     action: str, target_date: str | None = None) -> int | None:
    """统一的新鲜度闸门

    `export` / `stat` / `archive` 都要过这一关——它们读的都是 `decrypted/` 这份**快照**，
    快照过期就意味着日报会拿几天前的聊天记录写成"今天的日报"，而且看起来完全正常。
    增量采集（archive）尤其不能例外：它是出报主链路的第一步，漏了这一关，后面三步全在
    错误的数据上跑，退出码却一路是 0。

    `target_date` 是要出的那一天。给了历史日期，闸门改问"这份快照盖不盖得住那天"
    （解密时刻晚于该日结束即可），而不是"解密后有没有被写过"——每天只解一次密、
    全天反复补昨天日报的用法，靠的就是这条。

    返回 None 表示放行；返回 5 表示已拦下，调用方直接 return。
    """
    from wechat_data import guard

    try:
        guard.assert_fresh(db_dir, max_age, target_date=target_date)
        return None
    except guard.StaleDataError as e:
        # 显式要求用旧数据（补历史日报）时只警告，不中断
        if allow_stale:
            print(f"[数据新鲜度] ⚠ {e}（已按 --allow-stale 放行）", flush=True)
            return None
        print(f"[数据新鲜度] ⚠ {e}", flush=True)
        print(f"[中断] {action}已停止：数据不新鲜。"
              f"确需使用旧数据请显式加 --allow-stale", file=sys.stderr)
        return 5
    except FileNotFoundError:
        return None          # 目录不存在交给下游报错，这里不抢它的错误


def main():
    ap = argparse.ArgumentParser(description="微信聊天记录获取")
    ap.add_argument("--db-dir", help="解密后的数据库目录（默认 decrypted/）")
    ap.add_argument("--max-age-hours", type=float, default=None,
                    help="数据超过多少小时算过期（默认 24）")
    ap.add_argument("--allow-stale", action="store_true",
                    help="允许使用过期数据（仍然会警告）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出会话")
    p.add_argument("--kind", choices=["group", "friend", "all"])
    p.add_argument("--active", action="store_true", help="按最后消息时间排序，只列有消息的")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="按关键词搜会话")
    p.add_argument("keyword")
    p.add_argument("--kind", choices=["group", "friend"])
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("archive", help="采集并归档（给日报用）")
    p.add_argument("--config", action="store_true", help="按 config.json 里配置的群采集")
    p.add_argument("--chats", help="指定群，逗号分隔")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--days", type=int, help="最近 N 天（不含今天）")
    p.add_argument("--start")
    p.add_argument("--end")
    # 与 export/stat 同样的两个开关，写在子命令后面也认
    p.add_argument("--max-age-hours", type=float, default=argparse.SUPPRESS)
    p.add_argument("--allow-stale", action="store_true", default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("status", help="查看配置与归档状态")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("reindex", help="从磁盘重建索引 index.db（可随时重跑）")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_reindex)

    p = sub.add_parser("views", help="文本预览浏览层三个视图")
    p.set_defaults(func=cmd_views)

    for name, fn, helptext in (
        ("export", cmd_export, "导出聊天记录"),
        ("stat", cmd_stat, "只看统计"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--chat", help="会话名（群名/昵称/wxid）")
        p.add_argument("--chats", help="多个会话，逗号分隔（仅 export）")
        p.add_argument("--date", help="YYYY-MM-DD")
        p.add_argument("--start", help="起始日期 YYYY-MM-DD")
        p.add_argument("--end", help="结束日期 YYYY-MM-DD（含当天）")
        p.add_argument("--kind", choices=["group", "friend"])
        p.add_argument("--limit", type=int, default=None, help="最多取最近 N 条")
        p.add_argument("--format", default="text", choices=["text", "json", "md"])
        p.add_argument("--outdir", default=None)
        # 用 SUPPRESS 避免子命令默认值覆盖主 parser 上已解析的同名参数
        p.add_argument("--max-age-hours", type=float, default=argparse.SUPPRESS)
        p.add_argument("--allow-stale", action="store_true", default=argparse.SUPPRESS)
        p.set_defaults(func=fn)

    args = ap.parse_args()

    # 新鲜度闸门：宁可停下，也不拿过期数据算出一份"看起来正常"的日报。
    # archive 必须在列——它是出报主链路的第一步，漏了它等于整条链都没有保护。
    if args.cmd in ("export", "stat", "archive"):
        try:
            from wechat_data import config as cfgmod
            max_age = args.max_age_hours if args.max_age_hours else 24.0
            action = {"archive": "采集归档", "export": "导出", "stat": "统计"}[args.cmd]
            # 要出的那一天：archive 与命令行实际会处理的日期保持一致
            if args.cmd == "archive":
                try:
                    target = max(_date_list(args))
                except (ValueError, TypeError):
                    target = getattr(args, "date", None)
            else:
                target = args.date or args.start or args.end
            code = _check_freshness(cfgmod.db_dir(args.db_dir), max_age,
                                    args.allow_stale, action, target)
            if code:
                return code
        except FileNotFoundError:
            pass  # 目录不存在交给下游报错

    try:
        return args.func(args) or 0
    except AmbiguousChat as e:
        print(e, file=sys.stderr)
        return 3
    except FileNotFoundError as e:
        print(f"[错误] {e}", file=sys.stderr)
        print("提示：先运行 tools/wcdb_key_tool_windows.py extract + decrypt", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
