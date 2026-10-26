"""消息读取：跨分片取一个会话在指定时间段内的记录

微信 4.x 把消息按时间/容量分片存在 message_N.db（当前观察到 3 个），
同一个会话的记录可能散落在多个分片里，所以必须全部查一遍再按时间归并。
**分片数量由目录实际内容决定**，不写死——微信扩容后第 4 片照样要能读到。
"""
import hashlib
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from . import config, content
from .chat import Chat


class CoverageError(RuntimeError):
    def __init__(self, shard, code='SHARD_QUERY_FAILED'):
        self.issues = [{'code': code, 'source': os.path.basename(shard),
                        'message': '消息分片无法完整读取，请重新解密后重试。',
                        'retryable': True, 'next_action': 'decrypt_and_retry_in_workbuddy'}]
        super().__init__(f'{code}: {os.path.basename(shard)}')


@dataclass
class Message:
    local_id: int
    ts: datetime
    sender: str
    sender_username: str
    base: int
    sub: int
    text: str
    app: dict | None = None
    voice: dict | None = None
    source_shard: str = ""

    @property
    def ts_str(self) -> str:
        return self.ts.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "local_id": self.local_id,
            "source_shard": self.source_shard,
            "time": self.ts_str,
            "sender": self.sender,
            "sender_id": self.sender_username,
            "type": content.BASE_TYPES.get(self.base, str(self.base)),
            "sub_type": self.sub,
            "text": self.text,
            **({"app": self.app} if self.app else {}),
            **({"voice": self.voice} if self.voice else {}),
        }


@dataclass
class FetchStats:
    total: int = 0
    text_count: int = 0
    chars: int = 0
    senders: dict = field(default_factory=dict)   # 显示名 -> 条数
    types: dict = field(default_factory=dict)     # 类型名 -> 条数

    @property
    def unique_senders(self) -> int:
        return len(self.senders)


