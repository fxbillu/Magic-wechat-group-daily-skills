"""Local SILK → WAV → Whisper primitives.

Daily/archive orchestration and process isolation live in voice_jobs.py.
Decoder: pilk; ASR: faster-whisper/CTranslate2 with complete local model files.
No automatic download. Use voice configure/status/retry through fetch.py.
The transcriber releases its native CTranslate2 model in close(); job process
exit is the final native-resource boundary. Model files remain reusable.
"""
import gc
import importlib.util
import os
import sqlite3
import tempfile

from . import config

SILK_MAGIC = b"#!SILK_V3"

DEFAULT_MODEL_DIR = os.path.expanduser(
    "~/.cache/huggingface/hub/models--Systran--faster-whisper-base"
)


# ---------------------------------------------------------------- SILK 取数

def _media_db(db_dir=None) -> str:
    return os.path.join(config.db_dir(db_dir), "message", "media_0.db")


def _chat_name_id(cn, username: str):
    """user_name → media_0.db 里 Name2Id.rowid（即 VoiceInfo.chat_name_id）"""
    if not username:
        return None
    row = cn.execute("select rowid from Name2Id where user_name=?", (username,)).fetchone()
    return row[0] if row else None


def load_silk(local_id: int, chat_username: str | None = None,
              db_dir=None) -> bytes | None:
    """取一条语音的 SILK blob

    **必须带 chat_username**：`local_id` 只在会话内唯一，跨会话会重复
    （实测 media_0.db 1286 行只有 1161 个不同 local_id，跨 61 个会话）。
    只按 local_id 查会取到别的会话的语音，且不会报错。

    若确实只传 local_id，仅当该 id 全局唯一时才返回，否则抛 ValueError。
    """
    path = _media_db(db_dir)
    if not os.path.exists(path):
        return None
    cn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if chat_username:
            cid = _chat_name_id(cn, chat_username)
            if cid is None:
                return None
            row = cn.execute(
                "select voice_data from VoiceInfo where local_id=? and chat_name_id=? limit 1",
                (local_id, cid),
            ).fetchone()
            return bytes(row[0]) if row and row[0] else None

        # 未给会话：仅在全局唯一时放行，避免静默取错
        rows = cn.execute(
            "select chat_name_id, voice_data from VoiceInfo where local_id=?", (local_id,)
        ).fetchall()
        if len(rows) > 1:
            raise ValueError(
                f"local_id={local_id} 在 {len(rows)} 个会话中同时存在，"
                f"必须传入 chat_username 才能确定是哪一条"
            )
        return bytes(rows[0][1]) if rows and rows[0][1] else None
    finally:
        cn.close()


def load_silk_by_local_id(local_id: int, db_dir=None) -> bytes | None:
    """【已弃用】只按 local_id 查，跨会话会取错。

    保留仅为兼容旧调用；新代码请用 `load_silk(local_id, chat_username)`。
    """
    import warnings
    warnings.warn(
        "load_silk_by_local_id 只按 local_id 查询，跨会话会取错语音；"
        "请改用 load_silk(local_id, chat_username)",
        DeprecationWarning, stacklevel=2,
    )
    return load_silk(local_id, None, db_dir)


def load_silks_for_chat(local_ids, chat_username: str, db_dir=None) -> dict:
    """批量取某会话的语音，返回 {local_id: silk}"""
    ids = [int(i) for i in dict.fromkeys(local_ids) if i is not None]
    if not ids:
        return {}
    path = _media_db(db_dir)
    if not os.path.exists(path):
        return {}
    cn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cid = _chat_name_id(cn, chat_username)
        if cid is None:
            return {}
        out = {}
        for i in range(0, len(ids), 400):
            batch = ids[i:i + 400]
            ph = ",".join("?" * len(batch))
            rows = cn.execute(
                f"select local_id, voice_data from VoiceInfo "
                f"where chat_name_id=? and local_id in ({ph})",
                [cid] + batch,
            ).fetchall()
            for lid, buf in rows:
                if buf:
                    out[lid] = bytes(buf)
        return out
    finally:
        cn.close()


def list_voice_rows(db_dir=None, limit: int | None = None):
    """列出可转写的语音（供批量任务遍历）"""
    path = _media_db(db_dir)
    if not os.path.exists(path):
        return []
    cn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        sql = ("select local_id, create_time, length(voice_data) "
               "from VoiceInfo order by create_time")
        if limit:
            sql += f" limit {int(limit)}"
        return cn.execute(sql).fetchall()
    finally:
        cn.close()


# ---------------------------------------------------------------- SILK 解码

def _wrap_wav(pcm: bytes, rate: int, channels: int = 1, width: int = 2) -> bytes:
    """给裸 PCM 套 44 字节 WAV 头"""
    import struct
    data_len = len(pcm)
    byte_rate = rate * channels * width
    block_align = channels * width
    header = b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                                    byte_rate, block_align, width * 8)
    header += b"data" + struct.pack("<I", data_len)
    return header + pcm


