"""Reader acceptance tests through shipped commands and real HTTP only."""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "wechat-group-daily"


@contextmanager
def reader(config_text=None, read_only=False):
    """Run an installed copy with an isolated external configuration path."""
    with tempfile.TemporaryDirectory(prefix="daily-reader-") as temp:
        root = Path(temp)
        package = root / "skill"
        shutil.copytree(SKILL, package)
        if read_only:
            for path in package.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            package.chmod(0o555)
        config_path = root / "user-state" / "config.json"
        if config_text is not None:
            config_path.parent.mkdir()
            config_path.write_text(config_text, encoding="utf-8")
        env = dict(os.environ, WECHAT_DAILY_CONFIG=str(config_path),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        log_path = root / "reader.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-B", str(package / "scripts/tools/serve.py"),
                 "--port", "0"], env=env, cwd=root,
                stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    output = log_path.read_text(encoding="utf-8")
                    match = re.search(r"http://127\.0\.0\.1:(\d+)/", output)
                    if match and int(match[1]):
                        yield root, package, config_path, env, match[0].rstrip("/")
                        break
                    if process.poll() is not None:
                        raise AssertionError(f"Reader exited {process.returncode}: {output}")
                    time.sleep(0.03)
                else:
                    raise AssertionError(f"Reader did not start: {output}")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if read_only:
                    package.chmod(0o755)
                    for path in package.rglob("*"):
                        path.chmod(0o755 if path.is_dir() else 0o644)


