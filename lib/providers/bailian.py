"""阿里云百炼适配器：声音复刻（音色注册）+ CosyVoice 语音合成。

支持两种接口形态，按配置里是否填 workspace_id 自动切换：
- 经典 DashScope 接口（默认，只需 api_key，模型 cosyvoice-v2）
    enrollment: POST https://dashscope.aliyuncs.com/api/v1/services/audio/tts/voice-enrollment
                action: create / query / release；音色存 voice_data.audio
    synthesis : POST https://dashscope.aliyuncs.com/api/v1/services/audio/tts/generation
                参数放 parameters；音频在 output.audio.data（base64）
- MaaS 新接口（填 workspace_id 后启用，支持 cosyvoice-v3 / v3.5）
    enrollment: POST https://{ws}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization
                action: create_voice / query_voice / delete_voice；音频放 input.audio
    synthesis : POST https://{ws}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
                参数放 input；音频在 output.audio.url（24h 有效）或 output.audio.data

本地素材一律 Base64 Data URI 直传（data:audio/wav;base64,...），无需公网 URL。
素材要求：wav(16bit)/mp3/m4a，10~20 秒最佳（最长 60s），≤10MB，采样率 ≥16kHz。
"""
from __future__ import annotations

import base64
import json
import re

from lib.providers.base import (
    Provider,
    ProviderError,
    audio_data_uri,
    http_download,
    http_json,
)

CLASSIC = "https://dashscope.aliyuncs.com/api/v1"
_STATUS_READY = {"ok", "OK", "ready", "READY"}
_STATUS_BUSY = {"pending", "PENDING", "DEPLOYING", "PROCESSING", "RUNNING"}
_STATUS_FAILED = {"failed", "FAILED", "UNDEPLOYED"}


def sanitize_prefix(name: str) -> str:
    """音色前缀要求：仅字母数字、最长 10 字符，以字母开头。"""
    p = re.sub(r"[^A-Za-z0-9]", "", name or "")
    if not p or not p[0].isalpha():
        p = "vs" + p
    return p[:10]


# CosyVoice 官方预置音色（常用部分，免克隆直接用；完整列表见百炼官方音色列表文档，
# 面板与 voice_register_manual 均支持自定义音色 ID）
PRESET_VOICES = [
    {"voice_id": "longwan", "name": "龙婉", "tags": ["女声", "温柔型"], "target_model": "cosyvoice-v2"},
    {"voice_id": "longcheng", "name": "龙橙", "tags": ["男声", "沉稳型"], "target_model": "cosyvoice-v2"},
    {"voice_id": "longhua", "name": "龙华", "tags": ["男声", "播报"], "target_model": "cosyvoice-v2"},
    {"voice_id": "longxiaochun", "name": "龙小淳", "tags": ["女声", "温柔型"], "target_model": "cosyvoice-v2"},
    {"voice_id": "longxiaoxia", "name": "龙小夏", "tags": ["女声", "沉稳型"], "target_model": "cosyvoice-v2"},
    {"voice_id": "longjielidou", "name": "龙杰力斗", "tags": ["男声", "活力型"], "target_model": "cosyvoice-v2"},
    {"voice_id": "longshu", "name": "龙书", "tags": ["男声", "沉稳型", "播报"], "target_model": "cosyvoice-v2"},
    {"voice_id": "loongbella", "name": "Bella", "tags": ["女声", "双语"], "target_model": "cosyvoice-v2"},
]


