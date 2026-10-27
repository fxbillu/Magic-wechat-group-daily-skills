"""浏览界面：本机只读站点（Vue 前端 + JSON API）

    python tools/serve.py                 # http://127.0.0.1:8765
    python tools/serve.py --port 9000 --open

只绑本机回环地址。要手机看，未来走飞书云文档，不在这里开局域网端口——
明文聊天记录一旦监听 0.0.0.0，同一个 WiFi 下谁都能访问。

结构
    web/                    前端（Vue 3 本地单文件，无构建链，改完刷新即见）
    /api/browse             概览 + 最近一天 + 群列表 + 矩阵 + 日期轴 + 最近 N 天流
    /api/day                某一天全部群（不受最近 N 天窗口限制）
    /api/chat               某群时间线（默认最近 60 个归档日）
    /api/entry              某群某天的单个交点（含五态）
    /api/search             跨群跨天全文搜索
    /api/messages           某群某天的原始消息（分页）
    /api/health             自检：数据规模与索引状态
    /r/<相对路径>           reports 下的产物（HTML / PNG），带路径穿越防护
    <其他 GET>              SPA fallback → web/index.html

开发契约见仓库 docs/contracts/read-api-v1.md；旧读取字段保持兼容。
"""
import argparse
import json
import os
import posixpath
import re
import sqlite3
import sys
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "lib"))

from wechat_data import analysis, archive, browse, db, readiness, settings  # noqa: E402

WEB_DIR = os.path.join(SCRIPTS_DIR, "web")

RECENT_MAX = 30          # /api/browse 一次带多少天的日报流
SEARCH_LIMIT_MAX = 500
MESSAGES_LIMIT_MAX = 500
MESSAGES_LIMIT_DEFAULT = 40

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}


# ---------------------------------------------------------------- 工具

def _one(qs: dict, key: str, default: str = "") -> str:
    return (qs.get(key) or [default])[0].strip()


