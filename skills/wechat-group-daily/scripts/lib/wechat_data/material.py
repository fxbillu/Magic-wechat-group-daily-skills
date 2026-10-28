"""素材判定：一段素材够不够写成日报、大概能分几段

**这里是唯一真源。** `db.py` 的视图状态、`tools/check_story.py` 的检查、
`references/writing-spec.md` 的散文说明，都指向这个文件。改阈值改这里，
不要在别处再写一份——两份规则迟早会悄悄不一致。

判定用两个信号，不用条数：
    条数两头都会骗人。一个号连发十条促销，条数够却没有一句对话；
    一个人贴几段长文讲清一个方案，条数很少却是好素材。
"""

# 文字总量地板：低于这个数，无论几条消息都没有可讲的内容
MIN_CHARS = 200

# 单人单向发布的地板。一个人只在公告、没人与他对话，
# 但字数过这条线仍可能成篇（比如一口气讲完踩坑过程），所以不直接否决
MONOLOGUE_MIN_CHARS = 800

# 每段故事线至少要有的素材字数。低于它就是拆得太碎，靠转述撑字数
MIN_CHARS_PER_NODE = 60

# 段数的绝对下限。少于这个数不叫日报，叫一条消息
MIN_NODES = 3

# 段数上限只做防呆，真正该分几段看话题
MAX_NODES = 9


def sufficient(total: int, chars: int, senders: int, *, template='detailed') -> tuple[bool, str]:
    """这天的料够不够写一篇。返回 (够不够, 不够的理由)

    只看能拿到的事实，不猜。
    """
    if template == 'project':
        return (True, '') if chars > 0 else (False, '没有可读文字或成功的语音转写；附件内容未处理')
    if chars < MIN_CHARS:
        return False, f"文字总量只有 {chars} 字，不到 {MIN_CHARS} 字的地板"
    if senders <= 1 and chars < MONOLOGUE_MIN_CHARS:
        return False, (f"一个人在单向发布（{total} 条 / {chars} 字 / 无人接话），"
                       f"这是公告不是故事")
    return True, ""


def recommend_nodes(chars: int) -> tuple[int, int]:
    """按素材量给一个段数区间（含两端）

    不追求精确，只给个护栏：让「按内容分段」有个参照，
    而不是永远对着 6-8 这个固定区间硬凑。
    """
    hi = max(MIN_NODES, min(MAX_NODES, chars // MIN_CHARS_PER_NODE))
    return MIN_NODES, hi


def describe(chars: int) -> str:
    lo, hi = recommend_nodes(chars)
    return f"{lo}-{hi} 段" if lo != hi else f"{lo} 段"
