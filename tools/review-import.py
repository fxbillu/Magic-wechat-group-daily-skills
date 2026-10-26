"""Reproduce the imported skill review with synthetic data only.

Run from this repository: python3 tools/review-import.py
No Windows APIs, credentials, external services, or real conversations are used.
The reviewed source is never changed. Output and fixtures stay in legacy-import/qa.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
IMPORTED = ROOT / "legacy-import/distribution/wechat-群日报"
SKILL = IMPORTED / ".workbuddy/skills/wechat-group-daily"
SCRIPTS = SKILL / "scripts"
OUT = ROOT / "legacy-import/qa"
OUT.mkdir(parents=True, exist_ok=True)
sys.path[:0] = [str(SCRIPTS / "lib"), str(SCRIPTS / "tools"), str(SCRIPTS)]
sys.dont_write_bytecode = True

from wechat_data import archive, db, guard, settings, Chat, Message, MessageReader
from wechat_data.messages import table_of
from wechat_data import avatar


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


setup = module("review_setup", SCRIPTS / "tools/setup.py")
fetch = module("review_fetch", SCRIPTS / "fetch.py")
serve = module("review_serve", SCRIPTS / "tools/serve.py")
decrypt = module("review_decrypt", SCRIPTS / "tools/safe_decrypt.py")
pack = module("review_package", SCRIPTS / "tools/package.py")
check = module("review_check", SCRIPTS / "tools/check_story.py")
render = module("review_render", SCRIPTS / "tools/render_daily.py")
results = []


def record(name, status, detail):
    results.append({"name": name, "status": status, "detail": detail})
    print(f"{status}: {name}: {detail}")


def config(root):
    cfg = settings.default_config()
    cfg["paths"] = {k: str(root / k) for k in
                    ("decrypted", "data", "reports", "secrets", "logs")}
    cfg["paths"]["root"] = str(root)
    for value in cfg["paths"].values():
        Path(value).mkdir(parents=True, exist_ok=True)
    cfg["chats"] = [{"name": "测试群甲", "username": "test-a@chatroom", "daily": True},
                    {"name": "测试群乙", "username": "test-b@chatroom", "daily": True}]
    return cfg


DAY = "2026-10-24"
START = datetime.fromisoformat(DAY)
CHAT = Chat("test-a@chatroom", "测试群甲", kind="group")
MESSAGES = [Message(1, START.replace(hour=9), "成员甲", "test-user-a", 1, 0, "甲" * 120),
            Message(2, START.replace(hour=10), "成员乙", "test-user-b", 1, 0, "乙" * 120)]


def save(cfg, chat=CHAT, msgs=MESSAGES, day=DAY):
    start = datetime.fromisoformat(day)
    return archive.save(cfg, day, chat, msgs, MessageReader.summarize(msgs),
                        start, start + timedelta(days=1))


def syntax():
    files = list(SKILL.rglob("*.py"))
    for path in files:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    node = subprocess.run(["node", "--check", str(SCRIPTS / "web/app.js")], capture_output=True)
    assert node.returncode == 0
    return "PASS", f"{len(files)} Python files and frontend JavaScript parse"


def config_checks():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        with patch.object(settings, "CONFIG_PATH", str(path)):
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    settings.require()
                raise AssertionError("missing configuration was accepted")
            except SystemExit as exc:
                assert exc.code == 6
            path.write_text("{invalid-json")
            cfg = settings.require()
            assert cfg["paths"]["root"] == settings.ROOT
    return "CONFIRMED_BUG", "missing config blocks with 6; malformed config silently accepts package-local defaults"


def interactive_path():
    cfg = settings.default_config()
    with patch.object(setup, "ask_required", return_value=""), patch.object(setup.os, "makedirs"):
        setup.pick_paths(SimpleNamespace(root=None, auto=False), cfg)
    assert cfg["paths"]["root"] == setup.BASE
    return "CONFIRMED_BUG", "interactive Enter selects the skill scripts directory for keys and plaintext data"


def setup_failed_decrypt():
    cfg = settings.default_config()
    acct = {"db_dir": "/synthetic/source", "account": "synthetic-account", "root": "/synthetic"}
    with contextlib.ExitStack() as stack:
        for obj, name, value in [(setup, "check_env", True), (settings, "load", cfg),
                                 (setup, "pick_account", acct), (setup, "pick_paths", cfg),
                                 (setup, "get_keys", "/synthetic/keys"),
                                 (setup, "decrypt_all", False),
                                 (setup, "pick_chats", [{"name": CHAT.name, "username": CHAT.username}]),
                                 (setup, "pick_schedule", cfg), (settings, "save", "/synthetic/config")]:
            stack.enter_context(patch.object(obj, name, return_value=value))
        stack.enter_context(patch.object(sys, "argv", ["setup.py", "--auto"]))
        code = setup.main()
    assert code == 0
    return "CONFIRMED_BUG", "decrypt_all=False still produces initialization completed and exit 0"


def ambiguous_group():
    resolver = SimpleNamespace(search=lambda *a, **k: [CHAT, Chat("test-b@chatroom", "测试群甲二", kind="group")])
    with patch("builtins.input", side_effect=EOFError):
        try:
            setup._match_token("测试群甲", resolver, [])
        except EOFError:
            return "CONFIRMED_BUG", "--groups keyword with multiple matches calls bare input and raises EOFError unattended"
    raise AssertionError("expected ambiguous unattended selection to fail")


def archive_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config(Path(tmp)); save(cfg)
        assert len(db.search(cfg, "甲")) == 1
        errors = {}
        for name, kwargs in [("chat", {"chat": CHAT.username}), ("date", {"start": DAY})]:
            try:
                db.search(cfg, "甲", **kwargs)
            except sqlite3.OperationalError as exc:
                errors[name] = str(exc)
        assert len(errors) == 2
        return "CONFIRMED_BUG", f"keyword search works; filters fail: {errors}"


def empty_collection():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config(Path(tmp))
        reader = SimpleNamespace(fetch=lambda *a: [], __enter__=None)
        class Reader:
            def __init__(self, *args): pass
            def __enter__(self): return reader
            def __exit__(self, *args): pass
        resolver = SimpleNamespace(resolve=lambda *a, **k: CHAT)
        with patch.object(settings, "require", return_value=cfg), \
             patch("wechat_data.ChatResolver", return_value=resolver), \
             patch("wechat_data.MessageReader", Reader):
            code = fetch.cmd_archive(SimpleNamespace(config=True, chats=None, date=DAY, db_dir=tmp))
        state = db.by_day(cfg, DAY)["chats"][0]["state"]
        assert code == 2 and state == "missing"
    return "CONFIRMED_BUG", "successfully read zero messages => no archive, exit 2, displayed as missing/collection failure"


def same_name_groups():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config(Path(tmp)); save(cfg)
        second = Chat("test-b@chatroom", CHAT.name, kind="group")
        save(cfg, second)
        before = db.overview(cfg)["entries"]
        path = Path(archive.archive_path(cfg, DAY, CHAT.name))
        owner = json.loads(path.read_text())["chat"]["username"]
        db.rebuild(cfg)
        after = db.overview(cfg)["entries"]
        assert before == 2 and after == 1 and owner == second.username
    return "CONFIRMED_BUG", "two same-name groups overwrite one JSON: index has 2 entries, rebuild recovers only 1"


def make_shards(root, corrupt=False):
    (root / "contact").mkdir(); (root / "message").mkdir()
    cn = sqlite3.connect(root / "contact/contact.db")
    cn.execute("CREATE TABLE contact(username, nick_name, remark)")
    cn.executemany("INSERT INTO contact VALUES(?,?,?)", [("test-user-a", "成员甲", ""), ("test-user-b", "成员乙", "")])
    cn.commit(); cn.close()
    for i, sender in enumerate(["test-user-a", "test-user-b"]):
        p = root / f"message/message_{i}.db"
        if corrupt and i == 1:
            p.write_bytes(b"not a sqlite database"); continue
        cn = sqlite3.connect(p)
        cn.execute("CREATE TABLE Name2Id(user_name)")
        cn.execute("INSERT INTO Name2Id(rowid,user_name) VALUES(1,?)", (sender,))
        cn.execute(f'CREATE TABLE "{table_of(CHAT.username)}" (local_id,create_time,real_sender_id,local_type,message_content)')
        cn.execute(f'INSERT INTO "{table_of(CHAT.username)}" VALUES(?,?,?,?,?)',
                   (i + 1, int(START.replace(hour=9+i).timestamp()), 1, 1, "测试消息"))
        cn.commit(); cn.close()


def shard_sender():
    with tempfile.TemporaryDirectory() as tmp:
        make_shards(Path(tmp))
        with MessageReader(tmp) as reader:
            msgs = reader.fetch(CHAT, START, START + timedelta(days=1))
        names = [m.sender for m in msgs]
        assert names == ["成员甲", "成员甲"]
    return "CONFIRMED_BUG", "per-shard rowid=1 maps to different users, merged sender map attributes both messages to member A"


def corrupt_shard():
    with tempfile.TemporaryDirectory() as tmp:
        make_shards(Path(tmp), corrupt=True)
        with MessageReader(tmp) as reader:
            msgs = reader.fetch(CHAT, START, START + timedelta(days=1))
        assert len(msgs) == 1
    return "CONFIRMED_BUG", "a corrupt message shard is silently ignored; partial messages returned without warning"


def archive_after_report():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config(Path(tmp)); save(cfg)
        rep = Path(cfg["paths"]["reports"]) / DAY / f"{CHAT.name}.html"
        rep.parent.mkdir(); rep.write_text("<html>synthetic report</html>")
        db.set_report(cfg, DAY, CHAT.username, html=f"{DAY}/{CHAT.name}.html", story={"lead_title": "测试标题"})
        assert db.get_entry(cfg, DAY, CHAT.username)["report_html"]
        save(cfg)
        e = db.get_entry(cfg, DAY, CHAT.username)
        assert e["state"] == "ready" and e["report_html"] is None and e["title"] is None
    return "CONFIRMED_BUG", "recollecting same date clears report links/title while state remains ready from disk fallback"


def gap_days():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config(Path(tmp)); save(cfg, day="2026-10-22"); save(cfg, day="2026-10-24")
        days = [r["date"] for r in db.day_index(cfg)]
        matrix = db.matrix(cfg)["dates"]
        assert "2026-10-23" not in days and "2026-10-23" not in matrix
    return "PASS_WITH_LIMITATION", "backend returns archive dates only; frontend explicitly fills calendar gaps (verified in browser)"


def render_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);cfg=config(root);save(cfg)
        story={"group_name":CHAT.name,"date":DAY,"lead_title":"测试标题", "opening":"测试开场",
               "timeline":[],"highlights":[]}
        path=root/"synthetic-story.json";path.write_text(json.dumps(story))
        with patch.object(sys,"argv",["render_daily.py",str(path),"--no-png","--no-avatar"]), \
             patch.object(settings,"require",return_value=cfg):
            code=render.main()
        before=db.get_entry(cfg,DAY,CHAT.username)
        assert code==0 and before["state"]=="ready" and before["report_html"]
        rebuilt=db.rebuild(cfg)
        after=db.get_entry(cfg,DAY,CHAT.username)
        assert rebuilt["entries"]==1 and after["state"]=="ready" and after["title"]=="测试标题"
    return "PASS", "synthetic archive -> actual HTML renderer -> report registration -> index rebuild preserves report/title; no PNG/model test"


def partial_decrypt_stamp():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); src=root/"source"; out=root/"out"; src.mkdir(); out.mkdir()
        for name in ["contact.db", "message_0.db"]: (src/name).write_bytes(b"synthetic")
        keys=root/"synthetic-keys.json"
        keys.write_text(json.dumps({name:{"enc_key":"00"*32} for name in ["contact.db", "message_0.db"]}))
        def fake(src, dst, key):
            ok = str(src).endswith("contact.db")
            return {"ok":ok,"pages":1,"tables":1,"reason":"synthetic failure"}
        with patch.object(sys,"argv",["safe_decrypt.py","--db-dir",str(src),"--keys",str(keys),"--output",str(out)]), \
             patch.object(decrypt,"decrypt_one",side_effect=fake):
            code=decrypt.main()
        state=guard.check(str(out),target_date=DAY)
        assert code==1 and state["fresh"]
    return "CONFIRMED_BUG", "one successful DB plus one failed DB refreshes shared stamp; guard declares historical coverage fresh"


def quote_attribution():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        arch={"stats":{"total":2,"unique_senders":2,"chars":240},"messages":[m.to_dict() for m in MESSAGES]}
        story={"group_name":CHAT.name,"date":DAY,"opening":"中"*150,
               "stats":{"total_messages":2,"unique_senders":2,"total_chars":240},
               "highlights":[{"name":"成员甲"},{"name":"成员乙"}],
               "timeline":[{"no":str(i+1),"time":f"{9+i:02d}:00","story":"中"*160,
                            "theme":"测试","cast":["成员乙"],
                            "quotes":[{"who":"成员乙","text":MESSAGES[0].text}]} for i in range(3)]}
        ap=root/"archive.json";sp=root/"story.json"
        ap.write_text(json.dumps(arch));sp.write_text(json.dumps(story))
        with patch.object(sys,"argv",["check_story.py",str(sp),"--archive",str(ap)]): code=check.main()
        assert code==0
    return "CONFIRMED_BUG", "quotes spoken by member A but attributed to member B pass the mechanical checker"


def packaging():
    with tempfile.TemporaryDirectory() as tmp:
        pack.stage(tmp)
        baseline=pack.audit(tmp)
        assert not baseline, baseline
        shutil.rmtree(Path(tmp)/"scripts/web")
        assert not pack.audit(tmp)
        web=Path(tmp)/"scripts/web";web.mkdir()
        (web/"test.css").write_text("/* 1234567@chatroom */")
        assert not pack.audit(tmp)
    return "CONFIRMED_BUG", "factory audit passes baseline, also passes with all web files missing or group ID embedded in CSS"


def cli_uninitialized():
    cmd=[sys.executable,"-B",str(SCRIPTS/"fetch.py"),"status"]
    r=subprocess.run(cmd,capture_output=True,text=True)
    assert r.returncode==6
    return "PASS", "real CLI fetch.py status exits 6 without config"


def known_repairs():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);(root/"message").mkdir()
        for name in ["message_0.db","message_3.db","message_fts.db","message_resource.db"]:
            (root/"message"/name).touch()
        reader=MessageReader(tmp)
        assert [Path(p).name for p in reader.shard_paths]==["message_0.db","message_3.db"]
        reader.close()
    resolver=SimpleNamespace(all=lambda:[Chat("test-a","同名"),Chat("test-b","同名")])
    with patch("wechat_data.chat.ChatResolver",return_value=resolver):
        assert avatar.resolve_names_to_users(["同名"])=={}
    from wechat_data.messages import looks_undecoded
    assert looks_undecoded("\ufffd"*20) and not looks_undecoded("正常的中文消息")
    return "PASS", "R1 dynamic shard discovery/exclusions, R7 ambiguous avatar fallback, R8 garbled-text detection"


def seed_browser():
    root=OUT/"synthetic-runtime"
    if root.exists(): shutil.rmtree(root)
    cfg=config(root)
    save(cfg,day="2026-10-22");save(cfg)
    story={"group_name":CHAT.name,"date":DAY,"lead_title":"测试日报","opening":"测试开场", "timeline":[]}
    rep=Path(cfg["paths"]["reports"])/DAY/f"{CHAT.name}.html"
    rep.parent.mkdir();rep.write_text("<!doctype html><title>测试日报</title><h1>合成测试日报</h1>")
    db.set_report(cfg,DAY,CHAT.username,html=f"{DAY}/{CHAT.name}.html",story=story)
    (root/"review-config.json").write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    return "PASS", "synthetic browser fixture prepared; original runtime config untouched"


if __name__ == "__main__":
    for name, fn in [("syntax",syntax),("config validation",config_checks),
                     ("interactive data path",interactive_path),("initialization failure propagation",setup_failed_decrypt),
                     ("unattended ambiguous group",ambiguous_group),("archive and filtered search",archive_and_search),
                     ("zero-message collection",empty_collection),("same-name groups",same_name_groups),
                     ("cross-shard sender map",shard_sender),("corrupt shard",corrupt_shard),
                     ("recollection after report",archive_after_report),("whole-day gap visibility",gap_days),
                     ("partial decryption timestamp",partial_decrypt_stamp),("quote attribution",quote_attribution),
                     ("factory audit",packaging),("uninitialized CLI",cli_uninitialized),
                     ("HTML render and rebuild",render_roundtrip),
                     ("previous repair probes",known_repairs),
                     ("browser fixture",seed_browser)]:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            try:
                status,detail=fn()
            except Exception as exc:
                status,detail="HARNESS_ERROR",f"{type(exc).__name__}: {exc}"
        record(name,status,detail)
    (OUT/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
    raise SystemExit(1 if any(r["status"]=="HARNESS_ERROR" for r in results) else 0)