def table_of(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def looks_undecoded(s: str) -> bool:
    """判断字符串是不是「没解压的二进制」被硬 decode 出来的

    微信有一部分消息（系统提示、部分撤回/接龙）的 content 是 zstd 压缩的。
    解压失败时按 utf-8 解码会得到大量替换字符与控制字符，而这段文本会被
    原样写进归档，后果有两个：
      1. 写稿时可能把它当成"原话"引用进日报；
      2. 浏览台的明细页会把乱码直接摊在读者面前。
    所以在这里就换成可读的占位符，不让它流到下游。

    判据取 10%：正常中文/英文文本里几乎没有控制字符，而乱码样本里密密麻麻。
    """
    if not s:
        return False
    sample = s[:200]
    bad = sum(1 for ch in sample
              if ch == "\ufffd" or (ch < " " and ch not in "\n\t\r"))
    return bad / len(sample) >= 0.10


class MessageReader:
    def __init__(self, db_dir=None, shards: int | None = None):
        self.db_dir = config.db_dir(db_dir)
        self.msg_dir = os.path.join(self.db_dir, "message")
        self.contact_db = os.path.join(self.db_dir, "contact", "contact.db")
        if shards is None:
            self.shard_paths = self._discover_shards()
        else:
            # 留个口子：测试或特殊场景可以只读前 N 个分片
            self.shard_paths = [
                os.path.join(self.msg_dir, f"message_{i}.db")
                for i in range(shards)
                if os.path.exists(os.path.join(self.msg_dir, f"message_{i}.db"))
            ]
        if not self.shard_paths:
            raise FileNotFoundError(f"找不到消息库: {self.msg_dir}")
        self._conns = {}

    def _discover_shards(self) -> list[str]:
        """扫描 message_N.db，不写死数量

        微信会按容量扩容分片（当前是 3 个，将来可能是 4 个、5 个）。
        原来写死 range(3)，第 4 片建出来之后，那里的消息会**永远读不到且不报错**——
        日报只是少一块内容，看起来完全正常。所以这里按目录实际内容发现。
        """
        found = []
        for name in os.listdir(self.msg_dir):
            if not (name.startswith("message_") and name.endswith(".db")):
                continue
            idx = name[len("message_"):-len(".db")]
            if idx.isdigit():          # 排除 message_fts.db / message_resource.db
                found.append((int(idx), os.path.join(self.msg_dir, name)))
        found.sort()
        return [p for _i, p in found]

    # ---------- 连接管理 ----------

    def _conn(self, path):
        if path not in self._conns:
            self._conns[path] = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return self._conns[path]

    def close(self):
        for c in self._conns.values():
            c.close()
        self._conns.clear()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ---------- 元数据 ----------

    def _sender_map(self, path) -> dict[int, str]:
        """Name2Id row IDs are local to the source shard."""
        return dict(self._conn(path).execute("select rowid, user_name from Name2Id"))

    def _display_names(self, usernames: set[str]) -> dict[str, str]:
        out = {}
        if not usernames:
            return out
        cn = sqlite3.connect(f"file:{self.contact_db}?mode=ro", uri=True)
        try:
            cur = cn.execute("select username, nick_name, remark from contact")
            for uname, nick, remark in cur:
                if uname in usernames:
                    out[uname] = remark or nick or uname
        finally:
            cn.close()
        return out

    def has_messages(self, chat: Chat) -> bool:
        t = table_of(chat.username)
        for p in self.shard_paths:
            try:
                if self._conn(p).execute(
                    "select 1 from sqlite_master where type='table' and name=?", (t,)
                ).fetchone():
                    return True
            except sqlite3.Error:
                pass
        return False

    def last_message_time(self, chat: Chat):
        t = table_of(chat.username)
        last = 0
        for p in self.shard_paths:
            try:
                row = self._conn(p).execute(f'select max(create_time) from "{t}"').fetchone()
                if row and row[0]:
                    last = max(last, row[0])
            except sqlite3.Error:
                pass
        return datetime.fromtimestamp(last) if last else None

    # ---------- 读取 ----------

    def fetch(self, chat: Chat, start: datetime, end: datetime,
              limit: int | None = None) -> list[Message]:
        table = table_of(chat.username)
        s_ts, e_ts = int(start.timestamp()), int(end.timestamp())
        rows = []
        for p in self.shard_paths:
            try:
                exists = self._conn(p).execute(
                    "select 1 from sqlite_master where type='table' and name=?", (table,)
                ).fetchone()
                if not exists:
                    continue
                rows.extend((*row, p) for row in self._conn(p).execute(
                    f'select local_id, create_time, real_sender_id, local_type, message_content '
                    f'from "{table}" where create_time>=? and create_time<? order by create_time',
                    (s_ts, e_ts),
                ).fetchall())
            except sqlite3.Error as error:
                raise CoverageError(p) from error

        rows.sort(key=lambda r: (r[1], r[0]))
        if limit:
            rows = rows[-limit:]

        id2name = {}
        for path in {r[5] for r in rows}:
            try:
                id2name[path] = self._sender_map(path)
            except sqlite3.Error as error:
                raise CoverageError(path, 'SENDER_MAP_FAILED') from error
        # 把 type49（App 消息）和 type34（语音）的 blob 收集起来一次性解压
        blob_positions, blobs = [], []
        for i, (_lid, _ct, _sid, ltype, raw, _path) in enumerate(rows):
            if content.base_type(ltype) in (49, 34) and isinstance(raw, (bytes, bytearray)):
                blob_positions.append(i)
                blobs.append(bytes(raw))
        decoded = {}
        if blobs:
            for i, out in zip(blob_positions, content.batch_decode_payloads(blobs)):
                decoded[i] = out

        # 发送者
        usernames = {id2name[r[5]].get(r[2]) for r in rows}
        usernames.discard(None)
        disp = self._display_names(usernames)
        # 兜底：从消息内容前缀里抽 wxid
        def resolve_sender(sid, raw, path):
            uname = id2name[path].get(sid, "")
            if not uname and isinstance(raw, str) and ":\n" in raw[:80]:
                uname = raw.split(":\n", 1)[0]
            name = disp.get(uname) or uname or f"id{sid}"
            return name, uname

        msgs: list[Message] = []
        for i, (lid, ct, sid, ltype, raw, path) in enumerate(rows):
            base = content.base_type(ltype)
            sub = content.sub_type(ltype)
            sender, sender_uname = resolve_sender(sid, raw, path)
            payload = decoded.get(i, raw if isinstance(raw, (bytes, bytearray)) else None)
            app = None
            voice = None
            if base == 49:
                if payload:
                    txt = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
                    app = content.parse_appmsg(txt)
                    text = content.describe(base, sub, app)
                else:
                    text = "[App消息·无法解压]"
            elif base == 1:
                s = raw if isinstance(raw, str) else (bytes(raw).decode("utf-8", "replace") if raw else "")
                text = content.strip_sender_prefix(s)
            elif base == 34:
                if payload:
                    txt = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
                    v = content.parse_voicemsg(txt)
                    text = content.voice_label(v["duration_ms"])
                    voice = v
                else:
                    text = "[语音]"
            elif base == 10000:
                s = raw if isinstance(raw, str) else (bytes(raw).decode("utf-8", "replace") if raw else "")
                text = content.strip_sender_prefix(s)[:200]
            else:
                text = content.describe(base, sub, None)

            # 解不开的二进制换成人能读的占位符（见 looks_undecoded）
            if looks_undecoded(text):
                text = "[系统消息]" if base == 10000 else "[无法解析的消息]"

            msgs.append(Message(
                local_id=lid,
                source_shard=os.path.basename(path),
                ts=datetime.fromtimestamp(ct, start.tzinfo),
                sender=sender,
                sender_username=sender_uname,
                base=base,
                sub=sub,
                text=text,
                app=app,
                voice=voice,
            ))
        return msgs

    @staticmethod
    def summarize(msgs: list[Message]) -> FetchStats:
        st = FetchStats()
        for m in msgs:
            st.total += 1
            st.senders[m.sender] = st.senders.get(m.sender, 0) + 1
            tname = content.BASE_TYPES.get(m.base, str(m.base))
            st.types[tname] = st.types.get(tname, 0) + 1
            if m.base == 1:
                st.text_count += 1
                st.chars += len(m.text)
        return st