class BailianProvider(Provider):
    id = "bailian"
    display_name = "阿里云百炼 CosyVoice"
    capabilities = ("enroll", "design", "tts", "query", "delete", "catalog")
    config_schema = (
        {
            "key": "api_key",
            "label": "API Key（sk- 开头）",
            "required": True,
            "secret": True,
            "placeholder": "sk-xxxxxxxx",
            "help": "阿里云百炼控制台 → API-KEY 管理中创建；需开通模型服务",
        },
        {
            "key": "workspace_id",
            "label": "Workspace ID（可选）",
            "required": False,
            "secret": False,
            "placeholder": "",
            "help": "填入后走 MaaS 新接口，可用 cosyvoice-v3/v3.5 模型；留空用经典接口",
        },
        {
            "key": "target_model",
            "label": "默认目标模型",
            "required": False,
            "secret": False,
            "placeholder": "cosyvoice-v2",
            "help": "复刻音色与模型绑定；v2 免 workspace，v3/v3.5 需填 workspace_id",
        },
    )

    # ---- 接口地址 ----

    def _use_maas(self, cfg: dict) -> bool:
        return bool(str(cfg.get("workspace_id", "")).strip())

    def _enroll_url(self, cfg: dict) -> str:
        if self._use_maas(cfg):
            ws = str(cfg["workspace_id"]).strip()
            return (
                f"https://{ws}.cn-beijing.maas.aliyuncs.com"
                "/api/v1/services/audio/tts/customization"
            )
        return f"{CLASSIC}/services/audio/tts/voice-enrollment"

    def _tts_url(self, cfg: dict) -> str:
        if self._use_maas(cfg):
            ws = str(cfg["workspace_id"]).strip()
            return (
                f"https://{ws}.cn-beijing.maas.aliyuncs.com"
                "/api/v1/services/audio/tts/SpeechSynthesizer"
            )
        return f"{CLASSIC}/services/audio/tts/generation"

    def _headers(self, cfg: dict) -> dict:
        return {"Authorization": "Bearer %s" % str(cfg.get("api_key", "")).strip()}

    # ---- 音色注册 ----

    def enroll(self, material: bytes, ext: str, prefix: str, target_model: str,
               cfg: dict, note: str = "") -> dict:
        self.validate_config(cfg)
        target_model = target_model or cfg.get("target_model") or "cosyvoice-v2"
        data_uri = audio_data_uri(material, ext)
        if self._use_maas(cfg):
            payload = {
                "model": "voice-enrollment",
                "input": {
                    "action": "create_voice",
                    "target_model": target_model,
                    "prefix": sanitize_prefix(prefix),
                    "audio": data_uri,
                },
            }
        else:
            payload = {
                "action": "create",
                "target_model": target_model,
                "voice_prefix": sanitize_prefix(prefix),
                "voice_data": {"audio": data_uri, "audio_format": ext.lower()},
            }
        resp = http_json(self._enroll_url(cfg), payload, self._headers(cfg), timeout=120)
        voice_id = (resp.get("output") or {}).get("voice_id")
        if not voice_id:
            raise ProviderError(
                "创建音色未返回 voice_id，响应: %s" % json.dumps(resp, ensure_ascii=False)[:400]
            )
        return {"voice_id": voice_id, "target_model": target_model}

    def voice_status(self, voice_id: str, cfg: dict) -> dict:
        if self._use_maas(cfg):
            payload = {
                "model": "voice-enrollment",
                "input": {"action": "query_voice", "voice_id": voice_id},
            }
        else:
            payload = {"action": "query", "voice_id": voice_id}
        resp = http_json(self._enroll_url(cfg), payload, self._headers(cfg))
        raw = str((resp.get("output") or {}).get("status", ""))
        if raw in _STATUS_READY:
            norm = "ready"
        elif raw in _STATUS_BUSY:
            norm = "processing"
        elif raw in _STATUS_FAILED:
            norm = "failed"
        else:
            norm = raw.lower() or "unknown"
        return {"raw": raw, "status": norm, "output": resp.get("output")}

    def delete(self, voice_id: str, cfg: dict) -> bool:
        if self._use_maas(cfg):
            payload = {
                "model": "voice-enrollment",
                "input": {"action": "delete_voice", "voice_id": voice_id},
            }
        else:
            payload = {"action": "release", "voice_id": voice_id}
        http_json(self._enroll_url(cfg), payload, self._headers(cfg))
        return True

    def catalog(self, cfg: dict) -> list:
        """官方预置音色目录（静态，免克隆免 Key）。"""
        return [dict(v) for v in PRESET_VOICES]

    # ---- 声音设计（文字描述直接生成音色，无需素材） ----

    def design(self, voice_prompt: str, preview_text: str, prefix: str,
               target_model: str, cfg: dict, language: str = "zh") -> dict:
        """AI 生成音色：voice_prompt 描述声音 → voice_id + 试听音频。

        需 MaaS 接口（workspace_id），仅支持 cosyvoice-v3 / v3.5 系列；
        voice_prompt 仅中英文 ≤500 字符，preview_text 15~200 字符。
        """
        self.validate_config(cfg)
        if not self._use_maas(cfg):
            raise ProviderError(
                "声音设计需走 MaaS 接口：请先在面板「设置」页填写百炼 Workspace ID"
                "（声音设计仅支持 cosyvoice-v3 / v3.5 系列模型）"
            )
        target_model = target_model or "cosyvoice-v3.5-plus"
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "voice_prompt": voice_prompt.strip()[:500],
                "preview_text": preview_text.strip()[:200],
                "prefix": sanitize_prefix(prefix),
                "language_hints": [language or "zh"],
            },
        }
        resp = http_json(self._enroll_url(cfg), payload, self._headers(cfg), timeout=180)
        out = resp.get("output") or {}
        voice_id = out.get("voice_id")
        if not voice_id:
            raise ProviderError(
                "声音设计未返回 voice_id，响应: %s" % json.dumps(resp, ensure_ascii=False)[:400]
            )
        preview = b""
        pb64 = (out.get("preview_audio") or {}).get("data")
        if pb64:
            preview = base64.b64decode(pb64)
        return {
            "voice_id": voice_id,
            "target_model": out.get("target_model", target_model),
            "preview": preview,
        }

    # ---- 语音合成 ----

    def tts(self, text: str, voice_id: str, target_model: str, opts: dict,
            cfg: dict, voice_meta: dict | None = None):
        self.validate_config(cfg)
        target_model = target_model or cfg.get("target_model") or "cosyvoice-v2"
        fmt = str(opts.get("format") or "wav").lower()
        if fmt not in ("wav", "mp3", "pcm", "opus"):
            raise ProviderError(f"不支持的输出格式: {fmt}（可选 wav/mp3/pcm/opus）")
        sample_rate = int(opts.get("sample_rate") or 24000)
        rate = float(opts.get("rate") or 1.0)
        pitch = float(opts.get("pitch") or 1.0)
        volume = int(opts.get("volume") or 50)
        if not 0.5 <= rate <= 2.0:
            raise ProviderError("rate 取值范围 0.5~2.0")
        if not 0.5 <= pitch <= 2.0:
            raise ProviderError("pitch 取值范围 0.5~2.0")
        if not 0 <= volume <= 100:
            raise ProviderError("volume 取值范围 0~100")

        if self._use_maas(cfg):
            input_body = {"text": text, "voice": voice_id, "format": fmt,
                          "sample_rate": sample_rate}
            if rate != 1.0:
                input_body["rate"] = rate
            if pitch != 1.0:
                input_body["pitch"] = pitch
            if volume != 50:
                input_body["volume"] = volume
            payload = {"model": target_model, "input": input_body}
        else:
            params = {"voice": voice_id, "format": fmt, "sample_rate": sample_rate}
            if rate != 1.0:
                params["rate"] = rate
            if pitch != 1.0:
                params["pitch"] = pitch
            if volume != 50:
                params["volume"] = volume
            payload = {"model": target_model, "input": {"text": text}, "parameters": params}

        resp = http_json(self._tts_url(cfg), payload, self._headers(cfg), timeout=180)
        audio = (resp.get("output") or {}).get("audio") or {}
        if audio.get("data"):
            return base64.b64decode(audio["data"]), fmt
        if audio.get("url"):
            return http_download(audio["url"]), fmt
        raise ProviderError(
            "合成响应中没有音频数据，响应: %s" % json.dumps(resp, ensure_ascii=False)[:400]
        )
