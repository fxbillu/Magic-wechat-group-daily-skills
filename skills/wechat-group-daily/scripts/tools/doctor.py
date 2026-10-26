"""入职体检 —— 每次被唤醒先跑这个

七项：Python 版本 / 依赖 / 微信是否在跑 / 配置与路径 / 密钥是否仍有效 /
解密产物是否新鲜 / 有没有浏览器与 Node。
默认只看不动手；加 `--fix` 会自动补上「能自动补的」：装依赖、取密钥、重新解密。

**配置和选群永远不自动做**——监控哪些群是人的决定，工具只负责把候选和画像摆出来。

退出码（约定好，方便上层判断该跳到哪一步）：
   0  就绪，可以直接出报
  10  缺 Python 依赖（可 --fix 安装）
  11  尚未初始化（跑 tools/setup.py）
  12  配置里的路径失效（重跑 tools/setup.py）
  13  没有监控群（跑 tools/setup.py 选群）
  14  密钥缺失或失效（可 --fix 重新提取，需微信在运行）
  15  解密产物过期（可 --fix 重新解密）
  16  需要取密钥但微信没运行

用法：
    python tools/doctor.py            # 体检
    python tools/doctor.py --fix      # 体检并自动补依赖/密钥/解密
"""
import argparse
import importlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(BASE, "lib"))
sys.path.insert(0, HERE)

PY = sys.executable
PAGE = 4096

from wechat_data import settings  # noqa: E402

# 必需：缺了直接干不了活
REQUIRED_DEPS = [
    ("cryptography", "解密微信数据库"),
]
# 可选：缺了降级，不影响主线
OPTIONAL_DEPS = [
    ("PIL", "裁掉 PNG 底部空白（缺了图会留白）"),
    ("pilk", "语音转 silk（语音链路）"),
    ("faster_whisper", "语音转文字（语音链路）"),
]

EXIT_READY = 0
EXIT_DEPS = 10
EXIT_NOT_INIT = 11
EXIT_BAD_PATHS = 12
EXIT_NO_CHATS = 13
EXIT_KEYS = 14
EXIT_STALE = 15
EXIT_WEIXIN_DOWN = 16


# ---------------------------------------------------------------- 各项检查

def check_python() -> tuple[bool, str]:
    v = sys.version_info
    txt = f"{v.major}.{v.minor}.{v.micro}  ({sys.executable})"
    if v < (3, 11):
        return False, txt + "  版本过低，需要 3.11+（完整 Windows 兼容范围需另行验证）"
    return True, txt


def check_deps() -> tuple[list[str], list[str]]:
    """返回 (缺的必需包, 缺的可选包)"""
    def missing(names):
        out = []
        for name, _why in names:
            try:
                importlib.import_module(name)
            except ImportError:
                out.append(name)
        return out
    return missing(REQUIRED_DEPS), missing(OPTIONAL_DEPS)


def weixin_info() -> tuple:
    """(pid, 版本)；没运行则是 (None, None)"""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Weixin.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, encoding="gbk", errors="ignore")
    except OSError:
        return None, None
    for line in r.stdout.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "weixin.exe":
            try:
                return int(parts[1]), None
            except ValueError:
                return -1, None
    return None, None


def check_config() -> dict:
    """{'state': ok|not_init|no_paths|bad_paths, 'cfg':..., 'detail':..., 'chats': n}"""
    res = {"state": "ok", "cfg": {}, "detail": "", "chats": 0}
    if not settings.exists():
        res["state"] = "not_init"
        res["detail"] = "没有 config.json（这个包出厂就不带，属正常）"
        return res

    cfg = settings.load()
    res["cfg"] = cfg
    root = settings.get(cfg, "paths.root")
    if not root:
        res["state"] = "no_paths"
        res["detail"] = "config.json 存在但 paths 是空的（大概是直接拷了模板）"
        return res

    # 路径失效判定：看 root 的父目录还在不在。
    # 只判「非空」不够——换台机器后旧路径还写着，会静默读写上一个人的数据。
    parent = os.path.dirname(os.path.abspath(root))
    if not os.path.isdir(parent):
        res["state"] = "bad_paths"
        res["detail"] = f"数据总目录的上级不存在：{parent}（这份配置是别处带来的）"
        return res

    db_dir = settings.source_db_dir(cfg)
    if not db_dir or not os.path.isdir(db_dir):
        res["state"] = "bad_paths"
        res["detail"] = f"微信数据目录不存在：{settings.get(cfg, 'wechat.db_dir') or '(空)'}"
        return res

    res["chats"] = len(settings.active_chats(cfg))
    res["detail"] = f"数据在 {root}"
    return res


