"""初始化向导：一次性把环境理顺

做七件事：
    1. 检查运行环境（Python / 依赖 / Node / 浏览器）
    2. 找到微信数据目录、确认账号（多账号必须显式 --account）
    3. 定下数据总目录（--auto 时落在 ~/wechat-daily，绝不落进技能包）
    4. 取密钥（存到 secrets/all_keys.json，跟随目录走）
    5. 全量解密（出日报要用 message 库，不能只解联系人）
    6. 让你挑要监控的群（工具只推荐，不默认）
    7. 定时时间

用法：
    python tools/setup.py                    # 交互式（每步有默认值，回车即接受）
    python tools/setup.py --auto --groups "群A,群B"          # 全自动，落 ~/wechat-daily
    python tools/setup.py --auto --account 1 --groups "群A,群B" --root "D:/wechat-daily"
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(BASE, "tools")
sys.path.insert(0, os.path.join(BASE, "lib"))
sys.path.insert(0, TOOLS)

from wechat_data import settings  # noqa: E402

PY = sys.executable


# ---------------------------------------------------------------- 交互与中止

def is_interactive() -> bool:
    """有没有真人坐在终端前

    定时任务、管道、CI 里 stdin 不是 tty，`input()` 会抛 EOFError。
    裸 input 的后果是吐一屏 traceback、退出码 1、配置一个字没写——
    现场也看不出到底缺哪个参数。
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


class SetupAbort(RuntimeError):
    """非交互环境下缺必填参数：明确停下，不猜默认值"""


def ask_required(prompt: str, *, hint: str = "", default_on_empty: str | None = None) -> str:
    """必须由人回答的输入：非交互或读到 EOF 一律中止，绝不猜。

    `default_on_empty` 只对"人按了回车"生效（真终端下 input() 返回空串）；
    读到 EOF 说明根本没人，此时**不能**拿它顶包——Windows 上 `< /dev/null` 映射到 NUL，
    是个字符设备，`isatty()` 会误报成终端，只能靠 EOF 这一步兜住。
    """
    if not is_interactive():
        raise SetupAbort(hint or "需要人工输入")
    try:
        return input(prompt).strip() or (default_on_empty or "")
    except EOFError:
        raise SetupAbort(hint or "需要人工输入")


def ask_default(prompt: str, default: str) -> str:
    """有默认值的输入：没人应答就用默认值，不打断自动化"""
    if not is_interactive():
        print(f"{prompt}{default}    ← 非交互，用默认值")
        return default
    try:
        return input(prompt).strip() or default
    except EOFError:
        print(f"{prompt}{default}    ← 读到 EOF，用默认值")
        return default


def abort_hint(e: SetupAbort) -> int:
    """把"缺参数"翻译成一条能直接复制的命令"""
    print("\n" + "=" * 60)
    print("  无法在非交互环境继续：%s" % e)
    print("=" * 60)
    print("把缺的参数补上再跑，下面这行可以直接复制：\n")
    print('  %s tools/setup.py --auto --groups "群名1,群名2" --root "%%USERPROFILE%%\\wechat-daily"'
          % PY)
    print("\n只差账号时加 --account <wxid 片段或序号>；只差目录时加 --root <目录>。")
    return 2


# ---------------------------------------------------------------- 环境检查

def check_env():
    print("\n[1/7] 检查运行环境")
    ok = True
    v = sys.version_info
    if v >= (3, 11):
        print(f"      Python  {v.major}.{v.minor}.{v.micro}  OK")
    else:
        print(f"      Python  {v.major}.{v.minor}  版本过低，需要 3.11+（完整 Windows 兼容范围需另行验证）")
        ok = False
    try:
        import cryptography  # noqa: F401
        print("      cryptography  OK（解密用）")
    except ImportError:
        print("      cryptography  缺失 —— 无法解密，请先 pip install cryptography")
        ok = False
    from wechat_data import config as cfgmod
    node = cfgmod.node_exe()
    if node != "node" and os.path.exists(node):
        print(f"      Node    {node}")
    else:
        print("      Node    未找到 —— App 消息（链接/文件/视频号）将无法解析，其余功能正常")
    from render_daily import find_browser
    br = find_browser()
    print(f"      浏览器  {br}" if br else "      浏览器  未找到 —— 只能出 HTML，不能出 PNG")
    return ok


# ---------------------------------------------------------------- 找微信

