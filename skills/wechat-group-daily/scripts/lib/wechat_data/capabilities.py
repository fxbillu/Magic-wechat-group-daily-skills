"""Non-mutating capability probes shared by onboarding and doctor."""
from contextlib import closing
from datetime import datetime, timezone as utc_timezone
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfo

from . import config


def result(available, code, next_action, *, required=True, detail=None):
    return {'available': bool(available), 'required': required,
            'code': None if available else code, 'next_action': None if available else next_action,
            'detail': detail}


def probe(timezone=None, browser=None):
    try:
        with closing(sqlite3.connect(':memory:')) as cn:
            assert cn.execute('SELECT 1').fetchone()[0] == 1
            cn.execute('CREATE TABLE probe(id INTEGER PRIMARY KEY, value TEXT)')
            cn.execute("INSERT INTO probe VALUES(1,'中文') ON CONFLICT(id) DO UPDATE SET value=excluded.value")
            assert json.loads(json.dumps({'text': '中文'}))['text'] == '中文'
            assert len(hashlib.sha256(b'probe').digest()) == 32
        core = sys.version_info >= (3, 11)
    except Exception:
        core = False
    output = {'python_core': result(core, 'PYTHON_CAPABILITY_MISSING', 'repair_python_environment',
                                   detail='.'.join(map(str, sys.version_info[:3])))}
    # AES-256-CBC known-answer vector, independently checked against OpenSSL.
    key = bytes.fromhex('603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4')
    iv = bytes.fromhex('000102030405060708090a0b0c0d0e0f')
    ciphertext = bytes.fromhex('f58c4c04d6e5f1ba779eabfb5f7bfbd6')
    plaintext = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
    import importlib.util
    spec = importlib.util.spec_from_file_location('daily_aes_probe', os.path.join(config.TOOLS_DIR, 'safe_decrypt.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        aes_ok = module.aes_cbc_decrypt(key, iv, ciphertext) == plaintext
    except Exception:
        aes_ok = False
    output['aes_decrypt'] = result(aes_ok, 'AES_DECRYPT_UNAVAILABLE', 'repair_cng_or_cryptography_in_selected_python')
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        decoder = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        crypto = decoder.update(ciphertext) + decoder.finalize() == plaintext
    except Exception:
        crypto = False
    output['cryptography'] = result(crypto, 'CRYPTOGRAPHY_UNAVAILABLE', 'configure_python_crypto_fallback_if_needed', required=False)
    try:
        if not timezone:
            raise ValueError('timezone not confirmed')
        zone = utc_timezone.utc if timezone == 'UTC' else ZoneInfo(timezone)
        assert datetime.now(zone).utcoffset() is not None
        zone_ok = True
    except Exception:
        zone_ok = False
    output['timezone'] = result(zone_ok, 'TIMEZONE_UNAVAILABLE' if timezone else 'TIMEZONE_NOT_CONFIRMED',
                                'repair_timezone_in_workbuddy', detail=timezone)
    # A single-segment Zstd frame containing a raw "hello" block.
    javascript = """const z=require('node:zlib');
const b=Buffer.from('28b52ffd200529000068656c6c6f','hex');
if(typeof z.zstdDecompressSync!=='function'||z.zstdDecompressSync(b).toString()!=='hello')process.exit(2);
process.stdout.write('zstd-ok');"""
    try:
        checked = subprocess.run([config.node_exe(), '-e', javascript], capture_output=True,
                                 text=True, timeout=8)
        node_ok = checked.returncode == 0 and checked.stdout == 'zstd-ok'
    except (OSError, subprocess.SubprocessError):
        node_ok = False
    output['node_zstd'] = result(node_ok, 'NODE_ZSTD_UNAVAILABLE', 'configure_node_with_zstd_support')
    if browser is None:
        # Import only the renderer's discovery function; never launch rendering here.
        import importlib.util
        filename = os.path.join(config.TOOLS_DIR, 'render_daily.py')
        spec = importlib.util.spec_from_file_location('daily_browser_probe', filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        browser = module.find_browser()
    try:
        checked = subprocess.run([browser, '--version'], capture_output=True, text=True, timeout=8) if browser else None
        browser_ok = checked is not None and checked.returncode == 0 and bool((checked.stdout or checked.stderr).strip())
    except (OSError, subprocess.SubprocessError):
        browser_ok = False
    output['png_browser'] = result(browser_ok, 'PNG_BROWSER_UNAVAILABLE', 'open_html_in_host_browser',
                                   required=False, detail='binary_probe_only' if browser_ok else None)
    output['voice'] = {'available': None, 'required': False, 'code': 'NOT_CHECKED',
                       'next_action': 'configure_voice_only_if_requested', 'detail': None}
    return output


def required_ready(capabilities):
    return all(item['available'] is True for item in capabilities.values() if item['required'])
