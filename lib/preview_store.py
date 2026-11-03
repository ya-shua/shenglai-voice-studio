"""试听音频缓存：同一音色+同一文字只合成一次，之后秒开。

存储位置：数据根目录 / preview_cache/
文件名：{provider}_{音色安全串}_{文本md5前12位}.{ext}
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from lib import config

DEFAULT_PREVIEW_TEXT = "你好，很高兴认识你，希望我的声音能陪你度过愉快的一天。"


def _dir() -> Path:
    d = config.data_root() / "preview_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stem(provider: str, voice_id: str, text: str) -> str:
    th = hashlib.md5((text or "").strip().encode("utf-8")).hexdigest()[:12]
    safe = "".join(c for c in (voice_id or "") if c.isalnum())[:24] or "voice"
    return f"{provider}_{safe}_{th}"


def _key(provider: str, voice_id: str, text: str, ext: str = "mp3") -> str:
    return _stem(provider, voice_id, text) + "." + (ext or "mp3").lstrip(".").lower()


def get(provider: str, voice_id: str, text: str, ext: str | None = None) -> Path | None:
    """ext 省略时通配 mp3/wav 等常见扩展。"""
    stem = _stem(provider, voice_id, text)
    d = _dir()
    if ext:
        p = d / _key(provider, voice_id, text, ext)
        return p if p.is_file() else None
    for e in ("mp3", "wav", "ogg", "flac", "m4a"):
        p = d / (stem + "." + e)
        if p.is_file():
            return p
    return None


def put(provider: str, voice_id: str, text: str, data: bytes, ext: str = "mp3") -> Path:
    p = _dir() / _key(provider, voice_id, text, ext)
    p.write_bytes(data)
    return p


def has_default(provider: str, voice_id: str) -> bool:
    return get(provider, voice_id, DEFAULT_PREVIEW_TEXT) is not None
