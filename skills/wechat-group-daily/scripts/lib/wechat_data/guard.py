"""数据新鲜度闸门

解决的问题：`decrypted/` 只是某一时刻的快照，之后微信继续写。如果忘了
重新解密，日报会拿着三天前的数据出一份"看起来完全正常"的今日日报——
不报错、不告警、最难发现。

做法：解密完成时在 `decrypted/.stamp.json` 打一个时间戳（含各库指纹），
下游读数据前先看它。

两种判据，问的是两个不同的问题：

1. **要出历史某一天**（`target_date` 早于今天）→ 只问"快照盖不盖得住那天"。
   解密时刻晚于目标日结束，就说明那天的消息已全部落进快照。
   今天的消息再多也影响不到昨天，所以这种查询**不该**因为"解密后又写了库"而拦。
   这也是"每天定时解一次密、全天反复出昨天日报"能成立的前提。

2. **要出今天 / 不指定日期** → 才看时效与"解密后有没有被写过"。
   这时快照越新越好，容忍窗口 `STALE_TOLERANCE_S` 只用来挡掉"刚解完就被写"
   这种秒级抖动。

注意：不要用源库 mtime 来比较是否"新鲜到能用"——微信几乎一直在写，源库 mtime
永远比解密产物新。判据应当回到"我要出的那天，快照里有没有"。
"""
import datetime
import json
import os
import re
import time

STAMP_NAME = ".stamp.json"

# 影响日报正确性的核心库；朋友圈(sns)、表情(emoticon)等变化不影响内容
CRITICAL_PREFIXES = ("message/", "contact/", "session/")

# 解密结束后的容忍窗口（秒）。
#
# 微信几乎一直在写 message/session 库，解密一结束就可能来一条新消息。窗口原先写死 1 秒，
# 于是"刚解密完就判过期"成了常态：实测 decrypt 完成 17 秒后 message_2.db / session.db 被写，
# 整份快照立刻被划为不可用，而按文档指引重解一遍又会再中一次——哨兵在空转。
#
# 5 分钟对"以天为粒度"的日报没有实际影响：真正会漏的是这 5 分钟内的消息，
# 而它们本来也会在下一轮采集里出现。窗口放宽后，判过期意味着"确实该重解了"，
# 不再是"微信刚刚动了一下"。
STALE_TOLERANCE_S = 300


def stamp_path(db_dir: str) -> str:
    return os.path.join(db_dir, STAMP_NAME)


def is_core(rel):
    return rel in ('contact/contact.db', 'session/session.db') or bool(
        re.fullmatch(r'message/message_\d+\.db', rel))


def required_files(source_dir):
    found = {'contact/contact.db'}
    for root, _, names in os.walk(source_dir):
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), source_dir).replace('\\', '/')
            if is_core(rel):
                found.add(rel)
    return found


def write_stamp(db_dir: str, files: dict | None = None, source_dir: str = '',
                required=None, failures=None) -> str:
    from .archive import _atomic_write
    old = read_stamp(db_dir) or {}
    if old.get('source_dir') != source_dir:
        old = {}
    merged = dict(old.get('files') or {})
    merged.update(files or {})
    errors = dict(old.get('failures') or {})
    errors.update(failures or {})
    for rel in files or {}:
        errors.pop(rel, None)
    expected = sorted(required if required is not None else required_files(source_dir))
    verified = [merged.get(rel, {}).get('verified_at', 0) for rel in expected]
    complete_at = min(verified) if verified else 0
    data = {'schema_version': 2, 'decrypted_at': complete_at,
            'decrypted_at_str': datetime.datetime.fromtimestamp(complete_at).astimezone().isoformat(),
            'source_dir': source_dir, 'file_count': len(merged), 'files': merged,
            'required': expected, 'failures': errors}
    path = stamp_path(db_dir)
    _atomic_write(path, data)
    return path


