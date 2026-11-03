"""ElevenLabs 云端适配器（国际标杆，Instant Voice Cloning，有免费额度）。

- 克隆: POST /v1/voices/add (multipart: name, files=样本) → voice_id
- 合成: POST /v1/text-to-speech/{voice_id} (JSON: text, model_id) → mp3 音频
- 目录: GET /v1/voices → voices 列表
认证: Header xi-api-key: <key>
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


class ElevenLabsProvider(Provider):
    id = "elevenlabs"
    display_name = "ElevenLabs"
    tier = "高性能"
    capabilities = ("enroll", "tts", "catalog")
    config_schema = (
        {
            "key": "api_key",
            "label": "API Key",
            "required": True,
            "secret": True,
            "placeholder": "elevenlabs.io → API Keys",
            "help": "有免费额度；克隆与合成按字符计费",
        },
        {
            "key": "api_base",
            "label": "API 地址（可选）",
            "required": False,
            "secret": False,
            "placeholder": "https://api.elevenlabs.io",
        },
        {
            "key": "model_id",
            "label": "TTS 模型",
            "required": False,
            "secret": False,
            "placeholder": "eleven_multilingual_v2",
            "help": "multilingual_v2 质量优先 / flash_v2_5 速度优先 / v3 情感最强",
        },
    )

    def _base(self, cfg: dict) -> str:
        return str(cfg.get("api_base", "")).strip().rstrip("/") or "https://api.elevenlabs.io"

    def _auth(self, cfg: dict) -> dict:
        return {"xi-api-key": str(cfg.get("api_key", "")).strip()}

    def enroll(self, material: bytes, ext: str, prefix: str, target_model: str,
               cfg: dict, note: str = "") -> dict:
        self.validate_config(cfg)
        boundary = uuid.uuid4().hex
        body = multipart_body(
            [("name", (note or prefix).strip()[:40] or "voice")],
            [("files", f"ref.{ext or 'mp3'}", material)],
            boundary,
        )
        headers = dict(self._auth(cfg))
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        raw, _ctype = http_send(
            f"{self._base(cfg)}/v1/voices/add", body, headers, 180, method="POST"
        )
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"ElevenLabs 响应异常: {raw[:300]!r}") from None
        voice_id = data.get("voice_id")
        if not voice_id:
            raise ProviderError(
                f"克隆未返回 voice_id: {json.dumps(data, ensure_ascii=False)[:300]}"
            )
        return {"voice_id": str(voice_id), "target_model": ""}

    def tts(self, text: str, voice_id: str, target_model: str, opts: dict,
            cfg: dict, voice_meta: dict | None = None):
        self.validate_config(cfg)
        model_id = target_model or str(cfg.get("model_id", "")).strip() or "eleven_multilingual_v2"
        payload = {"text": text, "model_id": model_id}
        raw, ctype = http_send(
            f"{self._base(cfg)}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
            payload, self._auth(cfg), 300, method="POST",
        )
        if "json" in ctype or raw[:1] == b"{":
            try:
                err = json.loads(raw.decode("utf-8", "replace"))
                detail = err.get("detail", {}).get("message") if isinstance(err.get("detail"), dict) else err.get("detail")
                raise ProviderError(f"ElevenLabs 返回错误: {detail or json.dumps(err, ensure_ascii=False)[:250]}")
            except json.JSONDecodeError:
                raise ProviderError(f"ElevenLabs 响应异常: {raw[:200]!r}") from None
        return raw, "mp3"

    def catalog(self, cfg: dict) -> list:
        self.validate_config(cfg)
        raw, _ctype = http_send(
            f"{self._base(cfg)}/v1/voices?page_size=30", self._auth(cfg), 30, method="GET"
        )
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"ElevenLabs 目录响应异常: {raw[:200]!r}") from None
        out = []
        for v in (data.get("voices") or [])[:30]:
            vid = v.get("voice_id")
            if vid:
                out.append({"voice_id": str(vid), "name": str(v.get("name") or vid), "tags": ["英文", "官方音色"]})
        return out
