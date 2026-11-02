"""Fish Audio 云端适配器（有免费层）。

- 合成: POST {base}/v1/tts  JSON {text, reference_id, format, normalize, latency} → 音频二进制
- 克隆: POST {base}/v1/model  multipart (titles, voices=音频文件, visibility) → 返回模型 _id
- 目录: GET  {base}/v1/models?self=true → 自己账号下的音色模型列表
认证: Authorization: Bearer <api_key>（fish.audio 控制台创建）
网页端克隆的音色同样拿 model ID 登记即可使用。
"""
from __future__ import annotations

import json
import uuid

from lib.providers.base import Provider, ProviderError, http_send

_READY = {"finished", "trained", "success", "ready", "ok", "completed"}
_BUSY = {"training", "processing", "pending", "queued", "deploying"}


def _multipart(fields, files, boundary: str) -> bytes:
    """极简 multipart/form-data 构造（fields: [(name,value)]; files: [(name,filename,bytes)]）。"""
    out = []
    for name, value in fields:
        out.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            ).encode("utf-8")
        )
    for name, filename, data in files:
        out.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            ).encode("utf-8")
        )
        out.append(data)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(out)


class FishAudioProvider(Provider):
    id = "fish"
    display_name = "Fish Audio"
    capabilities = ("enroll", "tts", "query", "catalog")
    config_schema = (
        {
            "key": "api_key",
            "label": "API Key",
            "required": True,
            "secret": True,
            "placeholder": "fish.audio 控制台创建",
            "help": "https://fish.audio → 控制台 → API Keys；TTS 有免费额度",
        },
        {
            "key": "api_base",
            "label": "API 地址（可选）",
            "required": False,
            "secret": False,
            "placeholder": "https://api.fish.audio",
        },
        {
            "key": "format",
            "label": "输出格式",
            "required": False,
            "secret": False,
            "placeholder": "wav",
            "help": "wav / mp3 / opus",
        },
        {
            "key": "latency",
            "label": "延迟模式",
            "required": False,
            "secret": False,
            "placeholder": "normal",
            "help": "normal（质量优先）/ balanced",
        },
    )

    def _base(self, cfg: dict) -> str:
        base = str(cfg.get("api_base", "")).strip().rstrip("/")
        return base or "https://api.fish.audio"

    def _auth(self, cfg: dict) -> dict:
        return {"Authorization": "Bearer %s" % str(cfg.get("api_key", "")).strip()}

    # ---- 音色克隆（API 侧上传素材训练） ----

    def enroll(self, material: bytes, ext: str, prefix: str, target_model: str,
               cfg: dict, note: str = "") -> dict:
        self.validate_config(cfg)
        base = self._base(cfg)
        boundary = uuid.uuid4().hex
        fields = [
            ("titles", (note or f"voice-{prefix}").strip()[:60] or "voice"),
            ("visibility", "private"),
        ]
        files = [("voices", f"ref.{ext or 'wav'}", material)]
        body = _multipart(fields, files, boundary)
        headers = dict(self._auth(cfg))
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        last_err: ProviderError | None = None
        raw = b""
        for path in ("/v1/model", "/model"):  # 兼容新旧 API 前缀
            try:
                raw, _ctype = http_send(base + path, body, headers, timeout=180, method="POST")
                break
            except ProviderError as e:
                last_err = e
                if "HTTP 404" in str(e):
                    continue
                raise
        else:
            raise last_err or ProviderError("创建音色模型失败")
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"创建音色模型响应异常: {raw[:300]!r}") from None
        model_id = data.get("_id") or (data.get("model") or {}).get("_id")
        if not model_id:
            raise ProviderError(
                f"创建音色模型未返回 _id: {json.dumps(data, ensure_ascii=False)[:300]}"
            )
        return {"voice_id": str(model_id), "target_model": target_model or "fish-speech"}

    def voice_status(self, voice_id: str, cfg: dict) -> dict:
        try:
            raw, _ctype = http_send(
                f"{self._base(cfg)}/v1/model/{voice_id}", self._auth(cfg), timeout=30,
                method="GET",
            )
            data = json.loads(raw.decode("utf-8", "replace"))
        except (ProviderError, json.JSONDecodeError):
            # 查询不到状态时按就绪处理，真正的问题会在合成时暴露
            return {"raw": "", "status": "ready", "output": {}}
        state = str(data.get("state") or data.get("status") or "").lower()
        if not state or state in _READY:
            norm = "ready"
        elif state in _BUSY:
            norm = "processing"
        else:
            norm = "failed"
        return {"raw": state, "status": norm, "output": {}}

    # ---- 语音合成 ----

    def tts(self, text: str, voice_id: str, target_model: str, opts: dict,
            cfg: dict, voice_meta: dict | None = None):
        self.validate_config(cfg)
        fmt = str(opts.get("format") or cfg.get("format") or "wav").lower()
        if fmt not in ("wav", "mp3", "opus"):
            fmt = "wav"
        payload = {
            "text": text,
            "reference_id": voice_id,
            "format": fmt,
            "normalize": True,
            "latency": str(cfg.get("latency") or "normal"),
        }
        raw, ctype = http_send(
            f"{self._base(cfg)}/v1/tts", payload, self._auth(cfg), timeout=300, method="POST"
        )
        if "json" in ctype or raw[:1] == b"{":
            try:
                err = json.loads(raw.decode("utf-8", "replace"))
                raise ProviderError(
                    f"Fish Audio 返回错误: {err.get('message') or err.get('detail') or raw[:200]!r}"
                )
            except json.JSONDecodeError:
                raise ProviderError(f"Fish Audio 响应异常: {raw[:200]!r}") from None
        return raw, fmt

    # ---- 音色目录（自由选模型） ----

    def catalog(self, cfg: dict) -> list:
        self.validate_config(cfg)
        raw, _ctype = http_send(
            f"{self._base(cfg)}/v1/models?page_size=30&self=true",
            self._auth(cfg), timeout=30, method="GET",
        )
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"音色目录响应异常: {raw[:200]!r}") from None
        items = data.get("items") or data.get("models") or []
        out = []
        for it in items:
            mid = it.get("_id")
            if mid:
                out.append({"voice_id": str(mid), "name": str(it.get("title") or mid)})
        return out
