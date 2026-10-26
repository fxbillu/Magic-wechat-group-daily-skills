"""Read-only reader bootstrap state; it never initializes or repairs data."""
from contextlib import closing
import json
import os
import re
import sqlite3

from . import db, settings


def _text(value, limit=256):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Invalid public text field")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Control characters are not public labels")
    return value or None


def _public_config_fields(cfg: dict) -> tuple[dict, list]:
    """Validate before selecting allowlisted status fields; never echo objects."""
    compose = cfg.get("compose", {})
    chats = cfg.get("chats", [])
    if not isinstance(compose, dict) or not isinstance(chats, list):
        raise ValueError("Invalid public configuration shape")
    trigger = _text(compose.get("time"), 5)
    timezone = _text(compose.get("timezone"), 80)
    target = _text(compose.get("target_day"), 20)
    if trigger and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", trigger):
        raise ValueError("Invalid trigger time")
    if target not in (None, "yesterday"):
        raise ValueError("Unsupported target date rule")
    # T0 checks the identifier shape only. T2/T4 must resolve the chosen zone
    # against the actual host timezone database before using it for scheduling.
    if timezone and not re.fullmatch(
            r"UTC|(?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|"
            r"Europe|Indian|Pacific|Etc)(?:/[A-Za-z0-9_+\-]+){1,2}", timezone):
        raise ValueError("Invalid timezone identifier")
    followed = []
    for chat in chats:
        if not isinstance(chat, dict):
            raise ValueError("Invalid followed group")
        username, name = _text(chat.get("username")), _text(chat.get("name"))
        if not username or not isinstance(chat.get("daily", True), bool):
            raise ValueError("Invalid followed group identity")
        if chat.get("daily", True):
            followed.append({"username": username, "name": name or username})
    return {"trigger_time": trigger, "timezone": timezone, "target_rule": target}, followed


def snapshot() -> tuple[dict, dict | None]:
    """Return a redacted public status and a request-local configuration."""
    state = {
        "schema_version": 1,
        "configuration": {"state": "unconfigured"},
        "reading": {
            "available": False,
            "code": "NOT_CONFIGURED",
            "message": "尚未初始化。请在 WorkBuddy 对话中调用微信群日报，完成账号与关注群设置。",
            "retryable": False,
            "next_action": "initialize_in_workbuddy",
        },
        "first_report": {"state": "not_observed", "verified_at": None},
        "schedule": {
            "registered": False,
            "task_id": None,
            "readback_at": None,
            "enabled": None,
            "timezone": None,
            "trigger_time": None,
            "target_rule": None,
            "planned_at": None,
            "target_date": None,
            "last_scheduled_run": None,
        },
        "last_run": None,
        "followed_chats": [],
    }
    if not settings.exists():
        return state, None
    try:
        with open(settings.CONFIG_PATH, encoding="utf-8") as source:
            cfg = json.load(source)
        if not isinstance(cfg, dict) or not isinstance(cfg.get("paths"), dict):
            raise ValueError("Invalid configuration shape")
        paths = cfg["paths"]
        for key in ("root", "data", "reports"):
            path = paths.get(key)
            if not isinstance(path, str) or not path or not os.path.isabs(path):
                raise ValueError("Missing absolute data paths")
            package = os.path.realpath(os.path.dirname(settings.ROOT))
            try:
                inside_package = os.path.commonpath((package, os.path.realpath(path))) == package
            except ValueError:
                inside_package = False  # Different Windows drives cannot overlap.
            if inside_package:
                raise ValueError("Runtime data must be outside the Skill")
        public_schedule, followed = _public_config_fields(cfg)
    except (OSError, ValueError, TypeError):
        state["configuration"]["state"] = "needs_repair"
        state["reading"].update(
            code="CONFIG_INVALID",
            message="配置不可用。请在 WorkBuddy 中检查配置，已有数据不会被此页面改动。",
            next_action="repair_configuration_in_workbuddy",
        )
        return state, None

    state["configuration"]["state"] = "configured"
    state["schedule"]["registered"] = None  # Configuration is not host evidence.
    state["schedule"].update(public_schedule)
    state["followed_chats"] = followed
    if not db.exists(cfg):
        state["reading"].update(
            code="INDEX_NOT_READY",
            message="配置已保存，阅读数据还未就绪。请在 WorkBuddy 中完成首次采集或恢复索引。",
            next_action="prepare_reading_data_in_workbuddy",
        )
        return state, cfg
    try:
        with closing(db.connect_readonly(cfg)):
            pass
    except (OSError, sqlite3.Error):
        state["reading"].update(
            code="INDEX_INVALID",
            message="阅读索引不可用。请在 WorkBuddy 中检查并从已有归档恢复，原有文件未被此页面修改。",
            next_action="repair_reading_index_in_workbuddy",
        )
        return state, cfg
    state["reading"].update(available=True, code=None, message=None,
                            retryable=False, next_action=None)
    return state, cfg


def unavailable_error(state: dict) -> dict:
    reading = state["reading"]
    return {
        "schema_version": 1,
        "error": reading["message"],
        "code": reading["code"],
        "retryable": reading["retryable"],
        "next_action": reading["next_action"],
    }