def get(base, path):
    try:
        response = urlopen(base + path, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read().decode("utf-8")


class ReadinessTest(unittest.TestCase):
    def test_fresh_install_can_read_setup_state_without_creating_user_data(self):
        with reader(read_only=True) as (root, package, config_path, env, base):
            code, page = get(base, "/")
            self.assertEqual(code, 200)
            self.assertIn('id="app"', page)
            code, body = get(base, "/api/status")
            self.assertEqual(code, 200)
            state = json.loads(body)
            self.assertEqual(state["schema_version"], 1)
            self.assertEqual(state["configuration"]["state"], "unconfigured")
            self.assertFalse(state["reading"]["available"])
            self.assertEqual(state["reading"]["code"], "NOT_CONFIGURED")
            self.assertEqual(state["reading"]["next_action"], "initialize_in_workbuddy")
            self.assertIsNone(state["schedule"]["planned_at"])
            self.assertIsNone(state["schedule"]["last_scheduled_run"])
            self.assertNotIn(str(root), body)
            code, body = get(base, "/api/browse")
            self.assertEqual(code, 503)
            self.assertEqual(json.loads(body)["code"], "NOT_CONFIGURED")
            result = subprocess.run(
                [sys.executable, "-B", str(package / "scripts/fetch.py"), "status"],
                env=env, cwd=root, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 6)
            self.assertIn("尚未初始化", result.stderr)
            self.assertFalse(config_path.exists())
            self.assertFalse(config_path.parent.exists())
            for name in ("config.json", "data", "reports", "secrets", "decrypted", "logs"):
                self.assertFalse((package / "scripts" / name).exists(), name)

    def test_saved_configuration_without_index_is_not_ready_and_is_not_repaired_by_get(self):
        with reader() as (root, package, config_path, env, base):
            config_path.parent.mkdir()
            data_root = root / "personal-data"
            config_path.write_text(json.dumps({
                "paths": {key: str(data_root / key) for key in ("root", "data", "reports")},
                "compose": {"time": "08:30", "target_day": "yesterday"},
                "wechat": {"account": "synthetic-private-account"},
                "chats": [{"username": "fixture-team", "name": "示例群", "daily": True}],
            }), encoding="utf-8")
            code, body = get(base, "/api/status")
            state = json.loads(body)
            self.assertEqual(code, 200)
            self.assertEqual(state["configuration"]["state"], "configured")
            self.assertFalse(state["reading"]["available"])
            self.assertEqual(state["reading"]["code"], "INDEX_NOT_READY")
            self.assertIsNone(state["schedule"]["registered"])
            self.assertIsNone(state["schedule"]["readback_at"])
            self.assertEqual(state["schedule"]["trigger_time"], "08:30")
            self.assertNotIn("synthetic-private-account", body)
            self.assertNotIn(str(data_root), body)
            for path in ("/api/browse", "/api/day?date=2026-10-25", "/api/health",
                         "/api/chat?username=fixture-team", "/api/search?q=示例",
                         "/api/entry?date=2026-10-25&username=fixture-team",
                         "/api/messages?date=2026-10-25&username=fixture-team", "/r/example.html"):
                code, body = get(base, path.replace("示例", "%E7%A4%BA%E4%BE%8B"))
                self.assertEqual(code, 503, path)
                self.assertEqual(json.loads(body)["code"], "INDEX_NOT_READY", path)
            self.assertFalse(data_root.exists())

    def test_broken_configuration_is_redacted_and_never_falls_back_to_package_paths(self):
        with reader('{"private": "synthetic-value", broken') as (root, package, config_path, env, base):
            code, body = get(base, "/api/status")
            state = json.loads(body)
            self.assertEqual(code, 200)
            self.assertEqual(state["configuration"]["state"], "needs_repair")
            self.assertEqual(state["reading"]["code"], "CONFIG_INVALID")
            self.assertNotIn("synthetic-value", body)
            self.assertNotIn(str(root), body)
            code, body = get(base, "/api/browse")
            self.assertEqual(code, 503)
            self.assertEqual(json.loads(body)["code"], "CONFIG_INVALID")
            self.assertFalse((package / "scripts/data").exists())

    def test_existing_but_invalid_index_does_not_claim_reading_is_available(self):
        with reader() as (root, package, config_path, env, base):
            config_path.parent.mkdir()
            data = root / "data"
            data.mkdir()
            (data / "index.db").write_bytes(b"this is a synthetic broken index")
            config_path.write_text(json.dumps({"paths": {
                "root": str(root), "data": str(data), "reports": str(root / "reports"),
            }}), encoding="utf-8")
            code, body = get(base, "/api/status")
            self.assertEqual(code, 200)
            state = json.loads(body)
            self.assertFalse(state["reading"]["available"])
            self.assertEqual(state["reading"]["code"], "INDEX_INVALID")
            code, body = get(base, "/api/browse")
            self.assertEqual(code, 503)
            self.assertEqual(json.loads(body)["code"], "INDEX_INVALID")
            self.assertEqual((data / "index.db").read_bytes(), b"this is a synthetic broken index")

    def test_incomplete_index_schema_is_not_migrated_by_any_reader_request(self):
        with reader() as (root, package, config_path, env, base):
            config_path.parent.mkdir()
            data = root / "data"
            data.mkdir()
            index = data / "index.db"
            with closing(sqlite3.connect(index)) as connection:
                connection.executescript("""
                    CREATE TABLE entry(date TEXT, username TEXT);
                    CREATE TABLE message(date TEXT, username TEXT);
                    PRAGMA user_version=1;
                """)
            config_path.write_text(json.dumps({"paths": {
                "root": str(root), "data": str(data), "reports": str(root / "reports"),
            }}), encoding="utf-8")
            before = index.read_bytes()
            code, body = get(base, "/api/status")
            self.assertEqual(code, 200)
            self.assertFalse(json.loads(body)["reading"]["available"])
            for endpoint in ("/api/health", "/api/browse"):
                code, body = get(base, endpoint)
                self.assertEqual(code, 503)
                self.assertEqual(json.loads(body)["code"], "INDEX_INVALID")
            self.assertEqual(index.read_bytes(), before)

    def test_nested_or_invalid_config_fields_never_echo_in_status(self):
        cases = [
            {"compose": {"time": {"token": "synthetic-private-value"}}},
            {"compose": {"timezone": ["synthetic-private-value"]}},
            {"compose": {"target_day": {"token": "synthetic-private-value"}}},
            {"compose": {"time": "99:99"}},
            {"compose": {"target_day": "unknown-rule"}},
            {"chats": [{"username": {"token": "synthetic-private-value"}, "name": "示例群"}]},
            {"chats": [{"username": "fixture-team", "name": ["synthetic-private-value"]}]},
            {"chats": {"token": "synthetic-private-value"}},
        ]
        with reader() as (root, package, config_path, env, base):
            config_path.parent.mkdir()
            for fields in cases:
                with self.subTest(fields=list(fields)):
                    cfg = {"paths": {"root": str(root), "data": str(root / "data"),
                                     "reports": str(root / "reports")}, **fields}
                    config_path.write_text(json.dumps(cfg), encoding="utf-8")
                    code, body = get(base, "/api/status")
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body)["configuration"]["state"], "needs_repair")
                    self.assertEqual(json.loads(body)["reading"]["code"], "CONFIG_INVALID")
                    self.assertNotIn("synthetic-private-value", body)

    def test_public_reindex_restores_reading_without_restarting_the_server(self):
        with reader() as (root, package, config_path, env, base):
            config_path.parent.mkdir()
            data = root / "personal-data" / "data"
            archive_day = data / "2026-10-25"
            archive_day.mkdir(parents=True)
            shutil.copyfile(REPO / "tests/fixtures/sample-archive.json", archive_day / "示例群.json")
            config_path.write_text(json.dumps({
                "paths": {"root": str(data.parent), "data": str(data),
                          "reports": str(data.parent / "reports")},
                "chats": [{"username": "fixture-team", "name": "示例群", "daily": True}],
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(package / "scripts/fetch.py"), "reindex"],
                env=env, cwd=root, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            code, body = get(base, "/api/status")
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(body)["reading"]["available"])
            self.assertIsNone(json.loads(body)["schedule"]["registered"])
            code, body = get(base, "/api/browse")
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)["overview"]["entries"], 1)
            code, body = get(base, "/api/messages?date=2026-10-25&username=fixture-team")
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)["total"], 2)
            self.assertEqual(json.loads(body)["messages"][0]["sender"], "测试成员甲")
            index = data / "index.db"
            with closing(sqlite3.connect(index)) as writer:
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("UPDATE entry SET title='WAL-visible-fixture'")
                writer.commit()
                self.assertTrue(Path(str(index) + "-wal").exists())
                before = index.read_bytes()
                code, body = get(base, "/api/entry?date=2026-10-25&username=fixture-team")
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(body)["title"], "WAL-visible-fixture")
                self.assertEqual(index.read_bytes(), before)
            for unsupported_version in (0, 99):
                with closing(sqlite3.connect(index)) as writer:
                    writer.execute(f"PRAGMA user_version={unsupported_version}")
                    writer.commit()
                before = index.read_bytes()
                code, body = get(base, "/api/status")
                self.assertEqual(code, 200)
                self.assertFalse(json.loads(body)["reading"]["available"])
                code, body = get(base, "/api/health")
                self.assertEqual(code, 503)
                self.assertEqual(json.loads(body)["code"], "INDEX_INVALID")
                self.assertEqual(index.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