def _clamp(raw, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


def _is_date(s: str) -> bool:
    return bool(DATE_RE.match(s or ""))


# ---------------------------------------------------------------- API

def api_browse(qs: dict, cfg: dict) -> dict:
    """三个视图的全部数据，一次给完。

    在契约的五个字段之外增加 `recent`（最近 N 天的日报流）。
    原因：`today` 只给最近一天，首页的 3/7/14/30 天切换需要按天分组的数据。
    旧字段一个不动，符合 SCHEMA §0「字段只增不改」。
    """
    days = _clamp(_one(qs, "days", str(RECENT_MAX)), 1, 365, RECENT_MAX)
    data = browse(cfg)
    data["recent"] = db.recent_days(cfg, days)
    # 日期轴的计数必须来自全量索引：`recent` 只覆盖最近 N 天，
    # 拿它画整条轴会让更早的日子显示成「0 个群」，那是假的。
    data["dayrows"] = db.day_index(cfg)
    return data


def _required_point(qs: dict) -> tuple:
    """校验「日期 × 群」参数；三个明细接口共用同一套错误语义。"""
    date, username = _one(qs, "date"), _one(qs, "username")
    if not _is_date(date):
        return None, ({"error": "date 须为 YYYY-MM-DD", "field": "date"}, 400)
    if not username:
        return None, ({"error": "缺少 username", "field": "username"}, 400)
    return (date, username), None


def api_day(qs: dict, cfg: dict) -> tuple:
    """某一天全部群。直接打开旧链接时不依赖 browse 的 30 天窗口。"""
    date = _one(qs, "date")
    if not _is_date(date):
        return {"error": "date 须为 YYYY-MM-DD", "field": "date"}, 400
    return db.by_day(cfg, date, include_configured=True), 200


def api_chat(qs: dict, cfg: dict) -> tuple:
    """一个群的完整时间线（最近 60 个归档日）。"""
    username = _one(qs, "username")
    if not username:
        return {"error": "缺少 username", "field": "username"}, 400
    limit = _clamp(_one(qs, "limit", "60"), 1, 365, 60)
    payload = db.by_chat(cfg, username, limit)
    if not payload["entries"]:
        # 关注但从未归档的群仍有自己的说明页，不应被当成路由错误。
        configured = next((c for c in settings.active_chats(cfg)
                           if c.get("username") == username), None)
        if not configured:
            return {"error": "没有这个群的归档", "username": username}, 404
        payload["chat"] = configured.get("name") or username
        payload["followed"] = True
    return payload, 200


def api_entry(qs: dict, cfg: dict) -> tuple:
    """某群某天的单个交点，含后端统一计算的五态。"""
    point, error = _required_point(qs)
    if error:
        return error
    date, username = point
    entry = db.get_entry(cfg, date, username)
    if not entry:
        configured = next((c for c in settings.active_chats(cfg)
                           if c.get('username') == username), None)
        if configured:
            entry = db.uncollected_entry(cfg, date, configured)
    if not entry:
        return {"error": "该群这一天没有归档", "date": date,
                "username": username}, 404
    return entry, 200


def api_search(qs: dict, cfg: dict) -> tuple:
    kw = _one(qs, "q")
    if not kw:
        return {"error": "缺少查询词", "field": "q"}, 400
    if len(kw) > 200:
        return {"error": "查询词过长（上限 200 字）", "field": "q"}, 400

    limit = _clamp(_one(qs, "limit", "100"), 1, SEARCH_LIMIT_MAX, 100)
    start, end = _one(qs, "from"), _one(qs, "to")
    if start and not _is_date(start):
        return {"error": "from 须为 YYYY-MM-DD", "field": "from"}, 400
    if end and not _is_date(end):
        return {"error": "to 须为 YYYY-MM-DD", "field": "to"}, 400

    rows = db.search(
        cfg, kw,
        chat=_one(qs, "chat") or None,
        sender=_one(qs, "sender") or None,
        mtype=_one(qs, "type") or None,
        start=start or None,
        end=end or None,
        limit=limit,
    )
    return {
        "query": {"q": kw, "chat": _one(qs, "chat"), "sender": _one(qs, "sender"),
                  "type": _one(qs, "type"), "from": start, "to": end,
                  "limit": limit},
        "count": len(rows),
        "truncated": len(rows) >= limit,
        "results": rows,
    }, 200


def api_messages(qs: dict, cfg: dict) -> tuple:
    """某群某天的原始消息。明细页在「还没出日报」时用它让用户判断要不要生成。"""
    point, error = _required_point(qs)
    if error:
        return error
    date, username = point

    entry = db.get_entry(cfg, date, username)
    if not entry:
        day = db.by_day(cfg, date)
        entry = next((e for e in day['chats'] if e['username'] == username), None)
    if entry and entry['collection']['state'] == 'failed' and not entry.get('data_file'):
        return {'error': '采集失败，尚无成功素材，请在 WorkBuddy 中重试。',
                'code': 'COLLECTION_FAILED', 'retryable': True,
                'next_action': 'decrypt_and_retry_in_workbuddy',
                'collection': entry['collection']}, 409
    if not entry:
        return {"error": "该群这一天没有归档", "date": date}, 404

    offset = _clamp(_one(qs, "offset", "0"), 0, 100000, 0)
    limit = _clamp(_one(qs, "limit", str(MESSAGES_LIMIT_DEFAULT)),
                   1, MESSAGES_LIMIT_MAX, MESSAGES_LIMIT_DEFAULT)

    payload = archive.load(cfg, date, username) or {}
    all_msgs = payload.get("messages") or []
    page = all_msgs[offset:offset + limit]
    return {
        "date": date,
        "username": username,
        "chat": entry["chat"],
        "state": entry["state"],
        "collection": entry["collection"], "report": entry["report"],
        "total": len(all_msgs),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(all_msgs),
        "messages": [
            {"time": m.get("time", ""), "sender": m.get("sender", ""),
             "type": m.get("type", ""), "text": m.get("text", "")}
            for m in page
        ],
    }, 200


def api_context(qs: dict, cfg: dict) -> tuple:
    point, error = _required_point(qs)
    if error:
        return error
    date, username = point
    key = _one(qs, 'key')
    if not re.fullmatch(r'[0-9a-f]{64}', key):
        return {'error': '缺少有效的搜索来源，请重新搜索。'}, 400
    payload = archive.load(cfg, date, username)
    if not payload or payload.get('chat', {}).get('username') != username:
        return {'error': '找不到该群当日的素材归档。'}, 404
    result = analysis.context(payload, date, key,
                              _clamp(_one(qs, 'before'), 0, 30, 8),
                              _clamp(_one(qs, 'after'), 0, 30, 12))
    if result is None:
        return {'error': '来源已变化或无法唯一定位，请重新采集索引后搜索。',
                'code': 'CONTEXT_CHANGED'}, 409
    entry = db.get_entry(cfg, date, username)
    return {'date': date, 'username': username, **result,
            'collection': entry.get('collection') if entry else None}, 200


def api_analysis(qs: dict, cfg: dict) -> tuple:
    point, error = _required_point(qs)
    if error:
        return error
    date, username = point
    payload = archive.load(cfg, date, username)
    if not payload or payload.get('chat', {}).get('username') != username:
        return {'error': '尚无该群当日的素材归档。'}, 404
    entry = db.get_entry(cfg, date, username)
    return {'date': date, 'username': username,
            'source_revision': (payload.get('collection') or {}).get('revision'),
            'collection': entry.get('collection') if entry else None,
            'activity': analysis.activity(payload), 'analysis': analysis.saved(cfg, entry, payload)}, 200


def api_health(cfg: dict) -> dict:
    return {
        "ok": True,
        "index_ready": db.exists(cfg),
        "overview": db.overview(cfg),
        "recent_max": RECENT_MAX,
        "web_ready": os.path.isfile(os.path.join(WEB_DIR, "index.html")),
    }


# ---------------------------------------------------------------- 服务

class Handler(BaseHTTPRequestHandler):
    server_version = "GroupDaily/2.0"
    protocol_version = "HTTP/1.1"

    # ---------- 分发

    def do_GET(self):  # noqa: N802
        raw = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(raw.path)
        qs = urllib.parse.parse_qs(raw.query)
        try:
            if path.startswith("/api/"):
                return self.route_api(path, qs)
            if path.startswith("/r/"):
                return self.serve_report(path[3:])
            return self.serve_static_or_spa(path)
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            if path.startswith("/api/"):
                return self.send_json({"error": "内部错误", "detail": tb.splitlines()[-1]}, 500)
            return self.send_bytes(
                "text/plain; charset=utf-8",
                ("服务端错误\n\n" + tb).encode("utf-8"), 500)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    # ---------- API

    def route_api(self, path: str, qs: dict):
        state, cfg = readiness.snapshot()
        if path == "/api/status":
            return self.send_json(state)
        known = {"/api/browse", "/api/day", "/api/chat", "/api/entry",
                 "/api/search", "/api/messages", "/api/health", "/api/context", "/api/analysis"}
        if path in known and not state["reading"]["available"]:
            return self.send_json(readiness.unavailable_error(state), 503)
        if path not in known:
            return self.send_json({"error": "未知接口", "path": path}, 404)
        try:
            return self.dispatch_data_api(path, qs, db.readonly_config(cfg))
        except sqlite3.Error:
            # The index may have changed after the status probe. Never migrate
            # it or expose SQLite diagnostics through a browser GET.
            return self.send_json({
                "schema_version": 1,
                "error": "阅读索引暂不可用。请在 WorkBuddy 中检查后重新读取。",
                "code": "INDEX_INVALID", "retryable": False,
                "next_action": "repair_reading_index_in_workbuddy",
            }, 503)

    def dispatch_data_api(self, path: str, qs: dict, cfg: dict):
        if path == "/api/browse":
            return self.send_json(api_browse(qs, cfg))
        if path == "/api/day":
            body, code = api_day(qs, cfg)
            return self.send_json(body, code)
        if path == "/api/chat":
            body, code = api_chat(qs, cfg)
            return self.send_json(body, code)
        if path == "/api/entry":
            body, code = api_entry(qs, cfg)
            return self.send_json(body, code)
        if path == "/api/search":
            body, code = api_search(qs, cfg)
            return self.send_json(body, code)
        if path == "/api/messages":
            body, code = api_messages(qs, cfg)
            return self.send_json(body, code)
        if path in ('/api/context', '/api/analysis'):
            body, code = (api_context if path == '/api/context' else api_analysis)(qs, cfg)
            return self.send_json(body, code)
        if path == "/api/health":
            return self.send_json(api_health(cfg))

    # ---------- reports 产物

    def serve_report(self, rel: str):
        state, cfg = readiness.snapshot()
        if not state["reading"]["available"]:
            return self.send_json(readiness.unavailable_error(state), 503)
        rep = os.path.realpath(settings.reports_dir(cfg))
        target = os.path.realpath(os.path.join(rep, rel))
        if not target.startswith(rep + os.sep) or not os.path.isfile(target):
            return self.send_bytes("text/plain; charset=utf-8",
                                   b"404 file not found", 404)
        return self.send_file(target, cache="no-cache")

    # ---------- 静态资源 + SPA fallback

    def serve_static_or_spa(self, path: str):
        if path in ("/", ""):
            return self.serve_index()

        # 规范化，挡住 ../ 与绝对路径
        clean = posixpath.normpath("/" + path.lstrip("/"))
        if clean.startswith("/..") or "\x00" in clean:
            return self.send_bytes("text/plain; charset=utf-8", b"400 bad path", 400)

        target = os.path.realpath(os.path.join(WEB_DIR, clean.lstrip("/")))
        root = os.path.realpath(WEB_DIR)
        if target.startswith(root + os.sep) and os.path.isfile(target):
            # vendor 里的第三方库可长缓存；自家资源不缓存，改完刷新即见
            cache = "public, max-age=31536000, immutable" \
                if "/vendor/" in target.replace("\\", "/") else "no-cache"
            return self.send_file(target, cache=cache)

        # 带扩展名的请求 → 真的不存在，不该 fallback 成 HTML
        if os.path.splitext(clean)[1]:
            return self.send_bytes("text/plain; charset=utf-8",
                                   ("404 " + clean).encode("utf-8"), 404)

        # 其余都交给前端路由（History API）
        return self.serve_index()

    def serve_index(self):
        idx = os.path.join(WEB_DIR, "index.html")
        if not os.path.isfile(idx):
            return self.send_bytes(
                "text/html; charset=utf-8",
                ("<!DOCTYPE html><html lang=zh-CN><meta charset=utf-8>"
                 "<title>前端资源缺失</title>"
                 "<div style=\"font:15px/1.6 -apple-system,'Segoe UI',"
                 "'Microsoft YaHei',sans-serif;max-width:640px;margin:80px auto;"
                 "color:#22201C\">"
                 "<h1 style=\"font-size:22px\">前端资源缺失</h1>"
                 f"<p style=\"color:#66615A\">找不到 <code>{idx}</code>。</p>"
                 "<p style=\"color:#66615A\">技能包不完整，重新解压出厂 zip，"
                 "或确认 <code>scripts/web/</code> 目录存在。</p></div>"
                 "</html>").encode("utf-8"), 500)
        return self.send_file(idx, cache="no-cache")

    # ---------- 基础输出

    def send_file(self, target: str, cache: str = "no-cache"):
        ext = os.path.splitext(target)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(target, "rb") as f:
            data = f.read()
        self.send_bytes(ctype, data, 200, cache=cache)

    def send_bytes(self, ctype: str, data: bytes, code: int = 200,
                   cache: str = "no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_json(self, obj, code: int = 200):
        # 前端用 fetch 消费，不塞进 <script>，因此无需 \u003c 转义
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_bytes("application/json; charset=utf-8", body, code)

    def log_message(self, fmt, *args):
        try:
            msg = fmt % args
        except Exception:  # noqa: BLE001
            msg = str(fmt)
        path = urllib.parse.unquote(self.path)
        print("  %s %s  %s" % (self.command, path, msg))

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass


def main():
    ap = argparse.ArgumentParser(description="本机浏览界面")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(WEB_DIR, "index.html")):
        print(f"[警告] 前端资源缺失：{WEB_DIR}", file=sys.stderr)

    addr = ("127.0.0.1", args.port)
    try:
        srv = ThreadingHTTPServer(addr, Handler)
    except OSError as e:
        print(f"[错误] 端口 {args.port} 不可用：{e}", file=sys.stderr)
        return 3

    url = f"http://{addr[0]}:{srv.server_address[1]}/"
    print(f"群日报浏览  {url}", flush=True)
    print("只监听本机回环，局域网不可访问      Ctrl+C 停止")
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
