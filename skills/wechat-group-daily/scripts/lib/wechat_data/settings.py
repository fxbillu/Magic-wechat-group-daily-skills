"""配置中心：唯一的配置入口

所有路径、监控的群、定时策略都集中在这一个 `config.json` 里，
换电脑只需要改这个文件（或重跑 `tools/setup.py`）。

配置落点：包外用户目录，或 WECHAT_DAILY_CONFIG 指定的文件。

设计原则：
- 业务入口缺少配置时必须停下；阅读服务另外提供不落盘的未就绪状态
- 旧 load/default_config 的兼容行为仍待 T2 初始化修复，不能作为就绪证据
- 写入用「临时文件 + 替换」，避免写一半崩掉留下坏配置
- 密钥路径跟随 `paths.secrets`，实现「整体搬迁」要求
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def config_path() -> str:
    """Discover personal configuration without writing into the Skill package.

    An explicit path is useful for isolated runs. Existing package-local config
    is not silently imported; the initialization migration belongs to T2.
    """
    explicit = os.environ.get("WECHAT_DAILY_CONFIG")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return os.path.join(base, "WeChatGroupDaily", "config.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "wechat-group-daily", "config.json")


CONFIG_PATH = config_path()
CONFIG_VERSION = 1

# 「还没初始化」单独的退出码，方便定时任务区分「没配好」和「跑失败了」
EXIT_NOT_INITIALIZED = 6

INIT_HINT = """尚未初始化：找不到配置文件
    {path}

这个技能包出厂时不带配置——每个人的微信路径、要监控的群都不一样。
先跑一遍自检，它会列出还缺什么、该按哪个顺序补：

    cd {root}
    python tools/doctor.py

自检返回 11 就说明是这一步；随后跑初始化向导（探测微信、取密钥、解密、让你挑群）：

    python tools/setup.py

