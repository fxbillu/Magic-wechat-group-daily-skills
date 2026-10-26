"""日报渲染：story.json → 杂志风 HTML（+ PNG 长图）

默认按约定输出到 `reports/<date>/<群ID的sha256>.html|.png`，并登记到索引 index.db；
指定 `--out` 则回到"只出文件、不登记"的自由模式。

    python render_daily.py story.json                         # 约定路径 + 登记
    python render_daily.py story.json --theme minimal          # 换主题
    python render_daily.py story.json --accent "#2A6F97"       # 换主色
    python render_daily.py story.json --out d.html --no-png    # 自由输出

头像取自 head_image.db 的真实 JPEG，按显示名映射到 wxid；
找不到的降级为彩色圆形首字。
"""
import argparse
import html
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:var(--font-body);-webkit-font-smoothing:antialiased}
.page{width:900px;margin:0 auto;background:var(--paper);padding:var(--pad) 72px 56px;position:relative}
.masthead{display:flex;align-items:flex-end;justify-content:space-between;border-bottom:var(--mast-rule);padding-bottom:14px}
.brand{font-size:var(--brand-size);letter-spacing:.22em;font-weight:600;font-family:var(--font-head)}
.vol{font-size:12px;letter-spacing:.14em;color:var(--muted);font-family:var(--font-mono)}
.lead{padding:52px 0 44px;border-bottom:1px solid var(--rule)}
.eyebrow{font-family:var(--font-mono);font-size:11px;letter-spacing:.28em;color:var(--accent);text-transform:uppercase;margin-bottom:22px}
.title{font-size:var(--title-size);line-height:1.32;font-weight:600;letter-spacing:.01em;margin-bottom:30px;font-family:var(--font-head);color:var(--ink)}
.opening{font-size:16px;line-height:2;color:var(--body-text);text-align:justify}
.opening::first-letter{float:left;font-size:62px;line-height:.86;padding:6px 12px 0 0;color:var(--accent);font-weight:600;display:var(--dropcap)}
.timeline{padding-top:16px}
.node{padding:46px 0 40px;border-bottom:1px solid var(--rule);position:relative}
.node:last-child{border-bottom:none}
.no{font-family:var(--font-mono);font-size:13px;color:var(--accent);letter-spacing:.16em;margin-bottom:10px}
.node-head{display:flex;align-items:baseline;gap:14px;margin-bottom:18px}
.time{font-family:var(--font-mono);font-size:13px;color:var(--muted);letter-spacing:.08em}
.badge{font-size:11px;letter-spacing:.1em;padding:3px 10px;border:1px solid var(--accent);color:var(--accent);font-family:var(--font-mono)}
.theme{font-size:var(--theme-size);font-weight:600;line-height:1.45;margin-bottom:20px;font-family:var(--font-head);color:var(--ink)}
.cast{display:flex;gap:10px;align-items:center;margin-bottom:22px;flex-wrap:wrap}
.cast-label{font-family:var(--font-mono);font-size:10px;letter-spacing:.2em;color:var(--muted);margin-right:4px}
.avatar{width:32px;height:32px;border-radius:var(--avatar-radius);display:flex;align-items:center;justify-content:center;font-size:13px;color:#fff;font-family:var(--font-mono);overflow:hidden;flex:0 0 auto}
.avatar img{width:100%;height:100%;object-fit:cover;display:block}
.cast-name{font-size:12px;color:var(--muted);margin-right:8px}
.story{font-size:15px;line-height:2.05;color:var(--body-text);text-align:justify}
.quote{margin:24px 0 0;padding:16px 22px;border-left:3px solid var(--accent);background:var(--quote-bg);font-size:15px;line-height:1.95;color:var(--body-text)}
.quote .who{display:block;margin-top:10px;font-size:11px;letter-spacing:.1em;color:var(--muted);font-family:var(--font-mono)}
.output{margin-top:20px;font-size:12.5px;color:var(--muted);padding-top:14px;border-top:1px dashed var(--rule)}
.output b{color:var(--accent);font-weight:600;letter-spacing:.08em}
.sec-title{font-size:13px;letter-spacing:.26em;color:var(--accent);font-family:var(--font-mono);padding:50px 0 8px;border-bottom:var(--mast-rule);margin-bottom:30px}
.hl-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.hl{background:var(--card);padding:22px 24px;border:1px solid var(--rule);border-radius:var(--card-radius)}
.hl-top{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.hl-name{font-size:16px;font-weight:600;font-family:var(--font-head);color:var(--ink)}
.hl-tag{font-size:11px;color:var(--accent);letter-spacing:.08em;display:block;margin-top:2px;font-family:var(--font-mono)}
.hl-desc{font-size:13px;line-height:1.9;color:var(--body-text)}
.sop{background:var(--card);border:1px solid var(--rule);padding:24px 26px;margin-bottom:16px;border-radius:var(--card-radius)}
.sop-title{font-size:17px;font-weight:600;margin-bottom:6px;font-family:var(--font-head);color:var(--ink)}
.sop-meta{font-size:11px;color:var(--muted);margin-bottom:14px;letter-spacing:.06em;font-family:var(--font-mono)}
.sop ol{padding-left:20px}
.sop li{font-size:13.5px;line-height:2;color:var(--body-text)}
.qa{margin-bottom:20px}
.qa-q{font-size:15px;font-weight:600;margin-bottom:8px;font-family:var(--font-head);color:var(--ink)}
.qa-a{font-size:13.5px;line-height:1.95;color:var(--body-text);padding-left:14px;border-left:2px solid var(--rule);margin-bottom:8px}
.stats{margin-top:56px;padding-top:26px;border-top:var(--mast-rule);display:flex;justify-content:space-around;text-align:center}
.stat-num{font-size:34px;font-weight:600;color:var(--accent);font-family:var(--font-mono)}
.stat-label{font-size:11px;letter-spacing:.14em;color:var(--muted);margin-top:6px;font-family:var(--font-mono)}
.footer{margin-top:44px;padding:34px 0 12px;border-top:1px solid var(--rule);text-align:center}
.footer-text{font-size:20px;line-height:1.9;color:var(--ink);font-family:var(--font-head)}
.footer-attr{font-size:11px;color:var(--muted);margin-top:14px;letter-spacing:.1em;font-family:var(--font-mono)}
.produced{margin-top:40px;font-size:10px;color:var(--faint);letter-spacing:.2em;text-align:center;font-family:var(--font-mono)}
"""

SERIF = '"Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSong","SimSun",serif'
SANS = '"Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif'
MONO = '"SF Mono","Consolas","JetBrains Mono",monospace'

THEMES = {
    "magazine": {
        "bg": "#E8E2D5", "paper": "#F7F3EA", "ink": "#1E1B16",
        "body_text": "#2E2820", "muted": "#8A8175", "accent": "#B33A2B",
        "rule": "#D9D0BF", "card": "#FFFDF8", "quote_bg": "rgba(179,58,43,.045)",
        "faint": "#B8AE9C",
        "font_head": SERIF, "font_body": SERIF,
        "font_mono": '"Helvetica Neue",Arial,sans-serif',
        "title_size": "46px", "theme_size": "27px", "brand_size": "30px",
        "pad": "64px", "avatar_radius": "50%", "card_radius": "0",
        "mast_rule": "2px solid var(--ink)", "dropcap": "block",
    },
    "minimal": {
        "bg": "#FFFFFF", "paper": "#FFFFFF", "ink": "#0A0A0A",
        "body_text": "#2B2B2B", "muted": "#909090", "accent": "#0A0A0A",
        "rule": "#E6E6E6", "card": "#FAFAFA", "quote_bg": "transparent",
        "faint": "#C4C4C4",
        "font_head": SANS, "font_body": SANS, "font_mono": MONO,
        "title_size": "36px", "theme_size": "22px", "brand_size": "20px",
        "pad": "56px", "avatar_radius": "4px", "card_radius": "0",
        "mast_rule": "1px solid var(--ink)", "dropcap": "none",
    },
    "tech": {
        "bg": "#080A0E", "paper": "#0F1319", "ink": "#DDE4EC",
        "body_text": "#AFBAC7", "muted": "#6B7686", "accent": "#3FD0C9",
        "rule": "#1E2530", "card": "#141A22", "quote_bg": "rgba(63,208,201,.06)",
        "faint": "#3D4756",
        "font_head": SANS, "font_body": SANS,
        "font_mono": '"JetBrains Mono","Cascadia Code",Consolas,monospace',
        "title_size": "40px", "theme_size": "24px", "brand_size": "22px",
        "pad": "60px", "avatar_radius": "6px", "card_radius": "8px",
        "mast_rule": "1px solid var(--accent)", "dropcap": "none",
    },
}

PALETTE = ["#B33A2B", "#7A6A4F", "#4E5D52", "#8C6239", "#5B4B6E", "#A05C3C"]


def build_css(theme: str, accent: str | None = None) -> str:
    t = dict(THEMES.get(theme) or THEMES["magazine"])
    if accent:
        t["accent"] = accent
    v = f"""
    --bg:{t['bg']};--paper:{t['paper']};--ink:{t['ink']};
    --body-text:{t['body_text']};--muted:{t['muted']};--accent:{t['accent']};
    --rule:{t['rule']};--card:{t['card']};--quote-bg:{t['quote_bg']};--faint:{t['faint']};
    --font-head:{t['font_head']};--font-body:{t['font_body']};--font-mono:{t['font_mono']};
    --title-size:{t['title_size']};--theme-size:{t['theme_size']};--brand-size:{t['brand_size']};
    --pad:{t['pad']};--avatar-radius:{t['avatar_radius']};--card-radius:{t['card_radius']};
    --mast-rule:{t['mast_rule']};--dropcap:{t['dropcap']};
    """
    return ":root{" + v + "}\n" + BASE_CSS


def esc(s) -> str:
    return html.escape(str(s or ""))


def _avatar(name: str, uidx: dict, avatars: dict, i: int) -> str:
    uname = uidx.get(name)
    uri = avatars.get(uname) if uname else None
    if uri:
        return f'<div class="avatar"><img src="{uri}" alt=""></div>'
    ch = (name or "?")[0]
    return f'<div class="avatar" style="background:{PALETTE[i % len(PALETTE)]}">{esc(ch)}</div>'


def _quote_block(quotes) -> str:
    return "".join(
        f'<div class="quote">“{esc(q.get("text"))}”'
        f'<span class="who">— {esc(q.get("who"))}</span></div>'
        for q in (quotes or [])
    )


def _node(n: dict, i: int, uidx: dict, avatars: dict) -> str:
    cast = ""
    for j, c in enumerate(n.get("cast") or []):
        name = c.get("name") if isinstance(c, dict) else str(c)
        cast += _avatar(name, uidx, avatars, i + j) + f'<span class="cast-name">{esc(name)}</span>'
    cast_html = f'<div class="cast"><span class="cast-label">CAST</span>{cast}</div>' if cast else ""
    output = (f'<div class="output"><b>产出</b> · {esc(n["output"])}</div>'
              if n.get("output") else "")
    return f'''
    <article class="node">
      <div class="no">{esc(n.get("no", f"{i+1:02d}"))}</div>
      <div class="node-head">
        <span class="time">{esc(n.get("time",""))}</span>
        <span class="badge">{esc(n.get("badge",""))}</span>
      </div>
      <h2 class="theme">{esc(n.get("theme",""))}</h2>
      {cast_html}
      <p class="story">{esc(n.get("story",""))}</p>
      {_quote_block(n.get("quotes"))}
      {output}
    </article>'''


def render_html(story: dict, theme: str = "magazine", accent: str | None = None,
                uidx: dict | None = None, avatars: dict | None = None) -> str:
    uidx = uidx or {}
    avatars = avatars or {}
    stats = story.get("stats") or {}
    timeline = "".join(_node(n, i, uidx, avatars)
                       for i, n in enumerate(story.get("timeline") or []))

    hl = ""
    for i, h in enumerate(story.get("highlights") or []):
        hl += f'''
        <div class="hl">
          <div class="hl-top">
            {_avatar(h.get("name",""), uidx, avatars, i)}
            <div><div class="hl-name">{esc(h.get("name"))}</div>
                 <span class="hl-tag">{esc(h.get("tag",""))}</span></div>
          </div>
          <div class="hl-desc">{esc(h.get("desc",""))}</div>
        </div>'''
    hl_html = f'<div class="sec-title">今日高光</div><div class="hl-grid">{hl}</div>' if hl else ""

    sops = ""
    for s in story.get("sops") or []:
        steps = "".join(f"<li>{esc(x)}</li>" for x in s.get("steps") or [])
        meta = " · ".join(x for x in [s.get("author"), s.get("time")] if x)
        tail = (f'<div class="output" style="margin-top:14px"><b>结果</b> · {esc(s["output"])}</div>'
                if s.get("output") else "")
        sops += (f'<div class="sop"><div class="sop-title">{esc(s.get("title"))}</div>'
                 f'<div class="sop-meta">{esc(meta)}</div><ol>{steps}</ol>{tail}</div>')
    sops_html = f'<div class="sec-title">可抄作业</div>{sops}' if sops else ""

    qas = ""
    for q in story.get("qas") or []:
        ans = "".join(
            f'<div class="qa-a"><b>{esc(a.get("who"))}</b>：{esc(a.get("text"))}</div>'
            for a in q.get("answers") or []
        )
        qas += f'<div class="qa"><div class="qa-q">Q：{esc(q.get("q"))}</div>{ans}</div>'
    qas_html = f'<div class="sec-title">问答沉淀</div>{qas}' if qas else ""

    stat_html = ""
    for key, label in (("total_messages", "条消息"), ("unique_senders", "人发言"),
                       ("total_chars", "字讨论"), ("new_members", "位新成员")):
        v = stats.get(key)
        if v:
            stat_html += f'<div><div class="stat-num">{v}</div><div class="stat-label">{label}</div></div>'

    fq = story.get("footer_quote") or {}
    footer_html = ""
    if fq.get("text"):
        footer_html = (f'<div class="footer"><div class="footer-text">“{esc(fq["text"])}”</div>'
                       f'<div class="footer-attr">{esc(fq.get("attr",""))}</div></div>')

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{esc(story.get("group_name"))} · 群日报</title>
<style>{build_css(theme, accent)}</style></head>
<body><div class="page">
  <div class="masthead">
    <div class="brand">群日报</div>
    <div class="vol">Vol. {esc(story.get("date",""))} &nbsp;·&nbsp; {esc(story.get("time_range",""))}</div>
  </div>
  <section class="lead">
    <div class="eyebrow">{esc(story.get("lead_eyebrow","Today's Story · 今日故事"))}</div>
    <h1 class="title">{esc(story.get("lead_title","")).replace(chr(10),"<br>")}</h1>
    <p class="opening">{esc(story.get("opening",""))}</p>
  </section>
  <section class="timeline">{timeline}</section>
  {hl_html}
  {sops_html}
  {qas_html}
  <div class="stats">{stat_html}</div>
  {footer_html}
  <div class="produced">PRODUCED · {esc(story.get("group_name",""))} · 本地生成，未上传</div>
</div></body></html>'''


def find_browser():
    """按 环境变量 → PATH → 注册表 → 常见位置 逐级找 Chromium 系浏览器

    只认几个固定路径会漏掉"装在别的盘""单用户安装""改了目录名"这几种情况，
    表现是长图永远出不来、却看不出为什么。这里逐级降级，找不到才返回 None。
    """
    names = ("msedge.exe", "chrome.exe")
    cands = []

    # 1) 环境变量：用户显式指定优先
    for env in ("WECHAT_DAILY_BROWSER", "BROWSER"):
        v = os.environ.get(env)
        if v and os.path.isfile(v):
            cands.append(v)

    # 2) PATH
    import shutil
    for n in names:
        p = shutil.which(n)
        if p:
            cands.append(p)

    # 3) 注册表 App Paths —— 单用户安装、非默认盘也登记在这里
    try:
        import winreg
        rel = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for n in names:
                for view in (winreg.KEY_READ,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
                    try:
                        with winreg.OpenKey(hive, rel + n, 0, view) as k:
                            p = (winreg.QueryValue(k, None) or "").strip('"')
                            if p and os.path.isfile(p):
                                cands.append(p)
                    except OSError:
                        continue
    except ImportError:
        pass

    # 4) 常见位置（含 LocalAppData 的单用户安装）
    rels = (r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe")
    for root in (os.environ.get("ProgramFiles"),
                 os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")):
        if not root:
            continue
        for r in rels:
            p = os.path.join(root, r)
            if os.path.isfile(p):
                cands.append(p)

    for p in cands:
        if p and os.path.isfile(p):
            return p
    return None


def trim_bottom(png_path: str, pad: int = 48) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        im = Image.open(png_path).convert("RGB")
        w, h = im.size
        px = im.load()
        bg = px[w // 2, h - 2]
        sx, sy = max(1, w // 120), max(1, h // 900)
        bottom = 0
        for y in range(h - 1, 0, -sy):
            for x in range(0, w, sx):
                if px[x, y] != bg:
                    bottom = y
                    break
            if bottom:
                break
        if bottom and bottom < h - pad:
            im.crop((0, 0, w, min(h, bottom + pad))).save(png_path)
            return True
    except Exception:
        pass
    return False


def html_to_png(html_path: str, png_path: str, width: int = 900, height: int = 9000):
    exe = find_browser()
    if not exe:
        print("[warn] 未找到 Edge/Chrome，跳过 PNG")
        return None
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    out = os.path.abspath(png_path)
    if os.path.exists(out):
        os.remove(out)
    cmd = [exe, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
           f"--window-size={width},{height}", f"--screenshot={out}", url]
    try:
        subprocess.run(cmd, timeout=180, capture_output=True)
    except subprocess.SubprocessError as e:
        print("[warn] 截图失败:", e)
        return None
    import time
    deadline = time.time() + 60
    last, stable = -1, 0
    while time.time() < deadline:
        if os.path.exists(out):
            size = os.path.getsize(out)
            if size > 0 and size == last:
                stable += 1
                if stable >= 2:
                    return out
            else:
                stable = 0
            last = size
        time.sleep(0.5)
    return out if os.path.exists(out) else None


def collect_names(story: dict) -> list[str]:
    names = []
    for n in story.get("timeline") or []:
        for c in n.get("cast") or []:
            names.append(c.get("name") if isinstance(c, dict) else str(c))
        for q in n.get("quotes") or []:
            if q.get("who"):
                names.append(q["who"])
    for h in story.get("highlights") or []:
        if h.get("name"):
            names.append(h["name"])
    for s in story.get("sops") or []:
        if s.get("author"):
            names.append(s["author"])
    for q in story.get("qas") or []:
        if q.get("asker"):
            names.append(q["asker"])
        for a in q.get("answers") or []:
            if a.get("who"):
                names.append(a["who"])
    return [n for n in names if n]


def _rel_to_reports(cfg, path):
    """返回相对 reports 目录的路径（正斜杠）；不在其下返回 None"""
    from wechat_data import settings

    if not path:
        return None
    rep = os.path.abspath(settings.reports_dir(cfg))
    try:
        rel = os.path.relpath(os.path.abspath(path), rep)
    except ValueError:          # 跨盘符
        return None
    return None if rel.startswith("..") else rel.replace("\\", "/")


def _default_outputs(cfg, story):
    """按约定算默认输出：reports/<date>/<群ID的sha256>.html + 同名 .png"""
    from wechat_data import settings
    from wechat_data.archive import archive_path

    date = str(story.get("date") or "")
    chat = str(story.get("group_name") or "")
    if not (date and chat):
        raise SystemExit("[错误] story.json 缺少 date 或 group_name，无法推断输出路径；"
                         "请显式指定 --out")
    username = story.get('username')
    if not username:
        raise SystemExit('[错误] 群身份不明确，请指定 story.username。')
    stem = os.path.join(settings.reports_dir(cfg), date,
                        os.path.splitext(os.path.basename(archive_path(cfg, date, username)))[0])
    return stem + ".html", stem + ".png"


def _theme_from_config(cfg, story) -> str:
    """主题取值顺序：这个群自己的 theme → compose.theme → magazine

    配置里一直写着 `chats[].theme`，但渲染层从前只认命令行 `--theme`，
    那个字段等于装饰品——写 minimal 也不会有任何效果。这里把它接上。
    """
    from wechat_data import settings

    name = str(story.get("group_name") or "")
    for c in cfg.get("chats") or []:
        if name and name in (c.get("name"), c.get("username")):
            t = c.get("theme")
            if t in THEMES:
                return t
    t = settings.get(cfg, "compose.theme")
    return t if t in THEMES else "magazine"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story")
    ap.add_argument("--out", help="HTML 输出路径（默认按稳定群 ID）")
    ap.add_argument("--png", help="PNG 输出路径（默认与 HTML 同名）")
    ap.add_argument("--no-png", action="store_true", help="不生成 PNG")
    ap.add_argument("--theme", default=None, choices=list(THEMES),
                    help="默认取配置里的 theme（群的 theme → compose.theme → magazine）")
    ap.add_argument("--accent", help="覆盖主色，如 #B33A2B")
    ap.add_argument("--height", type=int, default=9000)
    ap.add_argument("--no-avatar", action="store_true", help="不用真实头像，全用首字占位")
    ap.add_argument("--no-register", action="store_true",
                    help="不登记到索引 index.db（只出文件）")
    args = ap.parse_args()

    story = json.load(open(args.story, encoding="utf-8"))

    from wechat_data import db, settings
    cfg = settings.require()

    if not args.no_register:
        date = str(story.get('date') or '')
        username = story.get('username') or db.find_username(cfg, date, story.get('group_name', ''))
        entry = db.get_entry(cfg, date, username) if username else None
        if not entry:
            print('[错误] 群身份不明确或没有对应归档，请指定 story.username。', file=sys.stderr)
            return 3
        story['username'] = username
        story.setdefault('source_revision', entry['collection']['revision'])
    theme = args.theme or _theme_from_config(cfg, story)

    if args.out:
        out_html, default_png = args.out, None
    else:
        out_html, default_png = _default_outputs(cfg, story)
    out_png = None if args.no_png else (args.png or default_png)

    uidx, avatars = {}, {}
    if not args.no_avatar:
        try:
            from wechat_data import avatar as av
            names = collect_names(story)
            uidx = av.resolve_names_to_users(names)
            avatars = av.get_avatars(list(uidx.values()))
            print(f"[avatar] 人名 {len(set(names))} 个，解析到 {len(uidx)} 个，取到头像 {len(avatars)} 张")
        except Exception as e:
            print(f"[warn] 头像加载失败（改用占位）：{e}")

    html_text = render_html(story, theme=theme, accent=args.accent,
                            uidx=uidx, avatars=avatars)
    os.makedirs(os.path.dirname(os.path.abspath(out_html)), exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"[OK] HTML -> {out_html}  (theme={theme})")

    if out_png:
        p = html_to_png(out_html, out_png, height=args.height)
        if p:
            trimmed = trim_bottom(p)
            print(f"[OK] PNG -> {p}" + ("（已裁底）" if trimmed else ""))
        else:
            print("[warn] PNG 未生成")
            out_png = None

    # 登记索引：不登记的话浏览层永远显示 pending
    if args.no_register:
        print("[skip] 按参数跳过索引登记")
        return 0

    rel_html = _rel_to_reports(cfg, out_html)
    rel_png = _rel_to_reports(cfg, out_png)
    if not (rel_html or rel_png):
        print("[warn] 产物不在 reports 目录下，跳过索引登记"
              "（想登记请输出到 reports/<date>/）")
        return 0

    # story 与产物一并落盘：rebuild 只认文件，不落这份标题就丢了
    story_out = os.path.join(
        os.path.dirname(out_html),
        os.path.splitext(os.path.basename(out_html))[0] + ".story.json")
    with open(story_out, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)
    print(f"[OK] story -> {story_out}")

    ok = db.set_report(cfg, str(story.get("date") or ""),
                       html=rel_html or "", png=rel_png or "", story=story)
    if ok:
        print(f"[OK] 已登记索引  {story.get('date')} / {story.get('group_name')}")
    else:
        print(f"[warn] 索引未登记：{story.get('date')} / {story.get('group_name')} "
              f"没有对应归档，先跑 python fetch.py archive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
