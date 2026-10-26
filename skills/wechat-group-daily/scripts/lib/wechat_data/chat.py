"""会话解析：把「群名 / 昵称 / wxid」统一解析成一个确定的会话

微信里群和私聊在数据结构上是同构的——都有一张 Msg_<md5(username)> 表，
所以这里统一用 Chat 表示，只在 kind 上区分。
"""
import os
import sqlite3
from dataclasses import dataclass

from . import config


@dataclass
class Chat:
    username: str          # wxid_xxx / xxxxx@chatroom / gh_xxx
    name: str              # 展示名（备注优先）
    nick: str = ""
    remark: str = ""
    kind: str = "unknown"  # group / friend / official / openim / unknown

    @property
    def is_group(self) -> bool:
        return self.kind == "group"

    def __str__(self):
        tag = {"group": "群", "friend": "好友", "official": "公众号",
               "openim": "企业微信"}.get(self.kind, "未知")
        return f"{self.name}（{tag}, {self.username}）"


def classify(username: str) -> str:
    if username.endswith("@chatroom"):
        return "group"
    if username.endswith("@openim"):
        return "openim"
    if username.startswith("gh_"):
        return "official"
    if username.startswith("wxid_") or username.isalnum():
        return "friend"
    return "unknown"


class ChatResolver:
    """从 contact.db 解析会话"""

    def __init__(self, db_dir=None):
        self.db_dir = config.db_dir(db_dir)
        self._contact_db = os.path.join(self.db_dir, "contact", "contact.db")
        if not os.path.exists(self._contact_db):
            raise FileNotFoundError(f"找不到联系人库: {self._contact_db}")
        self._cache = None

    def all(self) -> list[Chat]:
        if self._cache is not None:
            return self._cache
        cn = sqlite3.connect(f"file:{self._contact_db}?mode=ro", uri=True)
        chats = []
        try:
            for username, nick, remark in cn.execute(
                "select username, nick_name, remark from contact "
                "where username is not null and username != ''"
            ):
                chats.append(Chat(
                    username=username,
                    name=(remark or nick or username),
                    nick=nick or "",
                    remark=remark or "",
                    kind=classify(username),
                ))
        finally:
            cn.close()
        self._cache = chats
        return chats

    def groups(self) -> list[Chat]:
        return [c for c in self.all() if c.kind == "group"]

    def friends(self) -> list[Chat]:
        return [c for c in self.all() if c.kind == "friend"]

    def search(self, keyword: str, kind: str | None = None) -> list[Chat]:
        """按关键词找会话，精确匹配优先

        kind: group / friend / None（全部）
        """
        pool = self.all()
        if kind == "group":
            pool = [c for c in pool if c.kind == "group"]
        elif kind == "friend":
            pool = [c for c in pool if c.kind == "friend"]

        exact, starts, contains = [], [], []
        kw = keyword.strip()
        for c in pool:
            if kw in (c.username, c.name, c.nick, c.remark):
                exact.append(c)
            elif c.name.startswith(kw) or c.nick.startswith(kw) or c.remark.startswith(kw):
                starts.append(c)
            elif kw in c.name or kw in c.nick or kw in c.remark:
                contains.append(c)
        return exact + starts + contains

    def resolve(self, keyword: str, kind: str | None = None) -> Chat:
        """解析出唯一会话；多个候选时抛 AmbiguousChat"""
        hits = self.search(keyword, kind)
        if not hits:
            raise LookupError(f"找不到会话：{keyword}")
        if len(hits) > 1:
            top = hits[0]
            # 若唯一精确命中，直接用
            exact = [c for c in hits if keyword in (c.username, c.name, c.nick, c.remark)]
            if len(exact) != 1:
                raise AmbiguousChat(keyword, hits)
            return exact[0]
        return hits[0]

    def get(self, username: str) -> Chat:
        for c in self.all():
            if c.username == username:
                return c
        return Chat(username=username, name=username, kind=classify(username))


class AmbiguousChat(LookupError):
    def __init__(self, keyword, candidates):
        self.keyword = keyword
        self.candidates = candidates[:12]
        lines = "\n".join(f"  - {c}" for c in self.candidates)
        super().__init__(f"「{keyword}」匹配到 {len(candidates)} 个会话，请写得更具体：\n{lines}")
