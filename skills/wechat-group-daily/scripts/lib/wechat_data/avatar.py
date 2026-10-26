"""头像读取：从 head_image.db 取真实头像，转成可直接内嵌 HTML 的 data URI

微信 4.x 的 head_image 表里 image_buffer 就是**明文 JPEG**（ffd8ff 开头），
不需要解密图片，直接 base64 内嵌即可。
"""
import base64
import os
import sqlite3

from . import config

_CACHE: dict[tuple[str, str], str | None] = {}


def _db_path(db_dir=None) -> str:
    return os.path.join(config.db_dir(db_dir), "head_image", "head_image.db")


def _mime(blob: bytes) -> str:
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if blob[:4] == b"GIF8":
        return "image/gif"
    return "image/jpeg"


def get_avatar(username: str, db_dir=None) -> str | None:
    """单个头像，返回 data URI；没有则 None"""
    if not username:
        return None
    key = (str(db_dir or ""), username)
    if key in _CACHE:
        return _CACHE[key]
    path = _db_path(db_dir)
    if not os.path.exists(path):
        _CACHE[key] = None
        return None
    cn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = cn.execute(
            "select image_buffer from head_image where username=?", (username,)
        ).fetchone()
    finally:
        cn.close()
    if not row or not row[0]:
        _CACHE[key] = None
        return None
    blob = bytes(row[0])
    uri = f"data:{_mime(blob)};base64," + base64.b64encode(blob).decode("ascii")
    _CACHE[key] = uri
    return uri


def get_avatars(usernames, db_dir=None) -> dict[str, str]:
    """批量取头像（按 400 个一批做 IN 查询）"""
    want = [u for u in dict.fromkeys(usernames) if u]
    out: dict[str, str] = {}
    if not want:
        return out
    path = _db_path(db_dir)
    if not os.path.exists(path):
        return out

    cn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for i in range(0, len(want), 400):
            batch = want[i:i + 400]
            ph = ",".join("?" * len(batch))
            try:
                rows = cn.execute(
                    f"select username, image_buffer from head_image where username in ({ph})",
                    batch,
                ).fetchall()
            except sqlite3.Error:
                continue
            for uname, buf in rows:
                if buf:
                    blob = bytes(buf)
                    out[uname] = f"data:{_mime(blob)};base64," + base64.b64encode(blob).decode("ascii")
    finally:
        cn.close()
    return out


def resolve_names_to_users(names, db_dir=None) -> dict[str, str]:
    """把显示名映射到 username（完全匹配优先，其次是包含匹配）

    **只在唯一命中时才认。** 重名一律不猜：
    日报里的人名来自聊天记录，两个同名成员（或一个备注撞上别人的昵称）
    取错人的后果是给 A 配上 B 的脸，读者不会察觉，但人是错的——
    这比"没有头像"糟得多。取不到头像时下游会退回首字圆形，视觉上只是退一档。
    """
    from .chat import ChatResolver
    try:
        chats = ChatResolver(db_dir).all()
    except FileNotFoundError:
        return {}
    out: dict[str, str] = {}
    for name in dict.fromkeys(n for n in names if n):
        exact = [c for c in chats if name in (c.remark, c.nick, c.name)]
        if len(exact) == 1:
            out[name] = exact[0].username
            continue
        if len(exact) > 1:
            continue                      # 重名：宁缺毋滥
        fuzzy = [c for c in chats if name in c.name or name in c.nick or name in c.remark]
        if len(fuzzy) == 1:
            out[name] = fuzzy[0].username
    return out
