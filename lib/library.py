"""素材库、音色注册表与产出管理（仅标准库）。

目录布局（数据根目录下）：
  materials/<音色名>/*.wav|mp3|m4a   素材
  outputs/                            合成产出
  voices.json                         音色注册表
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from lib import config

_UNSAFE = re.compile(r'[\\/:*?"<>|]+')
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac"}
_INCOMING = "_incoming"


def sanitize_name(name: str) -> str:
    cleaned = _UNSAFE.sub("_", str(name or "").strip())
    return cleaned[:60] or "unnamed"


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in _AUDIO_EXTS


def materials_dir(voice_name: str) -> Path:
    d = config.data_root() / "materials" / sanitize_name(voice_name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_material(voice_name: str, src: str | Path) -> Path:
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"素材文件不存在: {src}")
    if not is_audio_file(src):
        raise ValueError(
            f"不支持的音频格式 {src.suffix}（支持 wav/mp3/m4a/flac/ogg/opus/aac）"
        )
    dest = materials_dir(voice_name) / src.name
    stem, suffix = src.stem, src.suffix
    i = 1
    while dest.exists() and dest.stat().st_size != src.stat().st_size:
        dest = materials_dir(voice_name) / f"{stem}_{i}{suffix}"
        i += 1
    shutil.copy2(src, dest)
    return dest


def list_materials(voice_name: str) -> list[dict]:
    d = materials_dir(voice_name)
    items = []
    for p in sorted(d.iterdir()):
        if p.is_file() and is_audio_file(p):
            items.append(
                {"name": p.name, "size": p.stat().st_size, "path": str(p)}
            )
    return items


def list_material_voices() -> list[str]:
    base = config.data_root() / "materials"
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and p.name != _INCOMING and any(is_audio_file(f) for f in p.iterdir())
    )


def find_material(voice_name: str, filename: str | None = None) -> Path:
    d = materials_dir(voice_name)
    if filename:
        p = d / sanitize_name(Path(filename).name)
        if p.is_file():
            return p
        raise FileNotFoundError(f"素材 {filename} 不在音色「{voice_name}」的素材库中")
    files = [p for p in sorted(d.iterdir()) if p.is_file() and is_audio_file(p)]
    if not files:
        raise FileNotFoundError(
            f"音色「{voice_name}」还没有入库素材。请先在面板上传或用 voice_material_add 添加"
            "（要求：≥10 秒清晰人声，无伴奏/混响/噪音，wav/mp3/m4a）"
        )
    return files[0]


# ---- 音色注册表 ----

def _registry_path() -> Path:
    return config.data_root() / "voices.json"


def load_registry() -> dict:
    p = _registry_path()
    if not p.is_file():
        return {"voices": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"voices": []}
    if not isinstance(data.get("voices"), list):
        data["voices"] = []
    return data


def save_registry(reg: dict) -> None:
    _registry_path().write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def upsert_voice(entry: dict) -> dict:
    reg = load_registry()
    entry = dict(entry)
    entry["name"] = sanitize_name(entry.get("name", ""))
    for i, existing in enumerate(reg["voices"]):
        if existing["name"] == entry["name"]:
            for k, v in entry.items():
                if v not in (None, ""):
                    existing[k] = v
            save_registry(reg)
            return existing
    entry.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    reg["voices"].append(entry)
    save_registry(reg)
    return entry


def get_voice(name: str) -> dict | None:
    name = sanitize_name(name)
    for v in load_registry()["voices"]:
        if v["name"] == name:
            return v
    return None


def remove_voice(name: str) -> bool:
    reg = load_registry()
    before = len(reg["voices"])
    reg["voices"] = [v for v in reg["voices"] if v["name"] != sanitize_name(name)]
    save_registry(reg)
    return len(reg["voices"]) < before


def list_voices() -> list[dict]:
    return load_registry()["voices"]


# ---- 产出 ----

def save_output(voice_name: str, ext: str, data: bytes) -> Path:
    out_dir = config.data_root() / "outputs"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = sanitize_name(voice_name)
    p = out_dir / f"{safe}_{stamp}.{ext}"
    i = 1
    while p.exists():
        p = out_dir / f"{safe}_{stamp}_{i}.{ext}"
        i += 1
    p.write_bytes(data)
    return p


def save_generated_material(voice_name: str, ext: str, data: bytes) -> Path:
    """把模型生成的音频直接写入某音色名下的素材库。"""
    d = materials_dir(voice_name)
    p = d / f"生成_{time.strftime('%m%d_%H%M%S')}.{ext}"
    i = 1
    while p.exists():
        p = d / f"生成_{time.strftime('%m%d_%H%M%S')}_{i}.{ext}"
        i += 1
    p.write_bytes(data)
    return p


def list_outputs(limit: int = 50) -> list[dict]:
    out_dir = config.data_root() / "outputs"
    files = [p for p in out_dir.iterdir() if p.is_file()]
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    items = []
    for p in files[:limit]:
        items.append(
            {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
        )
    return items