def check_keys(cfg: dict) -> dict:
    """抽查密钥是否仍然有效（微信可能已经换了一部分）"""
    res = {"ok": False, "total": 0, "valid": 0, "path": "", "detail": ""}
    kpath = settings.keys_file(cfg)
    res["path"] = kpath
    if not os.path.exists(kpath):
        res["detail"] = "密钥文件不存在"
        return res
    try:
        keys = json.load(open(kpath, encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        res["detail"] = f"密钥文件读不了：{e}"
        return res

    from safe_decrypt import verify_key
    db_dir = settings.source_db_dir(cfg)
    bad = []
    for rel, info in keys.items():
        if rel.startswith("_"):
            continue
        res["total"] += 1
        src = os.path.join(db_dir, rel.replace("\\", "/"))
        if not os.path.exists(src):
            bad.append(rel + "(源缺失)")
            continue
        try:
            with open(src, "rb") as f:
                page1 = f.read(PAGE)
            if verify_key(bytes.fromhex(info["enc_key"]), page1):
                res["valid"] += 1
            else:
                bad.append(rel)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{rel}({type(e).__name__})")
    res["ok"] = res["total"] > 0 and not bad
    res["detail"] = (f"{res['valid']}/{res['total']} 有效" if res["ok"]
                     else f"{res['valid']}/{res['total']} 有效，失效 {len(bad)}："
                          + "、".join(bad[:3]))
    return res


def check_fresh(cfg: dict) -> dict:
    from wechat_data import guard
    dec = settings.decrypted_dir(cfg)
    if not os.path.isdir(dec):
        return {"ok": False, "detail": "还没解密过（decrypted/ 不存在）", "reason": "missing"}
    r = guard.check(dec)
    detail = (f"{r['age_hours']:.1f} 小时前解密，数据是最新的"
              if r.get("fresh") and r.get("age_hours") is not None
              else (r.get("reason") or "需要重新解密"))
    return {"ok": bool(r.get("fresh")), "detail": detail, "raw": r}


def check_browser() -> str | None:
    from render_daily import find_browser
    return find_browser()


def check_node() -> str:
    """App 消息（链接/文件/视频号）要靠 Node 解压那段 zstd"""
    import shutil
    p = shutil.which("node")
    if p:
        return p
    try:
        from wechat_data.config import node_exe
        c = node_exe()
        if c and c != "node" and os.path.exists(c):
            return c
    except Exception:  # noqa: BLE001
        pass
    return "没找到（链接/文件/视频号消息会降级成占位）"


# ---------------------------------------------------------------- 修复动作

def fix_deps(pkgs: list[str]) -> bool:
    if not pkgs:
        return True
    print(f"      正在安装：{' '.join(pkgs)} ...")
    for pkg in pkgs:
        r = subprocess.run([PY, "-m", "pip", "install", "-q", pkg],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"      安装 {pkg} 失败：{(r.stderr or r.stdout).strip()[-200:]}")
            print(f"      可手动执行：{PY} -m pip install {pkg}")
            return False
        print(f"      {pkg} 装好了")
    return True


def fix_keys(cfg: dict) -> bool:
    kpath = settings.keys_file(cfg)
    os.makedirs(os.path.dirname(kpath), exist_ok=True)
    db_dir = settings.source_db_dir(cfg)
    print(f"      正在从微信进程取密钥 → {kpath}")
    r = subprocess.run([PY, os.path.join(HERE, "wcdb_key_tool_windows.py"),
                        "extract", "--db-dir", db_dir, "--output", kpath])
    return r.returncode == 0 and os.path.exists(kpath)


def fix_decrypt(cfg: dict) -> bool:
    print("      正在重新解密（首次或数据变动后需要 1-3 分钟）")
    r = subprocess.run([PY, os.path.join(HERE, "safe_decrypt.py"),
                        "--db-dir", settings.source_db_dir(cfg),
                        "--keys", settings.keys_file(cfg),
                        "--output", settings.decrypted_dir(cfg)])
    return r.returncode == 0


# ---------------------------------------------------------------- 汇总

def run_checks() -> dict:
    py_ok, py_txt = check_python()
    need, opt = check_deps()
    pid, _ = weixin_info()
    cfgres = check_config()
    cfg = cfgres["cfg"]

    keys = check_keys(cfg) if cfgres["state"] == "ok" else None
    fresh = check_fresh(cfg) if cfgres["state"] == "ok" else None
    browser = check_browser()
    node = check_node()

    return {"py_ok": py_ok, "py_txt": py_txt, "need": need, "opt": opt,
            "weixin_pid": pid, "cfg": cfgres, "keys": keys, "fresh": fresh,
            "browser": browser, "node": node}


def verdict(s: dict) -> tuple[int, str, list[str]]:
    """(退出码, 一句话结论, 下一步命令列表)"""
    sc = "python tools/setup.py"
    if not s["py_ok"]:
        # 版本不够是硬门槛，先于一切
        return EXIT_DEPS, "Python 版本不够，后面都跑不了", [
            "装一个 Python 3.11，然后用它的绝对路径重跑本自检"]
    if s["need"]:
        return EXIT_DEPS, f"缺必需的 Python 依赖：{'、'.join(s['need'])}", [
            f"{PY} tools/doctor.py --fix",
            f"或手动：{PY} -m pip install {' '.join(s['need'])}"]
    if s["cfg"]["state"] == "not_init":
        return EXIT_NOT_INIT, "这个包还没在这台机器上初始化", [
            sc,
            "向导会取密钥、解密、然后让你挑群（不会替你选）"]
    if s["cfg"]["state"] in ("no_paths", "bad_paths"):
        return EXIT_BAD_PATHS, "配置里的路径对不上这台机器", [
            sc, s["cfg"]["detail"]]
    if not s["keys"]["ok"]:
        if not s["weixin_pid"]:
            return EXIT_WEIXIN_DOWN, "密钥不可用，而微信没在运行，取不到新密钥", [
                "先登录并打开微信，然后再跑：",
                f"{PY} tools/doctor.py --fix"]
        return EXIT_KEYS, "密钥缺失或已失效（微信会定期换密钥）", [
            f"{PY} tools/doctor.py --fix"]
    if not s["fresh"]["ok"]:
        return EXIT_STALE, "解密产物该刷新了（微信一直在写库，这是常态）", [
            f"{PY} tools/doctor.py --fix      # 约 30 秒",
            "或手动跑 tools/safe_decrypt.py"]
    if s["cfg"]["chats"] == 0:
        return EXIT_NO_CHATS, "配置好了，但一个监控群都没有", [
            sc, "向导会列出候选群和近 7 天信息密度，由你决定监控哪些"]
    return EXIT_READY, "一切就绪，可以出报了", []


def report(s: dict, code: int, line: str, steps: list[str]) -> None:
    print("=" * 60)
    print("  微信群日报 · 自检")
    print("=" * 60)

    print(f"[1] Python     {'OK  ' if s['py_ok'] else '不足'} {s['py_txt']}")
    d = "、".join(f"{n} 缺" for n in s["need"]) or "必需齐全"
    o = ("，可选缺 " + "、".join(s["opt"])) if s["opt"] else ""
    print(f"[2] 依赖       {d}{o}")
    print(f"    Node       {s['node']}")
    print(f"[3] 微信       {'运行中 pid=%s' % s['weixin_pid'] if s['weixin_pid'] else '没运行（只在取密钥时需要它）'}")
    print(f"[4] 配置       {s['cfg']['detail'] or 'OK'}")
    if s["keys"] is not None:
        print(f"[5] 密钥       {'OK  ' if s['keys']['ok'] else '不可用'} {s['keys']['detail']}")
        print(f"[6] 解密产物   {'OK  ' if s['fresh']['ok'] else '不可用'} {s['fresh']['detail']}")
    else:
        print("[5] 密钥       —（等初始化后才有）")
        print("[6] 解密产物   —")
    print(f"[7] 出图       {('浏览器 ' + s['browser']) if s['browser'] else '没找到 Edge/Chrome，只能出 HTML'}")

    print("-" * 60)
    print(f"结论：{line}")
    if steps:
        print("下一步：")
        for i, cmd in enumerate(steps, 1):
            print(f"  {i}) {cmd}")
    elif s["cfg"]["chats"]:
        print(f"监控群 {s['cfg']['chats']} 个；正常流程见 SKILL.md 第 2 步起。")
    print(f"（返回码 {code}）")


def main() -> int:
    ap = argparse.ArgumentParser(description="微信群日报 · 自检 / 入职体检")
    ap.add_argument("--fix", action="store_true",
                    help="自动补依赖、取密钥、重新解密（不会改配置、不会选群）")
    args = ap.parse_args()

    s = run_checks()
    code, line, steps = verdict(s)

    if args.fix:
        acted = False
        # 顺序不能乱：依赖 → 密钥 → 解密，前一步不成立后一步也做不成
        if s["need"]:
            acted = True
            fix_deps(s["need"])
            s = run_checks()
        if s["cfg"]["state"] == "ok" and s["keys"] and not s["keys"]["ok"]:
            if s["weixin_pid"]:
                acted = True
                fix_keys(s["cfg"]["cfg"])
                s = run_checks()
            else:
                print("\n[fix] 取密钥需要微信在运行，先打开微信再跑一次。")
        if (s["cfg"]["state"] == "ok" and s["keys"] and s["keys"]["ok"]
                and s["fresh"] and not s["fresh"]["ok"]):
            acted = True
            fix_decrypt(s["cfg"]["cfg"])
            s = run_checks()
        if acted:
            print()
            code, line, steps = verdict(s)

    report(s, code, line, steps)
    return code


if __name__ == "__main__":
    sys.exit(main())
