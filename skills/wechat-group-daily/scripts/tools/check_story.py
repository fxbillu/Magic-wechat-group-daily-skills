"""写稿自检 + 素材画像

两个模式，回答两个不同的问题：

1. 稿件检查（默认）——「写出来的这篇，机械项有没有错」
   引号是不是逐字照抄、字数落在哪个区间、统计和归档一不一致、
   cast 里的人那一天到底有没有发言。这些不需要判断力，机器比人可靠。

2. 素材画像（--assess）——「这天的料够不够写一篇」
   条数、人数、字数、对话轮次。它不下结论、不拦你，只把数据摆出来，
   免得用"条数"这种最差的判据一刀切。

**它不是"要不要出日报"的判定器。** 出不出报是判断（读完之后划不划得出故事线），
这里只做防呆：防止交付物在机械约束上出错，防止决策凭一个数字拍脑袋。

用法：
    python tools/check_story.py "reports/2026-10-24/<群名>.story.json"
    python tools/check_story.py <story.json> --archive <归档.json>
    python tools/check_story.py --assess "<群名>" --date 2026-10-25

退出码：检查模式 0 全过 / 1 有不过项（渲染仍可能成功，不代表能交付）；
       画像模式恒为 0。
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "lib"))

from wechat_data import settings  # noqa: E402
from wechat_data import material  # noqa: E402

# 稿件字段的约束（story / opening 的字数区间是模板契约，改这里一处）
STORY_MIN, STORY_MAX = 150, 250
OPENING_MIN, OPENING_MAX = 150, 200
HIGHLIGHT_MIN, HIGHLIGHT_MAX = 6, 8

# 素材地板与段数区间不在这里定义——唯一真源是 lib/wechat_data/material.py


def is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def load_archive(args) -> dict:
    if args.archive:
        try:
            with open(args.archive, encoding='utf-8') as source:
                return json.load(source)
        except (OSError, ValueError):
            print('[错误] 无法读取指定归档')
            return None
    from wechat_data import archive
    result = archive.load(settings.require(), args.date or '', args.assess or '')
    if result is None:
        print('[错误] 找不到唯一归档，请使用稳定群 ID 或 --archive。')
    return result


def assess(args) -> int:
    """素材画像：只摆数据，不下"该不该写"的结论"""
    arch = load_archive(args)
    if arch is None:
        return 1
    msgs = arch.get("messages", [])
    if not msgs:
        print("[素材] 当天没有消息")
        return 0

    senders = [str(m.get("sender", "")) for m in msgs]
    texts = [str(m.get("text", "")) for m in msgs if m.get("type") == "text"]
    chars = sum(len(t) for t in texts)
    turns = sum(1 for a, b in zip(senders, senders[1:]) if a != b)
    people = len({s for s in senders if s})
    longest = max((len(t) for t in texts), default=0)
    others = len(msgs) - len(texts)

    print(f"[素材] {args.assess}  {args.date or ''}")
    print(f"   条数      {len(msgs)}（其中非文字 {others}）")
    print(f"   参与者    {people} 人")
    print(f"   文字总量  {chars} 字（最长单条 {longest} 字）")
    print(f"   对话轮次  {turns}（相邻两条换人的次数）")
    print(f"   参考段数  {material.describe(chars)}（内容决定，这只是护栏）")
    print()

    enough, why = material.sufficient(len(msgs), chars, people)
    if not enough:
        print(f"→ 不够成篇：{why}。")
        if people <= 1 and turns == 0 and chars < material.MONOLOGUE_MIN_CHARS:
            print(f"   （单人长篇仍可能成篇，地板是 {material.MONOLOGUE_MIN_CHARS} 字；这条没过线）")
    else:
        lo, hi = material.recommend_nodes(chars)
        print(f"→ 先读完再判。数据上够料（参考 {lo}-{hi} 段，按话题划，不必凑数）；")
        print("   读完全部消息后划不出 3 段完整故事线，才叫不够成篇。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="日报 story.json 自检 / 素材画像")
    ap.add_argument("story", nargs="?", help="story.json 路径（检查模式）")
    ap.add_argument("--assess", metavar="群名", help="只做素材画像，不检查稿件")
    ap.add_argument("--date", help="配合 --assess 使用：YYYY-MM-DD")
    ap.add_argument("--archive", help="归档文件路径（默认按配置推导）")
    args = ap.parse_args()

    if args.assess or (args.date and not args.story):
        if not args.assess:
            ap.error("--date 需要配合 --assess <群名> 使用")
        return assess(args)
    if not args.story:
        ap.error("请给出 story.json 路径，或用 --assess <群名> --date <日期>")

    story = json.load(open(args.story, encoding="utf-8"))
    group = story.get("group_name", "")
    date = story.get("date", "")

    if args.archive:
        with open(args.archive, encoding='utf-8') as source:
            arch = json.load(source)
    else:
        from wechat_data import archive
        arch = archive.load(settings.require(), date, story.get('username') or group)
    if arch is None:
        print('[错误] 找不到唯一归档，请指定 story.username 或 --archive。')
        return 1
    msgs = arch.get("messages", [])
    texts = {str(m.get("text", "")) for m in msgs}
    spokes = {str(m.get("sender", "")) for m in msgs}

    problems = []

    # 1. 引号必须逐字出现在归档里
    n_quotes = 0
    for n in story.get("timeline", []):
        for q in n.get("quotes", []):
            n_quotes += 1
            if not isinstance(q, dict):
                problems.append(f"{n.get('no')} 的 quotes 必须是 {{who, text}} 对象，现在是字符串：{str(q)[:30]}")
                continue
            if q.get("text") not in texts:
                problems.append(f"{n.get('no')} 引号与原文不符：{str(q.get('text'))[:40]}")
            if q.get("who") not in spokes:
                problems.append(f"{n.get('no')} 引号署名「{q.get('who')}」不在当天发言人里")
    print(f"[引号] {n_quotes} 句，逐字核对完毕")

    # 2. story 字数
    print("[字数]")
    for n in story.get("timeline", []):
        L = len(n.get("story", ""))
        ok = STORY_MIN <= L <= STORY_MAX
        print(f"   {n.get('no')} {L:>3} 字  {'OK' if ok else '越界'}")
        if not ok:
            problems.append(f"{n.get('no')} story {L} 字，要求 {STORY_MIN}-{STORY_MAX}")

    # 3. opening
    op = story.get("opening", "")
    if not op or not is_cjk(op[0]):
        problems.append("opening 必须以汉字开头（首字会被做 drop cap）")
    if not (OPENING_MIN <= len(op) <= OPENING_MAX):
        problems.append(f"opening {len(op)} 字，要求 {OPENING_MIN}-{OPENING_MAX}")
    print(f"[开场] {len(op)} 字，首字「{op[:1]}」")

    # 4. 段数：内容驱动，只卡下限和防呆上限，不再对着固定区间硬凑
    tl = story.get("timeline", [])
    hl = story.get("highlights", [])
    lo_n, hi_n = material.recommend_nodes(int((arch.get("stats") or {}).get("chars", 0)))
    if len(tl) < material.MIN_NODES:
        problems.append(f"timeline 只有 {len(tl)} 段，少于 {material.MIN_NODES} 段不算日报")
    elif len(tl) > material.MAX_NODES:
        problems.append(f"timeline {len(tl)} 段，超过防呆上限 {material.MAX_NODES} 段")
    elif not (lo_n <= len(tl) <= hi_n):
        print(f"[提示] timeline {len(tl)} 段，按素材量参考区间是 {lo_n}-{hi_n} 段——"
              f"如果每段都够 {material.MIN_CHARS_PER_NODE} 字素材就没问题")
    # 人物卡上限不能超过当天说话的人数，否则就成了「全员标签册」这个反模式
    people = len({str(m.get("sender", "")) for m in msgs if m.get("sender")})
    hl_min = min(HIGHLIGHT_MIN, people)
    if not (hl_min <= len(hl) <= HIGHLIGHT_MAX):
        problems.append(f"highlights {len(hl)} 张，要求 {hl_min}-{HIGHLIGHT_MAX}"
                        f"（当天只有 {people} 人说话，不必凑到 {HIGHLIGHT_MIN} 张）")
    print(f"[结构] timeline {len(tl)} 段（参考 {lo_n}-{hi_n}）/ highlights {len(hl)} 张"
          f"（{people} 人说话，下限 {hl_min}）")

    # 5. theme 不能是时间段
    for n in tl:
        th = (n.get("theme") or "").strip()
        if len(th) and th[0].isdigit() and (":" in th[:5] or "：" in th[:5]):
            problems.append(f"{n.get('no')} theme 写成了时间段：{th}")

    # 6. cast 必须是当天发过言的人
    for n in tl:
        for c in n.get("cast", []):
            if c not in spokes:
                problems.append(f"{n.get('no')} cast 里的「{c}」当天没有发言")
    print("[角色] cast 名单核对完毕")

    # 7. 统计一致
    a = arch.get("stats", {})
    s = story.get("stats", {})
    pairs = (("total_messages", "total"), ("unique_senders", "unique_senders"),
             ("total_chars", "chars"))
    mism = [f"{x}={s.get(x)} vs 归档 {a.get(y)}" for x, y in pairs if s.get(x) != a.get(y)]
    if mism:
        problems.append("统计与归档不一致：" + "; ".join(mism))
    print(f"[统计] {s.get('total_messages')} 条 / {s.get('unique_senders')} 人 / "
          f"{s.get('total_chars')} 字  {'OK' if not mism else '不一致'}")

    # 8. 信息密度：每段稿件字数 / 该时段源字数
    #    只提示不拦截——图片、视频号这类消息源字数极低但确有内容，
    #    所以只在「源字数很少 且 扩写倍数很高」时才值得看一眼
    def to_min(t: str) -> int:
        h, m = t.strip().split(" ")[-1].split(":")[:2]
        return int(h) * 60 + int(m)

    print("[密度]")
    suspects = []
    # 素材量口径：排除纯占位符（[图片]/[表情]/[语音]/[视频]）和系统消息的 XML 碎片，
    # 但**保留** [链接]/[视频号] 的标题——那是真内容，不是占位
    placeholder = re.compile(r"^\[(图片|表情|语音|视频|位置|拍一拍)\]$")
    text_msgs = [m for m in msgs
                 if "sysmsg" not in str(m.get("text", ""))
                 and not placeholder.match(str(m.get("text", "")).strip())]
    for i, n in enumerate(tl):
        lo = to_min(n.get("time", "00:00"))
        hi = to_min(tl[i + 1]["time"]) if i + 1 < len(tl) else 24 * 60
        src = sum(len(str(m.get("text", ""))) for m in text_msgs
                  if lo <= to_min(str(m.get("time", "00:00"))) < hi)
        L = len(n.get("story", ""))
        ratio = L / max(src, 1)
        hot = src < material.MIN_CHARS_PER_NODE and ratio > 4
        if hot:
            suspects.append(n.get("no"))
        print(f"   {n.get('no')} 源 {src:>4} 字 / 稿 {L:>3} 字 = {ratio:>4.1f}x"
              f"{'   ← 源字数少而扩写多，看是不是在拿环境描写凑字' if hot else ''}")
    if suspects:
        print(f"   （{len(suspects)} 段值得复核：{', '.join(map(str, suspects))}——仅提示，不拦截）")

    print()
    if problems:
        print(f"✗ {len(problems)} 项不过：")
        for p in problems:
            print("   -", p)
        return 1
    print("✓ 机械项全部通过。剩下要靠人：故事线划得对不对、人有没有选错、有没有注水。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
