"""官方试听样音导入：从各模型官方文档页抓取预置音色的官方试听音频。

- 阿里百炼：CosyVoice 音色列表页挂有每个官方音色的试听 mp3（help-static 域，公开可取），
  解析「voice 参数 → mp3」映射，24h 缓存到数据目录。
- 用途：大厅在模型未接入 Key 时，仍可播放该音色的官方样音（免费、无需 Key）；
  自定义文字试听仍需接入对应模型。
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

from lib import config as _config

_ALI_PAGE = "https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list"
_CACHE_TTL = 86400  # 24h


def _cache_path() -> str:
    return str(_config.data_root() / "ali_demo_cache.json")


def _fetch_mapping() -> dict:
    """抓取并解析阿里官方音色列表页 → {voice_id: {url, name}}。"""
    req = urllib.request.Request(_ALI_PAGE, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    mapping: dict = {}
    for row in re.split(r"<tr>", html):
        voices = re.findall(r"<code>([a-zA-Z][\w]*?)_v\d</code>", row) or \
                 re.findall(r"<code>([a-zA-Z][\w]*?)</code>", row)
        mp3s = re.findall(r"(https://help-static-aliyun-doc\.aliyuncs\.com/[^\"\s<>]+\.mp3)", row)
        name = re.findall(r"<strong>名称</strong>：([^<]+)<", row)
        if voices and mp3s:
            for v in set(voices):
                mapping[v] = {"url": mp3s[0],
                              "name": name[0].strip() if name else v}
    return mapping


def _load_mapping() -> dict:
    path = _cache_path()
    try:
        if time.time() - __import__("os").path.getmtime(path) < _CACHE_TTL:
            return json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    try:
        mapping = _fetch_mapping()
        open(path, "w", encoding="utf-8").write(json.dumps(mapping, ensure_ascii=False))
        return mapping
    except Exception:
        return {}


_SF_URL = ("https://sf-maas-uat-prod.oss-cn-shanghai.aliyuncs.com/voice_template/"
           "fish_audio-{name}.mp3")


def official_demo(provider_id: str, voice_id: str):
    """返回 (mp3_url, 名称) 或 None。

    - bailian：官方文档页解析的样音映射（精确 → 去 _v2/_v3 后缀）
    - siliconflow：预置音色官方样音按命名规则直拼（Alex/Benjamin/...）
    """
    if provider_id == "siliconflow":
        name = (voice_id or "").split(":")[-1].strip()
        if name:
            return _SF_URL.format(name=name.capitalize()), name
        return None
    if provider_id != "bailian":
        return None
    mapping = _load_mapping()
    if not mapping:
        return None
    vid = (voice_id or "").strip()
    hit = mapping.get(vid)
    if not hit:
        base = re.sub(r"_v\d$", "", vid)
        hit = mapping.get(base) or mapping.get(base + "_v2") or mapping.get(base + "_v3")
    if not hit:
        return None
    return hit["url"], hit.get("name", vid)


# 阿里文档页里混进来的情绪标签行（非音色，清洗用）
_NOISE_KEYS = {"sad", "happy", "neutral", "surprised", "angry", "fearful",
               "disgusted", "calm", "gentle", "serious"}


def ali_voices_full() -> list:
    """阿里官方文档页解析出的全部预置音色（清洗情绪噪音行）。

    返回 [{voice_id, name, url}]——每项都带官方试听 mp3（免费无需 Key）。
    """
    mapping = _load_mapping()
    out = []
    for k, v in mapping.items():
        if k.lower() in _NOISE_KEYS:
            continue
        if not (v.get("url") or "").startswith("http"):
            continue
        out.append({"voice_id": k, "name": v.get("name", k), "url": v["url"]})
    return out
