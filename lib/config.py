"""数据根目录与供应商配置管理（仅标准库）。

数据根目录解析顺序：
1. 环境变量 VOICE_STUDIO_HOME
2. D:/AI/声音工坊（存在 D:/AI 时）
3. ~/.voice-studio

config.json 与素材、音色注册表同住数据根目录，密钥只落本地磁盘，不进对话上下文。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "voice-studio"
VERSION = "1.8.0"

_DEFAULT_CONFIG = {
    "version": 1,
    "providers": {
        # 阿里云百炼（内置适配器）
        "bailian": {
            "api_key": "",
            "workspace_id": "",          # 可选：填入后启用 MaaS 接口（cosyvoice-v3/v3.5）
            "target_model": "cosyvoice-v2",
        }
    },
    "custom": {},                        # 自定义供应商: <id> -> 定义（自由接入）
}


def _default_data_root() -> Path:
    env = os.environ.get("VOICE_STUDIO_HOME", "").strip()
    if env:
        return Path(env)
    candidate = Path("D:/AI/声音工坊")
    try:
        if candidate.parent.is_dir():
            return candidate
    except OSError:
        pass
    return Path.home() / ".voice-studio"


def data_root() -> Path:
    root = _default_data_root()
    (root / "materials").mkdir(parents=True, exist_ok=True)
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    return root


def _config_path() -> Path:
    return data_root() / "config.json"


def load_config() -> dict:
    path = _config_path()
    merged = json.loads(json.dumps(_DEFAULT_CONFIG))
    if not path.is_file():
        return merged
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return merged
    for section in ("providers", "custom"):
        if isinstance(cfg.get(section), dict):
            for key, value in cfg[section].items():
                if isinstance(value, dict):
                    merged[section].setdefault(key, {})
                    merged[section][key].update(value)
                else:
                    merged[section][key] = value
    return merged


def save_config(cfg: dict) -> None:
    _config_path().write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def provider_config(provider_id: str) -> dict:
    cfg = load_config()
    if provider_id.startswith("custom:"):
        return dict(cfg["custom"].get(provider_id[len("custom:"):], {}))
    return dict(cfg["providers"].get(provider_id, {}))


def set_provider_config(provider_id: str, values: dict) -> dict:
    cfg = load_config()
    if provider_id.startswith("custom:"):
        section, cid = cfg["custom"], provider_id[len("custom:"):]
    else:
        section, cid = cfg["providers"], provider_id
    entry = section.setdefault(cid, {})
    for key, value in (values or {}).items():
        entry[key] = value
    save_config(cfg)
    return dict(entry)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "****"
    return value[:4] + "****" + value[-4:]


def public_config() -> dict:
    """脱敏后的配置视图（面板展示用，密钥打码）。"""
    cfg = load_config()
    view: dict = {"providers": {}, "custom": {}}
    for pid, entry in cfg["providers"].items():
        cleaned = {}
        for k, v in entry.items():
            if isinstance(v, str) and "key" in k.lower() and v:
                cleaned[k] = mask_secret(v)
            else:
                cleaned[k] = v
        view["providers"][pid] = cleaned
    for cid, entry in cfg["custom"].items():
        cleaned = dict(entry)
        if cleaned.get("api_key"):
            cleaned["api_key"] = mask_secret(cleaned["api_key"])
        view["custom"][cid] = cleaned
    return view