def coverage(db_dir):
    stamp = read_stamp(db_dir) or {}
    files = stamp.get('files') or {}
    expected = set(stamp.get('required') or [])
    source = stamp.get('source_dir')
    if source and os.path.isdir(source):
        expected.update(required_files(source))
    issues = []
    if stamp.get('schema_version') != 2 or not any(
            rel.startswith('message/') for rel in expected):
        issues.append({'code': 'DECRYPTION_INCOMPLETE', 'source': 'snapshot',
                       'message': '缺少逐库核验记录，请重新解密核心库。'})
    for rel in sorted(expected):
        if (not files.get(rel, {}).get('verified_at') or rel in (stamp.get('failures') or {})
                or not os.path.isfile(os.path.join(db_dir, rel))):
            issues.append({'code': 'DECRYPTION_INCOMPLETE', 'source': rel,
                           'message': '核心库尚未成功解密或产物缺失。'})
    for issue in issues:
        issue.update(retryable=True, next_action='decrypt_and_retry_in_workbuddy')
    return {'complete': not issues, 'issues': issues}


def rebuild_stamp(db_dir: str, source_dir: str) -> dict:
    """不解密，仅按现有产物重建时间戳

    用于：换了解密工具、或时间戳丢失后的修复。
    此记录只供诊断，不能代替逐库解密核验；coverage() 始终要求 schema v2。
    """
    files = {}
    newest = 0
    for root, _dirs, names in os.walk(db_dir):
        for n in names:
            if not n.endswith(".db"):
                continue
            p = os.path.join(root, n)
            rel = os.path.relpath(p, db_dir).replace("\\", "/")
            try:
                st = os.stat(p)
            except OSError:
                continue
            newest = max(newest, st.st_mtime)
            src = os.path.join(source_dir, rel)
            try:
                sst = os.stat(src)
                files[rel] = {"size": sst.st_size, "mtime": int(sst.st_mtime)}
            except OSError:
                files[rel] = {"size": 0, "mtime": 0}

    data = {
        "decrypted_at": int(newest) if newest else int(time.time()),
        "decrypted_at_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest or time.time())),
        "source_dir": source_dir,
        "file_count": len(files),
        "files": files,
        "rebuilt": True,
    }
    p = stamp_path(db_dir)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def read_stamp(db_dir: str) -> dict | None:
    p = stamp_path(db_dir)
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def day_end_ts(date_str: str) -> float | None:
    """把 `YYYY-MM-DD` 变成"那天结束"的时间戳；解析不了返回 None"""
    try:
        d = datetime.date.fromisoformat(str(date_str).strip())
    except (ValueError, TypeError):
        return None
    end = datetime.datetime.combine(d + datetime.timedelta(days=1), datetime.time.min)
    return end.timestamp()


def covers_date(decrypted_at: float, date_str: str) -> bool | None:
    """快照是否完整覆盖 `date_str` 这一天

    解密发生在目标日结束之后 → 那天的消息一条不落都进了快照。
    返回 None 表示日期不可解析，调用方应退回时效判据。
    """
    end = day_end_ts(date_str)
    if end is None:
        return None
    return decrypted_at >= end


