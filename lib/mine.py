"""「我的音色」语音参数持久化与试听记录（仅标准库）。

- mine_settings.json：语速/音调/音量/格式，语速音调为百分比整数（100=正常）
- audition_history.json：试听记录，含文本、语气、参数、产出文件与时间，超出限量自动截断
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from lib import config

DEFAULT_SETTINGS = {"rate": 100, "pitch": 100, "volume": 50, "format": "wav"}
_HISTORY_LIMIT = 50


def _settings_path():
    return config.data_root() / "mine_settings.json"


def _history_path():
    return config.data_root() / "audition_history.json"


def load_settings() -> dict:
    """读取持久化参数，缺失或非法字段回退默认，并夹到合法范围。"""
    result = dict(DEFAULT_SETTINGS)
    path = _settings_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULT_SETTINGS:
                    if key in data:
                        result[key] = data[key]
        except (OSError, json.JSONDecodeError):
            pass
    # 整数化 + 范围钳制
    result["rate"] = _clamp(int(result["rate"]), 50, 200)
    result["pitch"] = _clamp(int(result["pitch"]), 50, 200)
    result["volume"] = _clamp(int(result["volume"]), 0, 100)
    result["format"] = result["format"] if result["format"] in ("wav", "mp3") else "wav"
    return result


def save_settings(values: dict) -> dict:
    """合并保存设置（只接受已知字段），返回规范化后的完整设置。"""
    current = load_settings()
    for key in DEFAULT_SETTINGS:
        if key in values and values[key] not in (None, ""):
            current[key] = values[key]
    current["rate"] = _clamp(int(current["rate"]), 50, 200)
    current["pitch"] = _clamp(int(current["pitch"]), 50, 200)
    current["volume"] = _clamp(int(current["volume"]), 0, 100)
    if current["format"] not in ("wav", "mp3"):
        current["format"] = "wav"
    _settings_path().write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return current


def reset_settings() -> dict:
    """恢复默认设置并落盘。"""
    saved = dict(DEFAULT_SETTINGS)
    _settings_path().write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return saved


def list_history() -> list:
    path = _history_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def add_history(entry: dict) -> list:
    """追加一条试听记录（最新在前），超出限量截断后落盘。"""
    history = list_history()
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ts": int(time.time()),
        "text": str(entry.get("text") or "")[:200],
        "emotion": str(entry.get("emotion") or "默认"),
        "rate": _clamp(int(entry.get("rate") or 100), 50, 200),
        "pitch": _clamp(int(entry.get("pitch") or 100), 50, 200),
        "volume": _clamp(int(entry.get("volume") or 50), 0, 100),
        "format": str(entry.get("format") or "wav"),
        "file": str(entry.get("file") or ""),
        "url": str(entry.get("url") or ""),
    }
    history.insert(0, record)
    # 超出限量：被挤掉的记录连带删除对应音频，避免孤儿文件占空间
    if len(history) > _HISTORY_LIMIT:
        dropped = history[_HISTORY_LIMIT:]
        history = history[:_HISTORY_LIMIT]
        for old in dropped:
            _delete_output_file(old.get("file") or "")
    _history_path().write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return history


def _delete_output_file(filename: str) -> None:
    """安全删除 outputs 内的文件：必须解析后确认位于 outputs 目录，防路径穿越。"""
    if not filename:
        return
    try:
        out_dir = (config.data_root() / "outputs").resolve()
        target = (out_dir / filename).resolve()
        if out_dir in target.parents and target.is_file():
            target.unlink()
    except OSError:
        pass


def _clamp(value: int, low: int, high: int) -> int:
    return min(high, max(low, value))
