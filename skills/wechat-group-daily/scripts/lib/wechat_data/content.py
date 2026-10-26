"""消息内容解析

微信 4.x 的消息有两层编码需要处理：

1. **local_type 是复合整数**：低 32 位是基础类型，高 32 位是 App 消息子类型。
   例如 21474836529 = (5 << 32) | 49，表示 type 49（App 消息）下的类型 5（链接）。

2. **type 49 的内容是 zstd 压缩的 XML**（魔数 28 B5 2F FD），
   标准 sqlite3 读出来是二进制乱码。解压后才能看到 <appmsg> 结构。
"""
import os
import re
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from . import config

TYPE_MASK = 0xFFFFFFFF

# 基础类型
BASE_TYPES = {
    1: "text",
    3: "image",
    34: "voice",
    42: "card",
    43: "video",
    47: "sticker",
    48: "location",
    49: "app",
    50: "call",
    10000: "system",
    10002: "revoke",
}

# App 消息（<appmsg><type>）子类型 → 语义
APP_SUBTYPES = {
    3: "music",
    4: "video_link",
    5: "link",
    6: "file",
    19: "forward",
    24: "note",
    33: "miniprogram",
    36: "miniprogram",
    51: "channels",
    57: "channels_live",
    62: "pat",
    63: "video_account",
    2000: "transfer",
    2001: "redpacket",
    2003: "redpacket",
}

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def base_type(local_type: int) -> int:
    return int(local_type) & TYPE_MASK


def sub_type(local_type: int) -> int:
    return int(local_type) >> 32


def _node_batch_decompress(blobs: list[bytes]) -> list[bytes | None]:
    """用 Node 批量解压 zstd。协议见 tools/zstd_bridge.js"""
    if not blobs:
        return []
    node = config.node_exe()
    bridge = os.path.join(config.TOOLS_DIR, "zstd_bridge.js")
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "in.bin")
        outp = os.path.join(td, "out.bin")
        with open(inp, "wb") as f:
            for b in blobs:
                f.write(struct.pack("<I", len(b)))
                f.write(b)
        try:
            subprocess.run([node, bridge, inp, outp], check=True,
                           capture_output=True, timeout=180)
        except (subprocess.SubprocessError, FileNotFoundError):
            return [None] * len(blobs)
        data = open(outp, "rb").read()
    out = []
    pos = 0
    while pos + 4 <= len(data):
        (ln,) = struct.unpack("<I", data[pos:pos + 4])
        pos += 4
        if ln == 0:
            out.append(None)
        else:
            out.append(data[pos:pos + ln])
            pos += ln
    if len(out) < len(blobs):
        out.extend([None] * (len(blobs) - len(out)))
    return out


def batch_decode_payloads(blobs: list[bytes]) -> list[bytes | None]:
    """把一批可能是 zstd 的 blob 解开；非 zstd 的原样返回"""
    idx, targets = [], []
    for i, b in enumerate(blobs):
        if isinstance(b, (bytes, bytearray)) and bytes(b[:4]) == ZSTD_MAGIC:
            idx.append(i)
            targets.append(bytes(b))
    results: list[bytes | None] = [bytes(b) if b is not None else None for b in blobs]
    if targets:
        for i, r in zip(idx, _node_batch_decompress(targets)):
            results[i] = r
    return results


_STRIP_PREFIX_RE = re.compile(r"^[A-Za-z0-9_\-@\.]{3,64}:\n", re.S)


def strip_sender_prefix(content: str) -> str:
    """群消息内容形如 'wxid_xxx:\\n正文'，去掉发送者前缀"""
    if not content:
        return ""
    m = _STRIP_PREFIX_RE.match(content)
    return content[m.end():] if m else content


def parse_appmsg(text: str) -> dict:
    """解析 type 49 的 <appmsg> XML，抽出标题/描述/链接"""
    out = {"title": "", "des": "", "url": "", "app_type": None, "filename": ""}
    if not text:
        return out
    body = text[text.find("<msg"):] if "<msg" in text else text
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        m = re.search(r"<title>(.*?)</title>", text, re.S)
        if m:
            out["title"] = m.group(1).strip()
        return out
    app = root.find(".//appmsg")
    if app is None:
        return out

    def txt(tag):
        e = app.find(tag)
        return (e.text or "").strip() if e is not None else ""

    out["title"] = txt("title")
    out["des"] = txt("des")
    out["url"] = txt("url")
    t = txt("type")
    out["app_type"] = int(t) if t.isdigit() else None
    out["filename"] = txt("appattach/filename") or txt("filename")
    return out


def parse_voicemsg(text: str) -> dict:
    """解析 type 34 的 <voicemsg>，取出时长与格式

    微信不缓存转写文本，XML 里只有：
        <voicemsg voicelength="22306" voiceformat="4" ... />
    voicelength 单位是毫秒。
    """
    out = {"duration_ms": 0, "format": None}
    if not text:
        return out
    m = re.search(r'voicelength="(\d+)"', text)
    if m:
        out["duration_ms"] = int(m.group(1))
    m = re.search(r'voiceformat="(\d+)"', text)
    if m:
        out["format"] = int(m.group(1))
    return out


def voice_label(duration_ms: int) -> str:
    """语音占位标签，带时长"""
    if not duration_ms:
        return "[语音]"
    sec = max(1, round(duration_ms / 1000))
    if sec < 60:
        return f"[语音 {sec}\"]"
    return f"[语音 {sec // 60}:{sec % 60:02d}]"


def describe(base: int, sub: int, app: dict | None) -> str:
    """生成人类可读的类型标签"""
    if base == 49 and app:
        st = app.get("app_type") or sub
        kind = APP_SUBTYPES.get(st, "app")
        title = app.get("title") or ""
        if kind == "link":
            return f"[链接] {title}" if title else "[链接]"
        if kind == "file":
            return f"[文件] {app.get('filename') or title}"
        if kind in ("channels", "channels_live", "video_account"):
            return f"[视频号] {title}" if title else "[视频号]"
        if kind == "miniprogram":
            return f"[小程序] {title}" if title else "[小程序]"
        if kind == "forward":
            return f"[合并转发] {title}" if title else "[合并转发]"
        if kind == "transfer":
            return "[转账]"
        if kind == "redpacket":
            return "[红包]"
        if kind == "music":
            return f"[音乐] {title}" if title else "[音乐]"
        if kind == "pat":
            return f"[拍一拍] {title}" if title else "[拍一拍]"
        return f"[{kind}] {title}".strip()
    label = {
        "image": "[图片]", "voice": "[语音]", "video": "[视频]",
        "sticker": "[表情]", "location": "[位置]", "card": "[名片]",
        "call": "[通话]", "revoke": "[撤回]",
    }
    return label.get(BASE_TYPES.get(base, ""), f"[{BASE_TYPES.get(base, base)}]")