def check(db_dir: str, max_age_hours: float = 24.0,
          tolerance_s: float | None = None,
          target_date: str | None = None,
          target_end: float | None = None) -> dict:
    """返回新鲜度状态

    fresh   : 能不能拿这份快照去干活
    age_hours: 距上次解密多少小时
    stale_files: 源库里已比解密时刻更新、但还没被解密覆盖的文件

    tolerance_s: 写入容忍窗口（默认 STALE_TOLERANCE_S）。解密后这段时间内的写入
                 不算过期——微信一直在写库，1 秒的窗口会让闸门空转。
    target_date: 要出的那一天（`YYYY-MM-DD`）。给了历史日期就改判"覆盖"，
                 不再看"解密后有没有被写过"。
    """
    tol = STALE_TOLERANCE_S if tolerance_s is None else tolerance_s
    st = read_stamp(db_dir)
    if not st:
        return {
            "fresh": False,
            "age_hours": None,
            "reason": "没有解密时间戳（从未用 safe_decrypt 解密，或来自旧流程）",
            "stale_files": [],
            "action": "请先运行 tools/safe_decrypt.py 重新解密",
        }

    verified = coverage(db_dir)
    if not verified['complete']:
        return {'fresh': False, 'age_hours': None, 'reason': '核心库覆盖未完成',
                'stale_files': [], 'coverage': verified,
                'action': '重新解密核心库后再采集'}

    now = time.time()
    age_h = (now - st["decrypted_at"]) / 3600.0

    if target_end is not None:
        complete = st['decrypted_at'] >= target_end
        return {'fresh': complete, 'age_hours': round(age_h, 2),
                'decrypted_at': st.get('decrypted_at_str'), 'stale_files': [],
                'critical_stale': [], 'code': None if complete else 'SNAPSHOT_INCOMPLETE',
                'reason': '逐库快照已覆盖目标区间' if complete else '逐库快照早于目标区间结束',
                'action': '' if complete else '目标区间结束后重新解密核心库'}

    # ---- 判据一：要出历史某一天 → 只问快照盖不盖得住那天 ----
    # 只对**早于今天**的日期成立。今天一天还没过完，"解密晚于该日结束"永远不成立，
    # 照搬到今天会让 20:00 那趟（刚解密、目标就是今天）被判过期——它该走判据二。
    if target_date and str(target_date).strip() < datetime.date.today().isoformat():
        covered = covers_date(st["decrypted_at"], target_date)
        if covered is not None:
            if covered:
                return {
                    "fresh": True,
                    "age_hours": round(age_h, 2),
                    "decrypted_at": st.get("decrypted_at_str"),
                    "reason": (f"快照在 {target_date} 结束之后解密，"
                               f"完整覆盖该日（解密于 {st.get('decrypted_at_str')}）"),
                    "stale_files": [],
                    "critical_stale": [],
                    "action": "",
                }
            return {
                "fresh": False,
                "age_hours": round(age_h, 2),
                "decrypted_at": st.get("decrypted_at_str"),
                "reason": (f"解密于 {st.get('decrypted_at_str')}，早于 {target_date} 结束，"
                           f"覆盖不到那一天"),
                "stale_files": [],
                "critical_stale": [],
                "action": f"重新解密后再出 {target_date} 的日报",
            }

    # ---- 判据二：要出今天 / 没指定日期 → 看时效与写入 ----
    stale = []
    src_dir = st.get("source_dir") or ""
    if src_dir and os.path.isdir(src_dir):
        for rel, meta in (st.get("files") or {}).items():
            p = os.path.join(src_dir, rel.replace("\\", "/"))
            try:
                if os.path.getmtime(p) > st["decrypted_at"] + tol:
                    stale.append(rel.replace("\\", "/"))
            except OSError:
                continue

    critical_stale = [f for f in stale
                      if any(f.startswith(p) for p in CRITICAL_PREFIXES)]
    fresh = age_h <= max_age_hours and not critical_stale
    if fresh:
        note = f"（另有 {len(stale)} 个非核心库有更新，不影响日报）" if stale else ""
        reason = f"{age_h:.1f} 小时前解密，数据是最新的{note}"
        action = ""
    elif age_h > max_age_hours:
        reason = f"{age_h:.1f} 小时前解密，超过 {max_age_hours:g} 小时阈值"
        action = "数据可能过期，建议先重新解密"
    else:
        reason = (f"核心库在解密后又被写入过（{len(critical_stale)} 个，"
                  f"例如 {critical_stale[0]}）")
        action = "有新消息未纳入，建议重新解密"

    return {
        "fresh": fresh,
        "age_hours": round(age_h, 2),
        "decrypted_at": st.get("decrypted_at_str"),
        "reason": reason,
        "stale_files": stale,
        "critical_stale": critical_stale,
        "action": action,
    }


def warn_if_stale(db_dir: str, max_age_hours: float = 24.0,
                  tolerance_s: float | None = None,
                  target_date: str | None = None) -> dict:
    """打印警告（不中断）"""
    r = check(db_dir, max_age_hours, tolerance_s, target_date)
    if not r["fresh"]:
        print(f"[数据新鲜度] ⚠ {r['reason']}"
              + (f"；{r['action']}" if r["action"] else ""), flush=True)
    return r


class StaleDataError(RuntimeError):
    pass


def assert_fresh(db_dir: str, max_age_hours: float = 24.0,
                 tolerance_s: float | None = None,
                 target_date: str | None = None) -> dict:
    """严格模式：数据不新鲜直接抛异常，绝不产出可能错误的日报"""
    r = check(db_dir, max_age_hours, tolerance_s, target_date)
    if not r["fresh"]:
        raise StaleDataError(
            f"数据不新鲜：{r['reason']}。{r['action']}"
            f"（如确认可用旧数据，请显式加 --allow-stale）"
        )
    return r
