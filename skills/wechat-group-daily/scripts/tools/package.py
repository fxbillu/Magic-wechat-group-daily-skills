"""出厂审计 + 打包

这个包会被拷到别人机器上，所以每次保存版本前都要问三个问题：

1. 有没有夹带本机的东西？（我的配置、密钥、聊天记录、绝对路径、群 id）
2. 该有的在不在？（SKILL.md、写作规范、初始化模板、入口脚本）
3. 拿到新机器上第一次跑，会不会把人带进沟里？（未初始化要明确指路，不是静默开工）

做法是**先暂存再审计**：把该出货的文件复制到临时目录，对那份副本做检查、再压包。
这样开发者的本机 config.json 可以留在原地，不会被误打进去，也不会因为它在而审计永远失败。

用法：
    python tools/package.py                 # 审计"如果现在打包，包里有什么问题"
    python tools/package.py --build         # 审计通过后打 zip 到 dist/

退出码：0 合格；1 不合格（不打包）。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile

PKG = os.path.dirname(os.path.dirname(os.path.dirname(          # 技能包根
    os.path.abspath(__file__))))
NAME = os.path.basename(PKG)

# 出现即说明在夹带本机状态
FORBIDDEN_FILES = {
    "config.json": "本机配置（应由 setup.py 现场生成）",
    ".stamp.json": "解密时间戳",
    "all_keys.json": "明文密钥",
}
FORBIDDEN_DIRS = {
    "data": "归档（含明文聊天记录）",
    "reports": "日报（含明文聊天记录）",
    "decrypted": "解密产物（明文）",
    "secrets": "密钥目录",
    "logs": "运行日志",
    "__pycache__": "字节码",
    "dist": "打包产物",
}

# 不随包出货的文件（开发期本机用，拷出去没意义或有害）
SKIP_NAMES = {"config.json", ".stamp.json", "all_keys.json"}

REQUIRED = [
    "SKILL.md",
    "VERSION",
    "references/writing-spec.md",
    "scripts/fetch.py",
    "scripts/config.example.json",
    "scripts/lib/wechat_data/material.py",
    "scripts/lib/wechat_data/settings.py",
    "scripts/tools/setup.py",
    "scripts/tools/render_daily.py",
    "scripts/tools/check_story.py",
    "scripts/tools/safe_decrypt.py",
    "scripts/tools/package.py",
]

LEAK_PATTERNS = [
    (re.compile(r"C:\\+Users\\+[^\\\s\"']+"), "本机用户目录"),
    (re.compile(r"[A-Z]:\\+xwechat_files"), "本机微信数据目录"),
    (re.compile(r"wxid_[0-9a-z]{6,}"), "微信账号 id"),
    (re.compile(r"\d{6,}@chatroom"), "群 id"),
    # 拆开写，否则这行本身就带着要抓的那个名字，审计会自己抓自己
    (re.compile("符" + "春泳"), "用户名"),
]

TEXT_EXT = {".py", ".js", ".md", ".json", ".txt", ".yaml", ".yml"}


def skip(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    if any(p in FORBIDDEN_DIRS for p in parts):
        return True
    return parts[-1] in SKIP_NAMES or parts[-1].endswith((".pyc", ".exe", ".dll"))


def stage(dst: str) -> int:
    """把该出货的文件复制到暂存目录，返回文件数"""
    n = 0
    for root, dirs, files in os.walk(PKG):
        dirs[:] = [d for d in dirs if d not in FORBIDDEN_DIRS]
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, PKG)
            if skip(rel):
                continue
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
            n += 1
    return n


def audit(root: str) -> list[str]:
    problems: list[str] = []

    for need in REQUIRED:
        if not os.path.exists(os.path.join(root, need)):
            problems.append(f"缺少必需文件：{need}")

    for r, dirs, files in os.walk(root):
        for d in list(dirs):
            if d in FORBIDDEN_DIRS:
                problems.append(f"夹带目录 {os.path.relpath(os.path.join(r, d), root)}"
                                f"（{FORBIDDEN_DIRS[d]}）")
                dirs.remove(d)
        for f in files:
            rp = os.path.relpath(os.path.join(r, f), root)
            if f in FORBIDDEN_FILES:
                problems.append(f"夹带文件 {rp}（{FORBIDDEN_FILES[f]}）")
            elif f.endswith((".pyc", ".exe", ".dll")):
                problems.append(f"夹带二进制 {rp}")

    for r, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(r, f)
            if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                continue
            try:
                text = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for pat, what in LEAK_PATTERNS:
                m = pat.search(text)
                if not m:
                    continue
                hit = m.group(0)
                # 通用默认路径与占位示例不算本机痕迹
                if "Program Files" in hit or "xxx" in hit:
                    continue
                problems.append(f"{os.path.relpath(p, root)} 里出现{what}：{hit[:40]}")

    skill = os.path.join(root, "SKILL.md")
    if os.path.exists(skill):
        head = open(skill, encoding="utf-8").read(600)
        if not head.startswith("---"):
            problems.append("SKILL.md 缺少 frontmatter")
        for k in ("name:", "description:"):
            if k not in head:
                problems.append(f"SKILL.md frontmatter 缺少 {k}")
    return problems


def version() -> str:
    p = os.path.join(PKG, "VERSION")
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else "0.0.0"


def main() -> int:
    ap = argparse.ArgumentParser(description="技能包出厂审计 / 打包")
    ap.add_argument("--build", action="store_true", help="审计通过后打 zip")
    args = ap.parse_args()

    print(f"包    {PKG}")
    print(f"版本  {version()}")

    tmp = tempfile.mkdtemp(prefix="wgd-stage-")
    try:
        n = stage(tmp)
        total = sum(os.path.getsize(os.path.join(r, f))
                    for r, _d, fs in os.walk(tmp) for f in fs)
        print(f"暂存  {n} 个文件，{total / 1024:.0f} KB\n")

        problems = audit(tmp)
        if problems:
            print(f"✗ {len(problems)} 项不合格：")
            for x in problems:
                print("   -", x)
            return 1

        print("✓ 出厂审计通过：无运行时产物、无本机痕迹、必需文件齐全。")
        if args.build:
            dist = os.path.abspath(os.path.join(PKG, "..", "..", "..", "dist"))
            os.makedirs(dist, exist_ok=True)
            out = os.path.join(dist, f"{NAME}-{version()}.zip")
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for r, _d, fs in os.walk(tmp):
                    for f in fs:
                        full = os.path.join(r, f)
                        arc = os.path.join(NAME, os.path.relpath(full, tmp))
                        z.write(full, arc.replace("\\", "/"))
            print(f"\n已打包 -> {out}")
            print(f"体积 {os.path.getsize(out) / 1024:.0f} KB")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
