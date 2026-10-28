"""SQLite 派生索引：双轴查询、三态状态、消息检索

## 定位（最重要的一条）

    data/<date>/<群ID的sha256>.json   ← 真相源（产物，可读、可搬、可 git-ignore）
    data/index.db             ← 派生索引（可随时 rebuild，删了不丢数据）

DB 不是主存储。任何时候删掉 `index.db`，跑一次 `rebuild()` 就从 json 全量恢复。
这样既拿到 SQL 的查询能力，又不破坏「文件即归档」的可移植性。

## 为什么用 username 做主键

群会改名（`群名` 只是属性），`username`（xxx@chatroom）才是稳定标识。
归档与报告路径均使用群 ID 的散列；旧名称文件只按其自带的 username 重建。
同一身份的冲突旧副本保留原文件，等待用户明确选择。

## 为什么不存完整消息体

完整消息（含 app 详情、URL、封面）留在 json 里。DB 只存可检索、可筛选的字段，
体积约为完整数据的 1/5。真要拿详情，按 (date, username) 回读 json。

## 为什么不用 FTS5

中文分词需要 ICU 或 trigram（trigram 要求查询 ≥3 字，"日报" 这种两字词搜不到）。
一年 9 万条消息用 `LIKE '%kw%'` 全扫也就几十毫秒，比维护一张需要触发器的
外部内容表划算。等数据上百万条再换。
"""
import json
import os
from pathlib import Path
import sqlite3
import time

from . import settings
from . import material

DB_NAME = "index.db"
SCHEMA_VERSION = 1

# Runtime-only token: a JSON configuration cannot opt into or out of this mode.
_READ_ONLY_ACCESS = object()