向导跑完会生成本机的 config.json，之后的命令才能用。"""


def default_config() -> dict:
    """默认配置：路径都在项目内，等价于改造前的行为"""
    return {
        "version": CONFIG_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "wechat": {
            "data_root": "",
            "db_dir": "",
            "account": "",
        },
        "paths": {
            "root": ROOT,
            "decrypted": os.path.join(ROOT, "decrypted"),
            "data": os.path.join(ROOT, "data"),
            "reports": os.path.join(ROOT, "reports"),
            "secrets": os.path.join(ROOT, "secrets"),
            "logs": os.path.join(ROOT, "logs"),
        },
        "chats": [],
        "collect": {
            "initial_days": 7,
            "overlap_days": 1,
            "max_age_hours": 24,
            "schedule": [],
        },
        "compose": {
            "time": "",
            "target_day": "yesterday",
            "theme": "magazine",
            "formats": ["html", "png"],
        },
        "retention": {
            "data_days": 30,
        },
        "degrade": {
            "allow_no_node": True,
            "allow_no_browser": True,
        },
    }


def exists() -> bool:
    return os.path.exists(CONFIG_PATH)


def initialized() -> bool:
    """是否已经在这台机器上初始化过"""
    return exists()


def require() -> dict:
    """取配置。未初始化就停下并指路，绝不拿包内默认路径开工

    为什么不能"没有配置就用默认值"：默认值里的 paths 都算在技能包内部，
    一旦照着它跑，就会在包里建出 data/、reports/、decrypted/，
    把明文聊天记录写进一个本该纯净、要拷来拷去的目录。
    换机场景下更糟：包跟着走了，配置没走，看起来一切正常，
    实际还在读写上一个用户的数据。
    """
    if not exists():
        print(INIT_HINT.format(path=CONFIG_PATH, root=ROOT), file=sys.stderr, flush=True)
        raise SystemExit(EXIT_NOT_INITIALIZED)
    cfg = load()
    if not get(cfg, "paths.root"):
        print("配置文件存在，但 paths 还没填（大概是直接拷了 config.example.json）。\n"
              "请跑一次初始化向导，让它按这台机器的实际情况写好：\n\n"
              f"    cd {ROOT}\n"
              "    python tools/setup.py\n", file=sys.stderr, flush=True)
        raise SystemExit(EXIT_NOT_INITIALIZED)
    return cfg


def load() -> dict:
    """读配置；不存在则返回默认（不落盘）"""
    if not exists():
        return default_config()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return default_config()
    # 补齐缺失字段，兼容旧配置
    base = default_config()
    _merge_missing(cfg, base)
    return cfg


def _merge_missing(target: dict, source: dict) -> None:
    for k, v in source.items():
        if k not in target:
            target[k] = v
        elif isinstance(v, dict) and isinstance(target.get(k), dict):
            _merge_missing(target[k], v)


def save(cfg: dict) -> str:
    """原子写入配置"""
    cfg["version"] = CONFIG_VERSION
    cfg.setdefault("updated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    d = os.path.dirname(CONFIG_PATH)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json.tmp", dir=d)
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return CONFIG_PATH


def get(cfg: dict, dotted: str, default=None):
    """点号路径取值：get(cfg, "paths.reports")"""
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def ensure_dirs(cfg: dict) -> dict:
    """创建所有配置中的目录"""
    made = []
    for key in ("root", "decrypted", "data", "reports", "secrets", "logs"):
        p = get(cfg, f"paths.{key}")
        if not p:
            continue
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            made.append(p)
    return {"created": made}


# ---------------------------------------------------------------- 路径解析

def decrypted_dir(cfg: dict | None = None) -> str:
    cfg = cfg or load()
    return get(cfg, "paths.decrypted") or os.path.join(ROOT, "decrypted")


def data_dir(cfg: dict | None = None) -> str:
    cfg = cfg or load()
    return get(cfg, "paths.data") or os.path.join(ROOT, "data")


def reports_dir(cfg: dict | None = None) -> str:
    cfg = cfg or load()
    return get(cfg, "paths.reports") or os.path.join(ROOT, "reports")


def secrets_dir(cfg: dict | None = None) -> str:
    cfg = cfg or load()
    return get(cfg, "paths.secrets") or os.path.join(ROOT, "secrets")


def keys_file(cfg: dict | None = None) -> str:
    """密钥文件：优先 secrets/，兼容旧的 tools/all_keys.json

    密钥跟随 secrets 目录，满足「整个目录搬走还能用」的要求。
    """
    cfg = cfg or load()
    new = os.path.join(secrets_dir(cfg), "all_keys.json")
    if os.path.exists(new):
        return new
    legacy = os.path.join(ROOT, "tools", "all_keys.json")
    return new if not os.path.exists(legacy) else legacy


def source_db_dir(cfg: dict | None = None) -> str:
    cfg = cfg or load()
    d = get(cfg, "wechat.db_dir", "")
    if d and os.path.isdir(d):
        return d
    # 回退：从密钥文件的 _db_dir 读
    kf = keys_file(cfg)
    if os.path.exists(kf):
        try:
            with open(kf, encoding="utf-8") as f:
                v = json.load(f).get("_db_dir", "")
            if v and os.path.isdir(v):
                return v
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def migrate_keys(cfg: dict) -> str | None:
    """把旧的 tools/all_keys.json 迁到 secrets/"""
    legacy = os.path.join(ROOT, "tools", "all_keys.json")
    target = os.path.join(secrets_dir(cfg), "all_keys.json")
    if os.path.exists(legacy) and not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(legacy, target)
        return target
    return target if os.path.exists(target) else None


def active_chats(cfg: dict | None = None) -> list:
    """需要出日报的群"""
    cfg = cfg or load()
    return [c for c in (cfg.get("chats") or []) if c.get("daily", True)]



def expected_on(cfg: dict, username: str, target_date: str) -> bool | None:
    """A current follow list alone is not evidence of historical collection scope."""
    from datetime import date
    chat = next((c for c in cfg.get('chats', []) if c.get('username') == username), None)
    if chat is None:
        return None
    if not chat.get('daily', True):
        return False
    effective_from = chat.get('effective_from')
    try:
        if not isinstance(effective_from, str) or len(effective_from) != 10:
            return None
        start = date.fromisoformat(effective_from)
        if start.isoformat() != effective_from:
            return None
        return date.fromisoformat(target_date) >= start
    except ValueError:
        return None


def summary(cfg: dict | None = None) -> str:
    """人类可读的配置摘要，供 CLI 打印"""
    cfg = cfg or load()
    lines = [
        f"配置文件      {CONFIG_PATH}" + ("" if exists() else "（尚未创建，使用默认值）"),
        f"微信数据      {get(cfg, 'wechat.db_dir') or '未设置'}",
        f"解密目录      {decrypted_dir(cfg)}",
        f"归档目录      {data_dir(cfg)}",
        f"日报目录      {reports_dir(cfg)}",
        f"密钥目录      {secrets_dir(cfg)}",
        f"日志目录      {get(cfg, 'paths.logs')}",
        f"监控群        {len(active_chats(cfg))} 个",
    ]
    for c in active_chats(cfg)[:8]:
        lines.append(f"  · {c.get('name')}" + (f"（{c.get('username')}）" if c.get("username") else ""))
    sched = get(cfg, "collect.schedule") or []
    lines.append(f"采集时间      {', '.join(sched) if sched else '未设置'}")
    lines.append(f"日报时间      {get(cfg, 'compose.time') or '未设置'}")
    return "\n".join(lines)
