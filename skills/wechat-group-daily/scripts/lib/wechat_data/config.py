"""路径与运行环境配置

数据层只读「解密后」的数据库目录，不负责解密。
解密产物由 tools/wcdb_key_tool_windows.py 生成，目录结构与微信原始
db_storage 一致：

    decrypted/
      message/message_0.db  message_1.db  message_2.db
      contact/contact.db
      session/session.db
      head_image/head_image.db
      ...
"""
import os
import shutil

# lib/wechat_data/config.py -> 项目根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_DB_DIR = os.path.join(ROOT, "decrypted")
TOOLS_DIR = os.path.join(ROOT, "tools")


def _node_candidates():
    """Node 查找顺序：显式指定 → PATH → 常见安装位置

    不再写死某个用户目录，换机器也能找到。
    """
    out = []
    env = os.environ.get("WECHAT_NODE")
    if env:
        out.append(env)
    found = shutil.which("node")
    if found:
        out.append(found)
    out += [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.expanduser(r"~\AppData\Roaming\npm\node.exe"),
    ]
    return out


NODE_CANDIDATES = _node_candidates()


def db_dir(path=None) -> str:
    """解析数据库目录

    优先级：显式参数 > 环境变量 WECHAT_DATA_DIR > config.json > 项目内 decrypted/
    """
    p = path or os.environ.get("WECHAT_DATA_DIR")
    if not p:
        try:
            from . import settings
            p = settings.decrypted_dir()
        except Exception:
            p = None
    p = p or DEFAULT_DB_DIR
    if not os.path.isdir(p):
        raise FileNotFoundError(f"数据库目录不存在: {p}")
    return p


def node_exe():
    for c in NODE_CANDIDATES:
        if not c:
            continue
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        else:
            return c
    return "node"
