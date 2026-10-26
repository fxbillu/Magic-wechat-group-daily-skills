"""带一致性保证的数据库解密

修复原解密流程的静默错误：原实现直接逐页读源库，微信同时在写，
产物可能混合两个时刻的页，轻则读到旧数据，重则 SQLite 报损坏。

这里的做法是「稳定快照」：

    记录源文件指纹 → 复制副本 → 再记录指纹 → 两次一致才算稳定

不一致说明复制期间微信写过，重试最多 3 次；始终不稳定则明确报错，
而不是硬着头皮产出可能撕裂的文件。

用法：
    python safe_decrypt.py --db-dir <原始 db_storage> --keys all_keys.json --output decrypted
    python safe_decrypt.py --db-dir ... --only message/message_0.db   # 只解一个
"""
import argparse
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "tools"))
sys.path.insert(0, os.path.join(BASE, "lib"))

PAGE_SZ = 4096
RESERVE_SZ = 80
IV_SZ = 16
SALT_SZ = 16
HMAC_SZ = 64
SQLITE_HDR = b"SQLite format 3\x00"


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-256-CBC 解密，优先 Windows CNG，其次 cryptography"""
    try:
        import ctypes
        import ctypes.wintypes as wt
        bcrypt = ctypes.WinDLL("bcrypt")
        bcrypt.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(wt.HANDLE),
                                                       ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
        bcrypt.BCryptSetProperty.argtypes = [wt.HANDLE, ctypes.c_wchar_p, ctypes.c_char_p,
                                             ctypes.c_ulong, ctypes.c_ulong]
        bcrypt.BCryptGenerateSymmetricKey.argtypes = [wt.HANDLE, ctypes.POINTER(wt.HANDLE),
                                                     ctypes.c_char_p, ctypes.c_ulong,
                                                     ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong]
        bcrypt.BCryptDecrypt.argtypes = [wt.HANDLE, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_void_p,
                                         ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p,
                                         ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong]
        h_alg = wt.HANDLE()
        if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h_alg), "AES", None, 0) == 0:
            mode = ("ChainingModeCBC\x00").encode("utf-16-le")
            bcrypt.BCryptSetProperty(h_alg, "ChainingMode", mode, len(mode), 0)
            h_key = wt.HANDLE()
            if bcrypt.BCryptGenerateSymmetricKey(h_alg, ctypes.byref(h_key), None, 0,
                                                 key, len(key), 0) == 0:
                iv_buf = ctypes.create_string_buffer(iv, len(iv))
                out = ctypes.create_string_buffer(len(data))
                got = ctypes.c_ulong(0)
                if bcrypt.BCryptDecrypt(h_key, data, len(data), None, iv_buf, len(iv),
                                        out, len(out), ctypes.byref(got), 0) == 0:
                    res = out.raw[:got.value]
                    bcrypt.BCryptDestroyKey(h_key)
                    bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)
                    return res
                bcrypt.BCryptDestroyKey(h_key)
            bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)
    except Exception:
        pass

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return d.update(data) + d.finalize()


def verify_key(enc_key: bytes, page1: bytes) -> bool:
    import hashlib
    import hmac
    salt = page1[:SALT_SZ]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mk = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)
    h = hmac.new(mk, page1[SALT_SZ:PAGE_SZ - RESERVE_SZ + IV_SZ], hashlib.sha512)
    h.update(struct.pack("<I", 1))
    return h.digest() == page1[PAGE_SZ - HMAC_SZ:PAGE_SZ]


def _fingerprint(path: str):
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns)


def stable_snapshot(src: str, dst: str, retries: int = 3, settle: float = 0.4) -> tuple[bool, str]:
    """复制一份内容稳定的快照；返回 (是否稳定, 说明)"""
    last = ""
    for i in range(retries):
        before = _fingerprint(src)
        shutil.copy2(src, dst)
        time.sleep(settle)
        after = _fingerprint(src)
        if before == after:
            return True, f"稳定（第 {i + 1} 次）"
        last = f"复制期间源文件发生变化 {before} -> {after}"
        time.sleep(0.6)
    return False, last


def decrypt_page(enc_key: bytes, page: bytes, pgno: int) -> bytes:
    iv = page[PAGE_SZ - RESERVE_SZ:PAGE_SZ - RESERVE_SZ + IV_SZ]
    if pgno == 1:
        plain = aes_cbc_decrypt(enc_key, iv, page[SALT_SZ:PAGE_SZ - RESERVE_SZ])
        return SQLITE_HDR + plain + b"\x00" * RESERVE_SZ
    plain = aes_cbc_decrypt(enc_key, iv, page[:PAGE_SZ - RESERVE_SZ])
    return plain + b"\x00" * RESERVE_SZ


def decrypt_one(src: str, dst: str, enc_key: bytes, quiet: bool = False) -> dict:
    """解密单个库：验 key → 稳定快照 → 逐页解密 → 校验输出"""
    info = {"src": src, "dst": dst, "ok": False, "reason": "", "pages": 0}

    size = os.path.getsize(src)
    if size < PAGE_SZ:
        info["reason"] = "文件太小"
        return info
    with open(src, "rb") as f:
        page1 = f.read(PAGE_SZ)
    if not verify_key(enc_key, page1):
        info["reason"] = "密钥与该库不匹配（HMAC 校验失败）"
        return info

    # 快照放同盘，避免跨盘拷贝
    snap_dir = os.path.dirname(dst) or "."
    os.makedirs(snap_dir, exist_ok=True)
    fd, snap = tempfile.mkstemp(suffix=".snap", dir=snap_dir)
    os.close(fd)
    try:
        ok, msg = stable_snapshot(src, snap)
        info["snapshot"] = msg
        if not ok:
            info["reason"] = f"无法取得稳定快照：{msg}"
            return info

        total = size // PAGE_SZ
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        with open(snap, "rb") as fin, open(dst, "wb") as fout:
            for pgno in range(1, total + 1):
                page = fin.read(PAGE_SZ)
                if len(page) < PAGE_SZ:
                    page = page + b"\x00" * (PAGE_SZ - len(page))
                fout.write(decrypt_page(enc_key, page, pgno))
                if not quiet and pgno % 20000 == 0:
                    print(f"    {pgno}/{total}", flush=True)
        info["pages"] = total
    finally:
        try:
            os.remove(snap)
        except OSError:
            pass

    # 校验输出确实是可读的 SQLite
    try:
        cn = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
        n = cn.execute("select count(*) from sqlite_master").fetchone()[0]
        cn.close()
        if n <= 0:
            # 只有一两页的空库（如 weclaw.db）本来就没有表，不算失败
            if info["pages"] <= 2:
                info["tables"] = 0
                info["ok"] = True
                info["reason"] = "空库（无表，属正常）"
                return info
            info["reason"] = "解密后无任何表，可能密钥或页参数不匹配"
            return info
        info["tables"] = n
        info["ok"] = True
    except sqlite3.DatabaseError as e:
        info["reason"] = f"解密产物无法打开：{e}"
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-dir", required=True, help="原始 db_storage")
    from wechat_data import settings
    ap.add_argument("--keys", default=None,
                    help="密钥文件（默认取 config.json 里 paths.secrets/all_keys.json）")
    ap.add_argument("--output", default=None,
                    help="解密产物目录（默认取 config.json 里 paths.decrypted）")
    ap.add_argument("--only", help="只解某个相对路径，如 message/message_0.db")
    ap.add_argument("--rebuild-stamp", action="store_true",
                    help="仅按现有产物重建时间戳，不解密")
    args = ap.parse_args()

    out_dir = args.output or settings.decrypted_dir()

    if args.rebuild_stamp:
        from wechat_data import guard
        d = guard.rebuild_stamp(out_dir, os.path.abspath(args.db_dir))
        print(f"[时间戳] 重建完成：{d['file_count']} 个文件，基准 {d['decrypted_at_str']}")
        return 0

    keys_path = args.keys or settings.keys_file()
    keys = json.load(open(keys_path, encoding="utf-8"))
    targets = []
    for rel, val in keys.items():
        if rel.startswith("_"):
            continue
        if args.only and rel.replace("\\", "/") != args.only.replace("\\", "/"):
            continue
        targets.append((rel, val))

    if not targets:
        print("[错误] 没有可解密的目标")
        return 2

    ok = fail = 0
    files_meta = {}
    for rel, val in targets:
        src = os.path.join(args.db_dir, rel.replace("\\", "/"))
        dst = os.path.join(out_dir, rel.replace("\\", "/"))
        if not os.path.exists(src):
            print(f"[跳过] 源文件不存在: {rel}")
            continue
        try:
            st = os.stat(src)
            files_meta[rel.replace("\\", "/")] = {"size": st.st_size,
                                                  "mtime": int(st.st_mtime)}
        except OSError:
            pass
        t0 = time.time()
        print(f"[解密] {rel} ({os.path.getsize(src) / 1024 / 1024:.1f}MB) ...", flush=True)
        info = decrypt_one(src, dst, bytes.fromhex(val["enc_key"]))
        if info["ok"]:
            ok += 1
            print(f"   OK  {info['pages']} 页 / {info['tables']} 表 / "
                  f"{info.get('snapshot', '')} / {time.time() - t0:.1f}s")
        else:
            fail += 1
            print(f"   失败: {info['reason']}")

    # 记录解密时刻，供下游做新鲜度校验
    if ok:
        try:
            from wechat_data import guard
            p = guard.write_stamp(out_dir, files_meta, os.path.abspath(args.db_dir))
            print(f"\n[时间戳] 已写入 {p}")
        except Exception as e:
            print(f"\n[warn] 时间戳写入失败：{e}")

    print(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