def detect_wechat_dirs():
    """从微信配置里读数据根目录，再找账号目录"""
    appdata = os.environ.get("APPDATA", "")
    cfg_dir = os.path.join(appdata, "Tencent", "xwechat", "config")
    roots = []
    if os.path.isdir(cfg_dir):
        for ini in glob.glob(os.path.join(cfg_dir, "*.ini")):
            for enc in ("utf-8", "gbk"):
                try:
                    with open(ini, encoding=enc) as f:
                        content = f.read(200).strip()
                    if content and os.path.isdir(content):
                        roots.append(content)
                    break
                except (UnicodeDecodeError, OSError):
                    continue
    accounts = []
    for root in dict.fromkeys(roots):
        for p in glob.glob(os.path.join(root, "xwechat_files", "*", "db_storage")):
            if os.path.isdir(p):
                accounts.append({"root": root, "account": os.path.basename(os.path.dirname(p)),
                                 "db_dir": p.replace("\\", "/")})
    return accounts


def _match_account(token: str, found: list[dict]) -> dict:
    """把 --account 的值解析成一个账号（序号或 wxid 片段）"""
    token = token.strip()
    if token.isdigit():
        i = int(token)
        if 1 <= i <= len(found):
            return found[i - 1]
        raise SetupAbort(f"--account {token} 超出范围（1-{len(found)}）")

    hits = [a for a in found if token.lower() in a["account"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SetupAbort(f"--account {token} 没有匹配到任何账号")
    raise SetupAbort(f"--account {token} 匹配到 {len(hits)} 个账号，请写更完整的 wxid")


def pick_account(args):
    print("\n[2/7] 定位微信数据")
    if args.db_dir:
        d = args.db_dir.replace("\\", "/")
        print(f"      使用指定目录: {d}")
        return {"db_dir": d, "account": os.path.basename(os.path.dirname(d)),
                "root": os.path.dirname(os.path.dirname(os.path.dirname(d)))}

    found = detect_wechat_dirs()
    if not found:
        print("      没有自动找到。请确认微信已登录过，或用 --db-dir 手动指定")
        return None
    if len(found) == 1:
        print(f"      只发现 1 个账号：{found[0]['account']}")
        print(f"          {found[0]['db_dir']}")
        return found[0]

    print(f"      找到 {len(found)} 个账号：")
    for i, a in enumerate(found, 1):
        print(f"        {i}) {a['account']}   {a['db_dir']}")

    # 指定了就直接用（交互与否都一样）
    if args.account:
        acct = _match_account(args.account, found)
        print(f"      按 --account 选用：{acct['account']}")
        return acct

    # 多账号时**绝不默认**：选错账号不是报错，是天天出另一个人的日报，
    # 而且日报看起来完全正常——比 R1 那种丢数据更难发现。
    if args.auto or not is_interactive():
        raise SetupAbort(
            f"发现 {len(found)} 个微信账号，必须用 --account 指定用哪个（见上面清单）")

    while True:
        raw = ask_required("      选哪个？（回车=1）: ",
                           hint=f"发现 {len(found)} 个微信账号，必须用 --account 指定用哪个",
                           default_on_empty="1")
        try:
            idx = int(raw)
            acct = found[idx - 1]
        except (ValueError, IndexError):
            print(f"      序号必须在 1-{len(found)} 之间")
            continue
        print(f"      已选 {idx}) {acct['account']}   {acct['db_dir']}")
        again = ask_required("      确认请回车，重选输入 n：",
                            hint=f"发现 {len(found)} 个微信账号，必须用 --account 指定用哪个",
                            default_on_empty="y")
        if again.lower() not in ("n", "no"):
            return acct


# ---------------------------------------------------------------- 取密钥

def get_keys(account, cfg):
    print("\n[4/7] 获取密钥")
    secrets = settings.secrets_dir(cfg)
    os.makedirs(secrets, exist_ok=True)
    keys_path = os.path.join(secrets, "all_keys.json")

    # 先看有没有现成且还能用的
    if os.path.exists(keys_path):
        try:
            from safe_decrypt import verify_key
            k = json.load(open(keys_path, encoding="utf-8"))
            tried = ok = 0
            for rel, val in k.items():
                if rel.startswith("_"):
                    continue
                src = os.path.join(account["db_dir"], rel.replace("\\", "/"))
                if not os.path.exists(src):
                    continue
                tried += 1
                with open(src, "rb") as f:
                    if verify_key(bytes.fromhex(val["enc_key"]), f.read(4096)):
                        ok += 1
                if tried >= 3:
                    break
            if ok == tried and tried:
                print(f"      已有密钥仍然有效（抽查 {ok}/{tried}），跳过重新提取")
                return keys_path
        except Exception:
            pass

    print("      正在从微信进程提取密钥（需要微信处于登录状态）...")
    r = subprocess.run([PY, os.path.join(TOOLS, "wcdb_key_tool_windows.py"),
                        "extract", "--db-dir", account["db_dir"], "--output", keys_path],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print(f"      {line}")
    if not os.path.exists(keys_path):
        print("      提取失败。请确认微信已登录，然后重试")
        return None
    return keys_path


# ---------------------------------------------------------------- 解密

def decrypt_all(account, keys_path, cfg):
    """全量解密。

    不能只解 contact.db——选群要按"最近有消息"排序、要算近 7 天信息密度，
    这些都要读 message/session 库；出日报更是必须全量。第一次就在向导里做完，
    用户拿到配置时数据库已经是可用的，不用再记一条手动命令。
    """
    print("\n[5/7] 解密数据库（选群要读消息；首次约 1-3 分钟）")
    print("      下面是解密日志，结束后会自动继续 ...")
    out = settings.decrypted_dir(cfg)
    os.makedirs(out, exist_ok=True)
    r = subprocess.run([PY, os.path.join(TOOLS, "safe_decrypt.py"),
                        "--db-dir", account["db_dir"],
                        "--keys", keys_path, "--output", out])
    if r.returncode != 0:
        print("      [warn] 有库没解成功，选群结果可能不完整")
    return r.returncode == 0


# ---------------------------------------------------------------- 选群

def _match_token(token, resolver, shown):
    """把一个输入片段解析成群列表

    支持两种写法：
      · 纯数字 → 上面列表里的编号
      · 其它   → 当作群名关键词，在**全部群**里搜（不只前 15 个）
    """
    token = token.strip()
    if not token:
        return []

    if token.isdigit():
        i = int(token)
        if 1 <= i <= len(shown):
            return [shown[i - 1][1]]
        print(f"      编号 {i} 超出范围（1-{len(shown)}）")
        return []

    hits = resolver.search(token, kind="group")
    if not hits:
        print(f"      没有找到名称含「{token}」的群")
        return []
    if len(hits) == 1:
        return hits[0:1]

    # 多个匹配：列出来让用户挑，避免选错群
    print(f"      「{token}」匹配到 {len(hits)} 个群：")
    for j, c in enumerate(hits[:8], 1):
        print(f"        {j}) {c.name}")
    if len(hits) > 8:
        print(f"        …另有 {len(hits) - 8} 个，请把名字写更完整些")
    raw = input("      选第几个？（回车=跳过）: ").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= min(8, len(hits))):
        print("      已跳过")
        return []
    return [hits[int(raw) - 1]]


def _density(reader, chat, days: int = 7) -> dict:
    """近 N 天的信息密度画像

    选群时要看的是"这个群有没有人互相说话"，不是"它多久没停过"。
    公告群、优惠券群永远排在最前面，因为它们的号从不休息——只看最近消息时间
    就会把人往错的方向推。这里量的是文字量、人数和对话轮次。
    """
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        msgs = reader.fetch(chat, start, end)
    except Exception:
        return {}
    if not msgs:
        return {"total": 0, "people": 0, "chars": 0, "turns": 0, "days": days}
    st = reader.summarize(msgs)
    senders = [m.sender for m in msgs]
    turns = sum(1 for a, b in zip(senders, senders[1:]) if a != b)
    return {"total": st.total, "people": st.unique_senders,
            "chars": st.chars, "turns": turns, "days": days}


def _density_tag(d: dict) -> str:
    """给人看的一句话结论"""
    if not d:
        return "画像不可用"
    if d["total"] == 0:
        return "近 7 天没消息"
    per_day = d["total"] / max(d["days"], 1)
    head = f"{d['total']:>4}条/{d['people']}人/{d['chars']:>5}字/{d['turns']:>3}轮"
    if d["people"] <= 1 and d["turns"] == 0:
        return head + "  ← 单人单向发布，出不了叙事日报"
    if d["turns"] < 5:
        return head + "  ← 几乎没人接话"
    if per_day < 3:
        return head + "  ← 话太少"
    return head + "  ← 有人来回说，合适"


def pick_chats(args, cfg):
    print("\n[6/7] 选择要出日报的群")
    from wechat_data import ChatResolver, MessageReader
    try:
        resolver = ChatResolver(settings.decrypted_dir(cfg))
    except FileNotFoundError:
        print("      联系人库不可用，跳过选群（可稍后手工编辑 config.json）")
        return []

    groups = resolver.groups()
    print(f"      共有 {len(groups)} 个群，按最近消息排序中...")
    rows = []
    try:
        with MessageReader(settings.decrypted_dir(cfg)) as reader:
            for c in groups:
                if not reader.has_messages(c):
                    continue
                last = reader.last_message_time(c)
                if last:
                    rows.append((last, c))
    except FileNotFoundError:
        pass
    rows.sort(key=lambda x: x[0], reverse=True)

    # 命令行直接指定群名
    if args.groups:
        names = [x.strip() for x in args.groups.split(",") if x.strip()]
        picked = []
        for n in names:
            for c in _match_token(n, resolver, rows or [("", resolver.get(n))]):
                picked.append(c)
        return [{"name": c.name, "username": c.username, "kind": "group",
                 "daily": True, "theme": "magazine"} for c in picked]

    if not rows:
        print("      没有找到有消息的群")
        return []

    show = rows[:15]
    dens = {}
    try:
        with MessageReader(settings.decrypted_dir(cfg)) as reader:
            for _last, c in show:
                dens[c.username] = _density(reader, c)
    except FileNotFoundError:
        pass

    print("      近 7 天信息密度（条/人/字/轮）——挑有人来回说话的那种群：")

    # 推荐排序：按对话轮次与字数，不按"谁最近发得多"——优惠券群会永远赢。
    # 只是打星，不代替人决定。
    ranked = sorted(
        show, key=lambda r: (dens.get(r[1].username, {}).get("turns", 0),
                             dens.get(r[1].username, {}).get("chars", 0)),
        reverse=True)
    recommend = {c.username for _last, c in ranked[:3]}

    for i, (last, c) in enumerate(show, 1):
        star = "  ★推荐" if c.username in recommend else ""
        print(f"        {i:2d}) {last:%m-%d %H:%M}  {c.name}{star}")
        print(f"            {_density_tag(dens.get(c.username, {}))}")

    print("\n      怎么选？（监控哪些群由你决定，向导不会替你挑）")
    print("        · 编号：1,3,5")
    print("        · 群名：示例群（写一部分即可，会在全部群里搜索）")
    print("        · 也可混合：1,示例群,3")
    print("        · 直接回车：这次先不选")

    if args.auto or not sys.stdin.isatty():
        # 定时任务里没有终端，不能拿"默认值"冒充用户的选择
        print("\n      当前不是交互终端，需要明确指定群名：")
        print('        python tools/setup.py --groups "群名1,群名2"')
        print("      想用上面的编号挑，就在终端窗口里重跑一次（不要加 --auto）。")
        return []

    picked = []
    seen = set()
    attempted = False   # 用户是否真的输入过内容
    while True:
        prompt = "      要监控的群 > " if not picked else "      还要加吗（回车结束）> "
        try:
            raw = input(prompt).strip()
        except EOFError:
            break
        if not raw:
            break
        attempted = True
        for tok in raw.replace("，", ",").split(","):
            for c in _match_token(tok, resolver, show):
                if c.username in seen:
                    print(f"      = {c.name} 已在列表里")
                    continue
                seen.add(c.username)
                picked.append(c)
                print(f"      + {c.name}")

    if not picked:
        if attempted:
            # 输入过但一个都没匹配上——多半是名字写错了，不要静默换成默认群
            print("\n      没有选中任何群（名字可能写错了），本次先跳过")
        else:
            print("\n      没有选择任何群。上面带 ★ 的是密度最好的 3 个，仅供参考。")
        return []

    print(f"\n      最终选中 {len(picked)} 个群")
    return [{"name": c.name, "username": c.username, "kind": "group",
             "daily": True, "theme": "magazine"} for c in picked]


# ---------------------------------------------------------------- 路径与定时

def default_data_root() -> str:
    """`--auto` 的缺省落点：用户目录，**不是技能包**

    技能包要能被拷来拷去，里面绝不能长出 decrypted/（0.8GB 明文聊天记录）和
    secrets/（明文密钥）。曾经 `--auto` 用 BASE，结果是"一键初始化"把整个包
    从 117KB 灌到 848MB，拷给谁就等于把全部聊天记录拷给谁。
    """
    return os.path.join(os.path.expanduser("~"), "wechat-daily")


def pick_paths(args, cfg):
    """先定路径——必须在解密之前，否则会解到旧目录去"""
    print("\n[3/7] 目录")
    root = args.root
    if not root:
        if args.auto:
            root = default_data_root()
            print(f"      未指定 --root，自动落在用户目录：{root}")
        else:
            # 非交互时绝不回落到 BASE——那等于把明文解进技能包里
            d = ask_required(f"      数据总目录（回车={BASE}）: ",
                             hint="非交互环境必须用 --root 指定数据总目录")
            root = d or BASE
    root = os.path.abspath(root)

    cfg["paths"].update({
        "root": root,
        "decrypted": os.path.join(root, "decrypted"),
        "data": os.path.join(root, "data"),
        "reports": os.path.join(root, "reports"),
        "secrets": os.path.join(root, "secrets"),
        "logs": os.path.join(root, "logs"),
    })
    for k in ("decrypted", "data", "reports", "secrets", "logs"):
        os.makedirs(cfg["paths"][k], exist_ok=True)
    print(f"      总目录  {root}")
    print(f"      明文库  {cfg['paths']['decrypted']}    ← 含聊天原文，勿同步/勿外传")
    print(f"      密钥    {cfg['paths']['secrets']}")
    print(f"      归档    {cfg['paths']['data']}")
    print(f"      日报    {cfg['paths']['reports']}")
    return cfg


def pick_schedule(args, cfg):
    print("\n[7/7] 时间")
    # 时间不是必填项，非交互时用默认值即可，不必打断自动化流程
    s = ask_default("      每天几点采集？逗号分隔（回车=08:00,20:00）: ",
                    "08:00,20:00")
    cfg["collect"]["schedule"] = [x.strip() for x in s.split(",") if x.strip()]
    t = ask_default("      每天几点出日报？（回车=08:30）: ", "08:30")
    cfg["compose"]["time"] = t or "08:30"
    print(f"      采集    {', '.join(cfg['collect']['schedule'])}")
    print(f"      日报    {cfg['compose']['time']}")
    return cfg


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="微信群日报 · 初始化向导")
    ap.add_argument("--auto", action="store_true",
                    help="自动完成环境/路径/密钥/解密/定时；选群仍需 --groups 指定（不会替你选）")
    ap.add_argument("--db-dir", help="微信 db_storage 路径")
    ap.add_argument("--groups", help="要监控的群名，逗号分隔")
    ap.add_argument("--account", help="多账号时指定用哪个（wxid 片段或序号 1/2/…）")
    ap.add_argument("--root", help="数据总目录")
    args = ap.parse_args()

    print("=" * 60)
    print("  微信群日报 · 初始化")
    print("  将依次完成：环境检查 → 定位微信 → 定路径 → 取密钥 → 全量解密 → 选群 → 定时")
    print("=" * 60)

    if not check_env():
        print("\n环境不满足，请先解决上面的问题")
        return 1

    cfg = settings.load()
    try:
        account = pick_account(args)
    except SetupAbort as e:
        return abort_hint(e)
    if not account:
        return 2
    cfg["wechat"].update({
        "db_dir": account["db_dir"],
        "account": account["account"],
        "data_root": account.get("root", ""),
    })

    # 路径必须先定，后面解密才有正确落点
    try:
        cfg = pick_paths(args, cfg)
    except SetupAbort as e:
        return abort_hint(e)

    keys_path = get_keys(account, cfg)
    if not keys_path:
        print("\n未能获取密钥，流程中断")
        return 3

    decrypt_all(account, keys_path, cfg)
    chats = pick_chats(args, cfg)
    if not chats:
        # 没有群 = 出不了任何日报，这不算"初始化完成"，必须说清怎么补救
        print("\n" + "=" * 60)
        print("  初始化未完成：没有选中任何群")
        print("=" * 60)
        print("配置已写入，但监控名单是空的，这种情况下跑不出日报。补救方式：")
        print("  1) 用群名直接指定（会重新解密并写入配置）：")
        print('     %s tools/setup.py --groups "群名1,群名2"' % PY)
        print("  2) 或手工编辑 config.json 的 chats 段，填入群名与 username")
        print("\n（config.json 已保存在 %s，路径与密钥都不用重来）"
              % settings.CONFIG_PATH)
        cfg["chats"] = []
        settings.save(cfg)
        return 4

    cfg["chats"] = chats
    try:
        cfg = pick_schedule(args, cfg)
    except SetupAbort as e:
        return abort_hint(e)

    path = settings.save(cfg)
    print("\n" + "=" * 60)
    print("  初始化完成")
    print("=" * 60)
    print(settings.summary(cfg))
    print(f"\n配置已写入: {path}")
    print("\n下一步（解密已在上一步完成，这里不用再解）：")
    print("  1) 试采一天： python fetch.py archive --config --date %s"
          % (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
    print("  2) 查看状态： python fetch.py status")
    print("  3) 出首份日报： python fetch.py export --chat \"%s\" --date %s --format text"
          % (chats[0]["name"], (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")))
    print("     （读完后按 references/writing-spec.md 写 story.json，再 render_daily.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
