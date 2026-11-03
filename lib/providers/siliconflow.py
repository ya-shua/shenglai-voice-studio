"""硅基流动 SiliconFlow 云端适配器（国内直连，注册送额度）。

一个 Key 用多个底模：CosyVoice2-0.5B / fish-speech 等。
- 克隆: POST /v1/uploads/audio/voice_clone (multipart: model, customName, sample_audio 3~10s)
        → {"uri": "speech:名称:xx"} 作为 voice 使用
- 合成: POST /v1/audio/speech (JSON: model, input, voice, response_format) → 二进制音频
- 预置音色: voice = "{model}:{preset}"（alex/anna/bella/benjamin/charles/claire/david/diana 等）
认证: Authorization: Bearer <key>
"""
from __future__ import annotations

import json
import uuid

from lib.providers.base import (
    Provider,
    ProviderError,
    http_send,
    multipart_body,
)

DEFAULT_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
PRESETS = ["alex", "anna", "bella", "benjamin", "charles", "claire", "david", "diana"]


class SiliconFlowProvider(Provider):
    id = "siliconflow"
    display_name = "硅基流动 SiliconFlow"
    tier = "性价比"
    capabilities = ("enroll", "tts", "catalog")
    config_schema = (
        {
            "key": "api_key",
            "label": "API Key",
            "required": True,
            "secret": True,
            "placeholder": "cloud.siliconflow.cn 创建",
            "help": "一个 Key 多个底模，注册送额度",
        },
        {
            "key": "api_base",
            "label": "API 地址（可选）",
            "required": False,
            "secret": False,
            "placeholder": "https://api.siliconflow.cn",
        },
        {
            "key": "model",
            "label": "TTS 模型",
            "required": False,
            "secret": False,
            "placeholder": DEFAULT_MODEL,
        },
    )

    def _base(self, cfg: dict) -> str:
        return str(cfg.get("api_base", "")).strip().rstrip("/") or "https://api.siliconflow.cn"

    def _model(self, cfg: dict, target_model: str = "") -> str:
        return target_model or str(cfg.get("model", "")).strip() or DEFAULT_MODEL

    def _auth(self, cfg: dict) -> dict:
        return {"Authorization": "Bearer %s" % str(cfg.get("api_key", "")).strip()}

    def enroll(self, material: bytes, ext: str, prefix: str, target_model: str,
               cfg: dict, note: str = "") -> dict:
        self.validate_config(cfg)
        model = self._model(cfg, target_model)
        boundary = uuid.uuid4().hex
        body = multipart_body(
            [("model", model), ("customName", (note or prefix).strip()[:30] or "voice")],
            [("sample_audio", f"ref.{ext or 'wav'}", material)],
            boundary,
        )
        headers = dict(self._auth(cfg))
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        raw, _ctype = http_send(
            f"{self._base(cfg)}/v1/uploads/audio/voice_clone", body, headers, 180, method="POST"
        )
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"硅基流动响应异常: {raw[:300]!r}") from None
        uri = data.get("uri") or (data.get("data") or {}).get("uri")
        if not uri:
            raise ProviderError(
                f"音色克隆未返回 uri: {json.dumps(data, ensure_ascii=False)[:300]}"
            )
        return {"voice_id": str(uri), "target_model": model}

    def tts(self, text: str, voice_id: str, target_model: str, opts: dict,
            cfg: dict, voice_meta: dict | None = None):
        self.validate_config(cfg)
        model = self._model(cfg, target_model)
        payload = {
            "model": model,
            "input": text,
            "voice": voice_id,
            "response_format": str((opts or {}).get("format") or "wav").lower(),
        }
        rate = float((opts or {}).get("rate") or 1.0)
        if rate != 1.0:
            payload["speed"] = max(0.25, min(4.0, rate))
        raw, ctype = http_send(
            f"{self._base(cfg)}/v1/audio/speech", payload, self._auth(cfg), 300, method="POST"
        )
        if "json" in ctype or raw[:1] == b"{":
            try:
                err = json.loads(raw.decode("utf-8", "replace"))
                raise ProviderError(
                    f"硅基流动返回错误: {err.get('message') or json.dumps(err, ensure_ascii=False)[:250]}"
                )
            except json.JSONDecodeError:
                raise ProviderError(f"硅基流动响应异常: {raw[:200]!r}") from None
        return raw, payload["response_format"]

    def catalog(self, cfg: dict) -> list:
        model = self._model(cfg)
        meta = {
            "alex": ("Alex", ["男声", "英文"]), "anna": ("Anna", ["女声", "英文"]),
            "bella": ("Bella", ["女声", "英文"]), "benjamin": ("Benjamin", ["男声", "英文"]),
            "charles": ("Charles", ["男声", "英文"]), "claire": ("Claire", ["女声", "英文"]),
            "david": ("David", ["男声", "英文"]), "diana": ("Diana", ["女声", "英文"]),
        }
        return [
            {
                "voice_id": f"{model}:{p}",
                "name": meta.get(p, (p, []))[0] + "（硅基预置）",
                "tags": meta.get(p, (p, []))[1],
                "target_model": model,
            }
            for p in PRESETS
        ]