def readonly_config(cfg: dict) -> dict:
    """Create a request-local config that cannot initialize or migrate an index."""
    return dict(cfg, _reader_access=_READ_ONLY_ACCESS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS entry (
    date            TEXT    NOT NULL,
    username        TEXT    NOT NULL,
    chat            TEXT    NOT NULL,
    kind            TEXT    NOT NULL DEFAULT 'group',
    total           INTEGER NOT NULL DEFAULT 0,
    chars           INTEGER NOT NULL DEFAULT 0,
    unique_senders  INTEGER NOT NULL DEFAULT 0,
    data_file       TEXT    NOT NULL DEFAULT '',
    report_html     TEXT,
    report_png      TEXT,
    title           TEXT,
    lead            TEXT,
    cast_json       TEXT,
    archived_at     TEXT,
    composed_at     TEXT,
    PRIMARY KEY (date, username)
);
CREATE INDEX IF NOT EXISTS ix_entry_chat ON entry(username, date);
CREATE INDEX IF NOT EXISTS ix_entry_date ON entry(date, chat);

CREATE TABLE IF NOT EXISTS message (
    date        TEXT    NOT NULL,
    username    TEXT    NOT NULL,
    local_id    INTEGER NOT NULL,
    ts          INTEGER NOT NULL,
    sender      TEXT    NOT NULL,
    sender_uid  TEXT,
    type        TEXT    NOT NULL,
    sub         INTEGER NOT NULL DEFAULT 0,
    text        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_msg_date_chat ON message(date, username);
CREATE INDEX IF NOT EXISTS ix_msg_chat_ts   ON message(username, ts);
CREATE INDEX IF NOT EXISTS ix_msg_sender    ON message(username, sender);
CREATE INDEX IF NOT EXISTS ix_msg_ts        ON message(ts);
"""


# ---------------------------------------------------------------- 连接

def db_path(cfg: dict) -> str:
    return os.path.join(settings.data_dir(cfg), DB_NAME)


def connect(cfg: dict, retries: int = 6) -> sqlite3.Connection:
    """打开索引库并确保结构就绪

    Windows 下 WAL 有个坑：多个连接同时执行 `PRAGMA journal_mode=WAL`
    会报 `attempt to write a readonly database`（SQLite 拿不到独占锁时
    会退化成只读）。所以这里分开处理——先读当前模式，已经是 wal 就不再切换；
    切换失败也只是降级成默认 journal，不影响正确性。连接本身带重试。
    """
    if cfg.get("_reader_access") is _READ_ONLY_ACCESS:
        return connect_readonly(cfg)
    p = db_path(cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    last: Exception | None = None
    for i in range(retries):
        cn = None
        try:
            cn = sqlite3.connect(p, timeout=20)
            cn.row_factory = sqlite3.Row
            cn.execute("PRAGMA busy_timeout=20000")
            mode = str(cn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if mode != "wal":
                try:
                    cn.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError:
                    pass
            cn.execute("PRAGMA synchronous=NORMAL")
            _ensure_schema(cn)
            return cn
        except sqlite3.OperationalError as e:
            last = e
            if cn is not None:
                try:
                    cn.close()
                except sqlite3.Error:
                    pass
            time.sleep(0.05 * (i + 1))
    raise last or sqlite3.OperationalError("无法打开索引库")


def connect_readonly(cfg: dict) -> sqlite3.Connection:
    """Read the live SQLite database, including its WAL, without schema repair.

    SQLite may use WAL/SHM coordination sidecars. Do not use immutable=1 here:
    doing so would ignore committed records still present in the live WAL.
    """
    uri = Path(db_path(cfg)).resolve().as_uri() + "?mode=ro"
    cn = sqlite3.connect(uri, uri=True, timeout=1)
    cn.row_factory = sqlite3.Row
    try:
        if cn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise sqlite3.DatabaseError("Unsupported reader schema version")
        for table, required in (("entry", ENTRY_COLS), ("message", MSG_COLS)):
            columns = {row[1] for row in cn.execute(f"PRAGMA table_info({table})")}
            if not set(required).issubset(columns):
                raise sqlite3.DatabaseError("Incomplete reader schema")
        return cn
    except Exception:
        cn.close()
        raise


def _write(cfg: dict, fn, retries: int = 6):
    """在一个事务里执行写操作；锁冲突则换连接重试

    旧的 index.json 实现是「读全文件 → 改 → 全写回」，两个归档进程并行时
    后写的会覆盖先写的，条目静默丢失。事务 + 重试把这个问题彻底消掉。
    """
    last: Exception | None = None
    for i in range(retries):
        cn = connect(cfg)
        try:
            with cn:
                return fn(cn)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if not any(k in msg for k in ("locked", "busy", "readonly")):
                raise
            last = e
            time.sleep(0.05 * (i + 1))
        finally:
            try:
                cn.close()
            except sqlite3.Error:
                pass
    raise last or sqlite3.OperationalError("索引写入重试耗尽")


def _ensure_schema(cn: sqlite3.Connection) -> None:
    ver = cn.execute("PRAGMA user_version").fetchone()[0]
    if ver == SCHEMA_VERSION:
        return
    cn.executescript(SCHEMA)
    cn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    cn.commit()


def exists(cfg: dict) -> bool:
    return os.path.exists(db_path(cfg))


# ---------------------------------------------------------------- 写入

ENTRY_COLS = ("date", "username", "chat", "kind", "total", "chars",
              "unique_senders", "data_file", "report_html", "report_png",
              "title", "lead", "cast_json", "archived_at", "composed_at")

MSG_COLS = ("date", "username", "local_id", "ts", "sender",
            "sender_uid", "type", "sub", "text")


def _ts_of(s: str) -> int:
    try:
        return int(time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S")))
    except (ValueError, TypeError):
        return 0


def save_archive(cfg: dict, date: str, payload: dict, data_file: str) -> None:
    """写入一份归档的索引：entry 更新 + 消息全量替换，同一事务

    这里是修掉旧实现隐患的地方。原来的 `update_index()` 是
    「读整个 index.json → 改 → 整个写回」，两个归档进程并行时会丢条目，
    而且不报错。现在用 UPSERT + 事务，并发写是安全的。
    """
    chat = payload.get("chat", {})
    stats = payload.get("stats", {})
    username = chat.get("username", "")
    if not username:
        raise ValueError("归档缺少 username，拒绝写入索引")

    row = {
        "date": date,
        "username": username,
        "chat": chat.get("name", username),
        "kind": chat.get("kind", "group"),
        "total": stats.get("total", 0),
        "chars": stats.get("chars", 0),
        "unique_senders": stats.get("unique_senders", 0),
        "data_file": data_file,
        "archived_at": payload.get("archived_at", ""),
    }

    msgs = []
    for m in payload.get("messages", []):
        msgs.append((
            date, username, m.get("local_id", 0),
            _ts_of(m.get("time", "")),
            m.get("sender", ""), m.get("sender_id", ""),
            m.get("type", ""), m.get("sub_type", 0),
            (m.get("text") or "")[:4000],
        ))

    def _do(cn):
        cn.execute(
            f"INSERT INTO entry ({','.join(ENTRY_COLS)}) "
            f"VALUES ({','.join('?' * len(ENTRY_COLS))}) "
            "ON CONFLICT(date, username) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in ENTRY_COLS
                       if c in row and c not in ("date", "username")),
            tuple(row.get(c) for c in ENTRY_COLS),
        )
        # 消息做全量替换：归档本身就是这一天这一群的全集
        cn.execute("DELETE FROM message WHERE date=? AND username=?",
                   (date, username))
        if msgs:
            cn.executemany(
                f"INSERT INTO message ({','.join(MSG_COLS)}) "
                f"VALUES ({','.join('?' * len(MSG_COLS))})", msgs)

    _write(cfg, _do)


def find_username(cfg: dict, date: str, chat: str) -> str | None:
    """按 日期 + 群名 反查 username

    story.json 里只有 group_name 没有 username，渲染层要用它登记产物。
    仅允许稳定 ID 或唯一精确名称；同名和模糊名称必须由用户选择。
    """
    if not chat:
        return None
    cn = connect(cfg)
    try:
        rows = cn.execute('SELECT username FROM entry WHERE date=? AND (username=? OR chat=?)',
                          (date, chat, chat)).fetchall()
        return rows[0]['username'] if len(rows) == 1 else None
    finally:
        cn.close()


def set_report(cfg: dict, date: str, username: str = "", html: str = "",
               png: str = "", story: dict | None = None,
               chat: str = "") -> bool:
    """登记日报产物。story 非空时顺带抽取标题/首句/出场人物

    username 为空时按 (date, chat) 或 story 里的 group_name 反查；
    查不到就返回 False，由调用方决定警告还是中断——不静默成功。
    """
    username = username or (story or {}).get("username", "")
    if not username:
        username = find_username(
            cfg, date, chat or (story or {}).get("group_name", ""))
    if not username:
        return False
    sets, vals = [], []
    if html:
        sets.append("report_html=?")
        vals.append(html)
    if png:
        sets.append("report_png=?")
        vals.append(png)
    if story:
        s = story.get("cover") or story
        raw_title = story.get("lead_title") or story.get("title") or s.get("title") or ""
        # 索引里的标题是列表标签，压成单行；带换行的原版留在 story.json
        title = " ".join(str(raw_title).split())
        lead = " ".join(str(story.get("opening") or story.get("lead") or "").split())[:200]
        cast = story.get("cast")
        if not cast:
            cast = [h.get("name", "") for h in (story.get("highlights") or [])
                    if isinstance(h, dict) and h.get("name")]
        sets.append("title=?")
        vals.append(title)
        sets.append("lead=?")
        vals.append(lead)
        sets.append("cast_json=?")
        vals.append(json.dumps(cast, ensure_ascii=False) if cast else None)
    if not sets:
        return False
    sets.append("composed_at=?")
    vals.append(time.strftime("%Y-%m-%d %H:%M:%S"))
    vals.extend([date, username])
    sql = f"UPDATE entry SET {','.join(sets)} WHERE date=? AND username=?"
    updated = bool(_write(cfg, lambda cn: cn.execute(sql, tuple(vals)).rowcount > 0))
    if updated:
        from . import archive, collection
        entry = get_entry(cfg, date, username)
        record = {key: entry.get(key) for key in
                  ('report_html', 'report_png', 'title', 'lead', 'cast', 'composed_at')}
        record['source_revision'] = (story or {}).get('source_revision') or entry['collection']['revision']
        record['report_template'] = (story or {}).get('report_template', 'detailed')
        record['composed_at'] = collection.now()
        archive._atomic_write(collection.record_path(cfg, 'report-records', date, username), record)
    return updated


def rebuild(cfg: dict, verbose: bool = False) -> dict:
    """按磁盘上的 json 归档全量重建索引

    索引损坏、手工删过文件、换电脑只搬了 json —— 都靠这个恢复。
    """
    root = settings.data_dir(cfg)
    n = nm = bad = 0
    cn = connect(cfg)
    try:
        with cn:
            cn.execute("DELETE FROM entry")
            cn.execute("DELETE FROM message")
        for date in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            d = os.path.join(root, date)
            if not (len(date) == 10 and date[4] == "-" and os.path.isdir(d)):
                continue
            from . import archive
            groups = {}
            for path, payload in archive.sources_of_day(cfg, date):
                username = (payload or {}).get('chat', {}).get('username')
                if not isinstance(username, str) or not username:
                    bad += 1
                    continue
                groups.setdefault(username, []).append((path, payload))
            for username, candidates in groups.items():
                chosen = archive.choose_source(cfg, date, username, candidates)
                if not chosen:
                    bad += len(candidates)
                    continue
                path, payload = chosen
                rel = os.path.relpath(path, root).replace('\\', '/')
                try:
                    save_archive(cfg, date, payload, rel)
                    n += 1
                    nm += len(payload.get('messages', []))
                except (ValueError, sqlite3.Error):
                    bad += 1
                if verbose:
                    print(f'  + {rel}')
        # Failed first attempts have no material JSON, but remain historical facts.
        from . import collection
        attempts = Path(root) / 'collections'
        for path in sorted(attempts.glob('*/*.json')):
            record = collection.read_record(path)
            chat = record.get('chat') or {}
            date, username = record.get('date'), chat.get('username')
            if date and username and record.get('collection', {}).get('state') == 'failed':
                with cn:
                    cn.execute('INSERT INTO entry(date,username,chat,kind) VALUES(?,?,?,?) '
                               'ON CONFLICT(date,username) DO NOTHING',
                               (date, username, chat.get('name') or username, 'group'))
        # 产物登记：磁盘上已有的 html/png 补回 entry（rebuild 会清空这两列）
        _relink_reports(cfg, cn)
    finally:
        cn.close()
    return {"entries": n, "messages": nm, "broken": bad}


def _relink_reports(cfg: dict, cn: sqlite3.Connection) -> None:
    """重建索引时把磁盘上已有的产物挂回 entry

    约定：`reports/<date>/<群名>.html|.png` 是日报本体，
    `reports/<date>/<群名>.story.json` 是它的叙事源。后者必须一起落盘，
    否则 rebuild 之后标题/首句/人物会全丢——那些字段只存在 DB 里。
    """
    from . import collection
    for row in cn.execute('SELECT date,username FROM entry').fetchall():
        record = collection.read_record(collection.record_path(
            cfg, 'report-records', row['date'], row['username']))
        if record:
            with cn:
                cn.execute('UPDATE entry SET report_html=?,report_png=?,title=?,lead=?,cast_json=?,composed_at=? '
                           'WHERE date=? AND username=?',
                           (record.get('report_html'), record.get('report_png'), record.get('title'),
                            record.get('lead'), json.dumps(record.get('cast') or []), record.get('composed_at'),
                            row['date'], row['username']))
    rep = settings.reports_dir(cfg)
    if not os.path.isdir(rep):
        return
    for date in os.listdir(rep):
        d = os.path.join(rep, date)
        if not (len(date) == 10 and date[4] == "-" and os.path.isdir(d)):
            continue
        for fn in sorted(os.listdir(d)):
            stem, ext = os.path.splitext(fn)
            full = os.path.join(d, fn)
            if ext in (".html", ".png"):
                col = "report_html" if ext == ".html" else "report_png"
                with cn:
                    cn.execute(
                        f"UPDATE entry SET {col}=? WHERE date=? AND chat=? AND {col} IS NULL "
                        "AND (SELECT COUNT(*) FROM entry WHERE date=? AND chat=?)=1",
                        (f"{date}/{fn}", date, stem, date, stem))
            elif fn.endswith(".story.json"):
                base = fn[:-len(".story.json")]
                try:
                    with open(full, encoding="utf-8") as f:
                        story = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                title = " ".join(str(story.get("lead_title") or "").split())
                lead = " ".join(str(story.get("opening") or "").split())[:200]
                cast = [h.get("name", "") for h in (story.get("highlights") or [])
                        if isinstance(h, dict) and h.get("name")]
                ts = time.strftime("%Y-%m-%d %H:%M:%S",
                                   time.localtime(os.path.getmtime(full)))
                with cn:
                    cn.execute(
                        "UPDATE entry SET title=?, lead=?, cast_json=?, composed_at=? "
                        "WHERE date=? AND chat=? AND composed_at IS NULL "
                        "AND (SELECT COUNT(*) FROM entry WHERE date=? AND chat=?)=1",
                        (title, lead,
                         json.dumps(cast, ensure_ascii=False) if cast else None,
                         ts, date, base, date, base))


def dump_json(cfg: dict) -> str:
    """把索引导出成 index.json（人看的，不做权威源）

    保留它有两个用处：出问题时直接 cat 一眼看清；以及给不装 sqlite 的
    工具链留个后路。
    """
    rows = _query_entries(cfg)
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "authoritative": False,
        "note": "此文件由 index.db 导出，请勿手工编辑；真正的索引在 index.db",
        "entries": rows,
    }
    p = os.path.join(settings.data_dir(cfg), "index.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


# ---------------------------------------------------------------- 读：两个轴

def _query_entries(cfg: dict, where: str = "", args: tuple = (),
                   order: str = "date DESC, chat") -> list:
    cn = connect(cfg)
    try:
        cur = cn.execute(
            f"SELECT * FROM entry {('WHERE ' + where) if where else ''} "
            f"ORDER BY {order}", args)
        return [_entry_row(r) for r in cur.fetchall()]
    finally:
        cn.close()


def _entry_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    cast = d.pop("cast_json", None)
    d["cast"] = json.loads(cast) if cast else []
    return d


def _state(cfg: dict, e: dict) -> str:
    """五态

    ready   已出报
    empty   有归档，但素材不足成篇——不是欠账，是这天本来就没东西
    pending 有归档，素材够，还欠一份日报
    orphan  有产物无归档（通常意味着 data 被清过）
    missing 配置里监控、当天连归档都没有（采集断了）

    `empty` 单列出来，是为了不让必然事件长期显示成"欠一份日报"：
    单人单向的公告群每天都会是空料，把这种必然显示成 pending，
    视图里就永远挂着两笔假账，真出问题时反而看不见。
    """
    from . import collection
    collection.decorate(cfg, e)
    e["expected"] = True  # An actual collection/report record defines this group-day.
    if e['report']['state'] in ('ready', 'stale'):
        return 'ready'
    if e['report']['state'] == 'orphan':
        return 'orphan'
    if e['report']['state'] == 'insufficient':
        return 'empty'
    if e['collection']['state'] in ('not_collected', 'failed') and not e.get('data_file'):
        return 'missing'
    return 'pending'


def get_entry(cfg: dict, date: str, username: str) -> dict | None:
    """取单个交点（某群某天），带 state"""
    rows = _query_entries(cfg, "date=? AND username=?", (date, username),
                          order="date")
    if not rows:
        return None
    e = rows[0]
    e["state"] = _state(cfg, e)
    return e


def by_day(cfg: dict, date: str, include_configured: bool = True) -> dict:
    """当日总览：这一天所有群

    include_configured=True 时，仅为有明确生效日期且当天应采集的关注群补行。
    旧配置的当前名单不能证明过去的应采集范围；真实记录始终保留。
    """
    rows = _query_entries(cfg, "date=?", (date,))
    seen = {r["username"] for r in rows}
    for r in rows:
        r["state"] = _state(cfg, r)

    if include_configured:
        for c in settings.active_chats(cfg):
            u = c.get("username") or ""
            if u and u not in seen and settings.expected_on(cfg, u, date) is True:
                rows.append(uncollected_entry(cfg, date, c))
    from . import collection
    for row in rows:
        if "collection" not in row:
            collection.decorate(cfg, row)
    rows.sort(key=lambda x: -x.get("total", 0))
    return {
        "date": date,
        "chats": rows,
        "total": sum(r.get("total", 0) for r in rows),
        "reports": sum(1 for r in rows if r["state"] == "ready"),
        "pending": sum(1 for r in rows if r["state"] == "pending"),
        "missing": sum(1 for r in rows if r["state"] == "missing"),
    }


def by_chat(cfg: dict, username: str, limit: int = 30) -> dict:
    """群时间线：一个群最近 N 天，最新在上"""
    rows = _query_entries(cfg, "username=?", (username,), order="date DESC")
    rows = rows[:limit]
    for r in rows:
        r["state"] = _state(cfg, r)
    name = rows[0]["chat"] if rows else username
    totals = [r["total"] for r in rows if r["total"]]
    return {
        "username": username,
        "chat": name,
        "days": len(rows),
        "avg": round(sum(totals) / len(totals), 1) if totals else 0,
        "last_date": rows[0]["date"] if rows else None,
        "entries": rows,
    }


def list_chats(cfg: dict) -> list:
    """群列表 + 画像

    两个关键区分：
    - `followed`：是不是 config.json 里关注的群（来自配置，不是来自归档）
    - 关注但从未归档过的群**也要出现**，否则它在界面上等于消失了

    v1.2 起每行带 `last_state`：该群**最近一天**的五态。
    加它是因为前端曾经用 `reports>0 ? ready : total>0 ? pending : missing`
    自己推——这套推法永远推不出 `empty`，于是"素材不足"在群列表里
    被画成"欠一份日报"，正是第五态最容易被吃掉的地方。
    """
    followed_u = {c.get("username") for c in settings.active_chats(cfg)
                  if c.get("username")}
    cn = connect(cfg)
    try:
        rows = cn.execute(
            "SELECT username, chat, kind, COUNT(*) days, SUM(total) total, "
            "MIN(date) first_date, MAX(date) last_date, "
            "SUM(CASE WHEN report_png IS NOT NULL OR report_html IS NOT NULL "
            "    THEN 1 ELSE 0 END) reports, "
            "MAX(CASE WHEN report_png IS NOT NULL OR report_html IS NOT NULL "
            "    THEN date END) last_report "
            "FROM entry GROUP BY username ORDER BY last_date DESC, total DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            top = cn.execute(
                "SELECT sender, COUNT(*) c FROM message WHERE username=? "
                "GROUP BY sender ORDER BY c DESC LIMIT 1", (d["username"],)
            ).fetchone()
            d["top_sender"] = top["sender"] if top else ""
            d["followed"] = d["username"] in followed_u
            out.append(d)

        # 每个群最新一天的状态。ORDER BY date 升序，后写覆盖前写。
        latest = {}
        for r in cn.execute("SELECT * FROM entry ORDER BY date"):
            e = _entry_row(r)
            latest[e["username"]] = e
    finally:
        cn.close()

    for d in out:
        e = latest.get(d["username"])
        d["last_state"] = _state(cfg, e) if e else "missing"

    known = {r["username"] for r in out}
    for c in settings.active_chats(cfg):
        u = c.get("username") or ""
        if u and u not in known:
            out.append({
                "username": u, "chat": c.get("name") or u,
                "kind": c.get("kind", "group"), "days": 0, "total": 0,
                "first_date": None, "last_date": None, "reports": 0,
                "last_report": None, "top_sender": "", "followed": True,
                "last_state": "missing",
            })
    out.sort(key=lambda r: r["last_date"] or "", reverse=True)
    out.sort(key=lambda r: 0 if r["followed"] else 1)   # 稳定排序：关注的在前
    return out


def day_index(cfg: dict, limit: int = 0) -> list:
    """按日期聚合：每天几个群、多少条、出了几份日报（倒序）

    v1.2 起每行还带五态计数。为什么不能在别处凑：
    「按日期」轴只靠 `recent`（最近 30 天）画的话，第 31 天往前的行
    会因为没有明细而显示成 0 个群 / 空心的点——那天明明有归档。
    轴的计数必须来自全量索引，明细才允许只覆盖最近 N 天。

    `reports` 保留旧语义（索引登记了几份），`ready` 是新口径（磁盘上真的有）。
    两个数可能不一样，信 `ready`。
    """
    cn = connect(cfg)
    try:
        rows = cn.execute("SELECT * FROM entry ORDER BY date DESC").fetchall()
    finally:
        cn.close()

    agg = {}
    for r in rows:
        e = _entry_row(r)
        a = agg.get(e["date"])
        if a is None:
            a = agg[e["date"]] = {
                "date": e["date"], "chats": 0, "total": 0, "reports": 0,
                "ready": 0, "pending": 0, "empty": 0, "orphan": 0, "missing": 0,
            }
        s = _state(cfg, e)
        a["chats"] += 1
        a["total"] += e["total"] or 0
        if e.get("report_png") or e.get("report_html"):
            a["reports"] += 1
        a[s] = a.get(s, 0) + 1

    out = sorted(agg.values(), key=lambda x: x["date"], reverse=True)
    return out[:limit] if limit else out


def recent_days(cfg: dict, limit_days: int = 7) -> list:
    """最近若干天的日报流：每天一组，组内 ready 优先

    这是「最近日报」页的数据源——按日期倒序分组，组内列该天的各个群。
    """
    out = []
    for d in day_index(cfg, limit_days):
        rows = _query_entries(cfg, "date=?", (d["date"],))
        for r in rows:
            r["state"] = _state(cfg, r)
        rows.sort(key=lambda x: (x["state"] != "ready", -x["total"]))
        out.append({**d, "entries": rows})
    return out



def uncollected_entry(cfg, date, chat):
    """Explicit navigation may describe an unobserved point without claiming it was due."""
    from . import collection
    username = chat['username']
    entry = {'date': date, 'username': username, 'chat': chat.get('name') or chat.get('chat') or username,
             'kind': chat.get('kind', 'group'), 'total': 0, 'chars': 0, 'unique_senders': 0,
             'data_file': '', 'report_html': None, 'report_png': None, 'title': None, 'lead': None,
             'cast': [], 'archived_at': None, 'composed_at': None, 'state': 'missing',
             'expected': settings.expected_on(cfg, username, date)}
    collection.decorate(cfg, entry)
    return entry


def _missing_cell(cfg, date, chat):
    return dict(uncollected_entry(cfg, date, chat), ready=False)


def matrix(cfg: dict, days: int = 14) -> dict:
    """全景矩阵：行=群，列=日期

    真正价值是暴露空洞——哪天空了、哪个群一直没数据。
    """
    cn = connect(cfg)
    try:
        dates = [r[0] for r in cn.execute(
            "SELECT DISTINCT date FROM entry ORDER BY date DESC LIMIT ?",
            (days,)).fetchall()]
        dates.sort()
        chats = [dict(r) for r in cn.execute(
            "SELECT username, chat FROM entry "
            "GROUP BY username ORDER BY MAX(date) DESC").fetchall()]
        # 单元格必须带 state：矩阵是唯一一个「一眼看五态」的表面，
        # 只给 total + ready 会让 empty（素材不足）退化成数字，
        # 于是必然没料的日子看着像欠账，反而掩盖真正的空洞。
        # 这里直接复用 _state()，不另写一套判定——两套判定迟早会分叉。
        cells = {}
        for r in cn.execute(
                "SELECT * FROM entry WHERE date >= ?",
                (dates[0] if dates else "",)):
            e = _entry_row(r)
            legacy_state = _state(cfg, e)
            cells[(e["date"], e["username"])] = {
                "date": e["date"], "total": e["total"],
                "ready": bool(e["report"]["html_url"]),
                "state": legacy_state, "expected": True,
                "collection": e["collection"], "report": e["report"],
            }
        # 配置里监控但从未归档的群也要出现在矩阵里（否则会"消失得无声无息"）
        known = {c["username"] for c in chats}
        for c in settings.active_chats(cfg):
            u = c.get("username") or ""
            if u and u not in known:
                chats.append({"username": u, "chat": c.get("name", u)})
                known.add(u)

        grid = []
        for c in chats:
            grid.append({
                "username": c["username"],
                "chat": c["chat"],
                "cells": [cells.get((d, c["username"])) or _missing_cell(cfg, d, c)
                          for d in dates],
            })
        return {"dates": dates, "rows": grid}
    finally:
        cn.close()


# ---------------------------------------------------------------- 读：检索

def search(cfg: dict, kw: str, chat: str | None = None,
           sender: str | None = None, mtype: str | None = None,
           start: str | None = None, end: str | None = None,
           limit: int = 100) -> list:
    """跨群跨天搜消息正文

    chat 参数仅收契约规定的稳定 username，不以名称或 ID 片段扩大范围。
    """
    where, args = ["m.text LIKE ?"], [f"%{kw}%"]
    if chat:
        where.append("m.username=?")
        args.append(chat)
    if sender:
        where.append("(m.sender LIKE ? OR m.sender_uid=?)")
        args.extend((f"%{sender}%", sender))
    if mtype:
        where.append("m.type=?")
        args.append(mtype)
    if start:
        where.append("m.date>=?")
        args.append(start)
    if end:
        where.append("m.date<=?")
        args.append(end)
    args.append(limit)

    cn = connect(cfg)
    try:
        cur = cn.execute(
            "SELECT m.*, e.chat FROM message m "
            "LEFT JOIN entry e ON e.date=m.date AND e.username=m.username "
            f"WHERE {' AND '.join(where)} ORDER BY m.ts DESC LIMIT ?", tuple(args))
        out = []
        from .analysis import search_key
        for r in cur.fetchall():
            d = dict(r)
            d["time"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["ts"]))
            d['context_key'] = search_key(d)
            out.append(d)
        return out
    finally:
        cn.close()


def overview(cfg: dict) -> dict:
    cn = connect(cfg)
    try:
        r = cn.execute(
            "SELECT COUNT(*) entries, COUNT(DISTINCT username) chats, "
            "COUNT(DISTINCT date) days, COALESCE(SUM(total),0) msgs, "
            "MIN(date) first_date, MAX(date) last_date FROM entry").fetchone()
        ready = cn.execute(
            "SELECT COUNT(*) c FROM entry "
            "WHERE report_png IS NOT NULL OR report_html IS NOT NULL"
        ).fetchone()["c"]
        return {**dict(r), "reports": ready}
    finally:
        cn.close()


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    import sys
    cfg = settings.load()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stat"
    if cmd == "rebuild":
        print(rebuild(cfg, verbose="-v" in sys.argv))
        print("导出:", dump_json(cfg))
    elif cmd == "stat":
        print(json.dumps(overview(cfg), ensure_ascii=False, indent=2))
        print("\n群画像:")
        for c in list_chats(cfg):
            print(f"  {c['chat']:<28} {c['days']}天 {c['total']:>6}条 "
                  f"{c['first_date']}~{c['last_date']} 最活跃:{c['top_sender']}")
    elif cmd == "matrix":
        m = matrix(cfg, 14)
        print("日期:", " ".join(d[5:] for d in m["dates"]))
        for row in m["rows"]:
            cells = " ".join(f"{c['total']:>5}" if c["total"] else "    ·"
                             for c in row["cells"])
            print(f"  {row['chat'][:14]:<16}{cells}")
    elif cmd == "search":
        kw = sys.argv[2] if len(sys.argv) > 2 else ""
        for h in search(cfg, kw, limit=20):
            print(f"{h['time']} [{h.get('chat') or h['username']}] "
                  f"{h['sender']}: {h['text'][:80]}")