def silk_to_wav(silk: bytes, sample_rate: int = 24000) -> bytes:
    """SILK → WAV 字节

    微信语音常见为 24000Hz / 单声道 / 16bit。
    pilk.decode 输出裸 PCM，再手工封 WAV 头，避免引入额外音频库。
    """
    try:
        import pilk
    except ImportError as e:
        raise NotImplementedError(
            "缺少 SILK 解码器：请按授权配置 pilk"
        ) from e

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.silk")
        pcm_path = os.path.join(td, "out.pcm")
        with open(src, "wb") as f:
            f.write(bytes(silk))
        pilk.decode(src, pcm_path, pcm_rate=sample_rate)
        with open(pcm_path, "rb") as f:
            pcm = f.read()

    return _wrap_wav(pcm, sample_rate)


# ---------------------------------------------------------------- Whisper

def model_path(directory):
    """Require complete local model assets; never resolve a remote model name."""
    if not isinstance(directory, str) or not directory:
        raise ValueError('VOICE_MODEL_UNAVAILABLE')
    directory = os.path.abspath(os.path.expanduser(directory))
    required = ('model.bin', 'config.json', 'tokenizer.json')
    candidates = [directory]
    snapshots = os.path.join(directory, 'snapshots')
    if os.path.isdir(snapshots):
        candidates.extend(os.path.join(snapshots, name) for name in sorted(os.listdir(snapshots)))
    for candidate in candidates:
        if all(os.path.isfile(os.path.join(candidate, name)) for name in required):
            return candidate
    raise ValueError('VOICE_MODEL_UNAVAILABLE')

class WhisperTranscriber:
    """faster-whisper 转写器，支持上下文管理，退出时释放模型"""

    def __init__(self, model_dir: str | None = None, device: str = "cpu",
                 compute_type: str = "int8", language: str = "zh"):
        self.model_dir = model_dir or DEFAULT_MODEL_DIR
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def _ensure(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise NotImplementedError(
                "缺少 ASR 引擎：pip install ctranslate2 faster-whisper"
            ) from e
        source = model_path(self.model_dir)
        self._model = WhisperModel(source, device=self.device,
                                   compute_type=self.compute_type, local_files_only=True)

    def transcribe(self, silk: bytes) -> str:
        """单条 SILK → 文本"""
        self._ensure()
        wav = silk_to_wav(silk)
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "a.wav")
            with open(p, "wb") as f:
                f.write(wav)
            segments, _info = self._model.transcribe(
                p, language=self.language, vad_filter=True, beam_size=5
            )
            text = "".join(s.text for s in segments).strip()
        return to_simplified(text)

    def close(self):
        """显式释放模型"""
        model, self._model = self._model, None
        try:
            native = getattr(model, 'model', None)
            if native is not None and callable(getattr(native, 'unload_model', None)):
                native.unload_model()
        finally:
            del model
            gc.collect()

    def __enter__(self):
        self._ensure()
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def to_simplified(text: str) -> str:
    """whisper 中文常输出繁体，尽量转简体（没装 opencc 就原样返回）"""
    if not text:
        return text
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(text)
    except Exception:
        return text


def transcribe_one(silk: bytes, **kwargs) -> str:
    """单条转写，用完立刻释放模型"""
    t = WhisperTranscriber(**kwargs)
    try:
        return t.transcribe(silk)
    finally:
        t.close()


def transcribe_batch(blobs, progress=None, **kwargs) -> list:
    """批量转写：一次加载模型，全部结束后释放

    单条失败返回 None，不影响其他条目。
    progress: 可选回调 (index, total, text)
    """
    out = []
    t = WhisperTranscriber(**kwargs)
    try:
        t._ensure()
        total = len(blobs)
        for i, b in enumerate(blobs):
            try:
                txt = t.transcribe(b) if b else None
            except Exception:
                txt = None
            out.append(txt)
            if progress:
                try:
                    progress(i, total, txt)
                except Exception:
                    pass
    finally:
        # 关键：无论正常结束还是异常中断，都释放模型占用
        t.close()
    return out


# ---------------------------------------------------------------- 可用性

def status() -> dict:
    deps = {}
    for name in ('pilk', 'faster_whisper', 'ctranslate2', 'opencc'):
        try:
            deps[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            deps[name] = False
    try:
        model_path(DEFAULT_MODEL_DIR)
        model_ok = True
    except (OSError, ValueError):
        model_ok = False
    return {'deps': deps, 'model_cached': model_ok, 'model_dir': DEFAULT_MODEL_DIR,
            'silk_ready': deps['pilk'], 'asr_ready': deps['faster_whisper'] and deps['ctranslate2'],
            'ready': deps['pilk'] and deps['faster_whisper'] and deps['ctranslate2'] and model_ok}


if __name__ == "__main__":
    import json
    print(json.dumps(status(), indent=2, ensure_ascii=False))
