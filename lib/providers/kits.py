"""Kits.AI 云端适配器（唱歌换声线）。

分工：自定义唱歌音色在 kits.ai 网页端用多段素材训练（API 不开放训练端点）；
API 侧负责：列出账号下的音色模型 → 人声/伴奏分离 → 干声换声 → 下载结果。

端点（arpeggi.io/api/kits/v1，Authorization: Bearer <key>）：
- GET  /voice-models            账号下的音色模型列表
- POST /vocal-separations       人声分离（inputFile：wav/webm/mp3/flac ≤50MB）
- GET  /vocal-separations/{id}  轮询 → vocalAudioFileUrl / backingAudioFileUrl
- POST /voice-conversions       换声（voiceModelId + soundFile ≤100MB，可选 conversionStrength/pitchShift）
- GET  /voice-conversions/{id}  轮询 → outputFileUrl（签名 URL，4 小时有效）
job 状态：running / success / error / cancelled
"""
from __future__ import annotations

import json
import uuid

from lib.providers.base import (
    Provider,
    ProviderError,
    http_download,
    http_send,
    multipart_body,
    poll_until,
)


class KitsAIProvider(Provider):
    id = "kits"
    display_name = "Kits.AI（唱歌换声）"
    tier = "翻唱"
    capabilities = ("convert", "separate", "catalog")
    config_schema = (
        {
            "key": "api_key",
            "label": "API Key",
            "required": True,
            "secret": True,
            "placeholder": "kits.ai 控制台创建（需付费订阅）",
            "help": "kitsu.ai 网页端用多段唱歌素材训练音色模型后，在此填 API Key",
        },
        {
            "key": "api_base",
            "label": "API 地址（可选）",
            "required": False,
            "secret": False,
            "placeholder": "https://arpeggi.io/api/kits/v1",
        },
    )

    def _base(self, cfg: dict) -> str:
        return str(cfg.get("api_base", "")).strip().rstrip("/") or "https://arpeggi.io/api/kits/v1"

    def _auth(self, cfg: dict) -> dict:
        return {"Authorization": "Bearer %s" % str(cfg.get("api_key", "")).strip()}

    def _post_multipart(self, cfg: dict, path: str, fields, files, timeout: int) -> dict:
        boundary = uuid.uuid4().hex
        body = multipart_body(fields, files, boundary)
        headers = dict(self._auth(cfg))
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        raw, _ctype = http_send(f"{self._base(cfg)}{path}", body, headers, timeout, method="POST")
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"Kits.AI 响应异常: {raw[:300]!r}") from None

    def _poll_job(self, cfg: dict, kind: str, job_id, timeout_s: int) -> dict:
        url = f"{self._base(cfg)}/{kind}/{job_id}"
        def step():
            raw, _ctype = http_send(url, self._auth(cfg), timeout=30, method="GET")
            try:
                return json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                raise ProviderError(f"Kits.AI 任务状态响应异常: {raw[:200]!r}") from None
        def check(job):
            st = str(job.get("status", "")).lower()
            if st == "success":
                return True, "success"
            if st in ("error", "cancelled"):
                raise ProviderError(f"Kits.AI 任务失败（{st}）")
            return False, st or "running"
        job, _ = poll_until(step, check, timeout_s, 5, f"Kits.AI {kind} 任务")
        return job

    # ---- 音色目录（网页端训练好的模型） ----

    def catalog(self, cfg: dict) -> list:
        self.validate_config(cfg)
        raw, _ctype = http_send(
            f"{self._base(cfg)}/voice-models?perPage=30", self._auth(cfg), 30, method="GET"
        )
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"Kits.AI 模型列表响应异常: {raw[:200]!r}") from None
        items = data.get("data") or data.get("items") or (data if isinstance(data, list) else [])
        out = []
        for it in items:
            mid = it.get("id")
            if mid is None:
                continue
            out.append({"voice_id": str(mid), "name": str(it.get("name") or it.get("title") or mid)})
        return out

    # ---- 人声/伴奏分离 ----

    def separate(self, data: bytes, filename: str, cfg: dict) -> dict:
        self.validate_config(cfg)
        job = self._post_multipart(
            cfg, "/vocal-separations", [], [("inputFile", filename, data)], 300
        )
        if not job.get("id"):
            raise ProviderError(f"分离任务创建失败: {json.dumps(job, ensure_ascii=False)[:300]}")
        job = self._poll_job(cfg, "vocal-separations", job["id"], 900)
        vocal = job.get("vocalAudioFileUrl")
        if not vocal:
            vocal = job.get("lossyVocalAudioFileUrl")
        backing = job.get("backingAudioFileUrl")
        if not vocal:
            raise ProviderError("分离完成但未返回人声 URL")
        return {
            "vocal_url": vocal,
            "backing_url": backing,
            "stems": job.get("stemFileUrls") or [],
        }

    # ---- 干声换声 ----

    def convert(self, data: bytes, filename: str, voice_id: str, cfg: dict,
                strength: float = 0.8, pitch_shift: int = 0) -> dict:
        self.validate_config(cfg)
        try:
            model_id = str(int(str(voice_id).strip()))
        except ValueError:
            raise ProviderError(
                f"Kits.AI 音色模型 ID 必须是数字（网页端模型页可见），收到: {voice_id}"
            ) from None
        fields = [
            ("voiceModelId", model_id),
            ("conversionStrength", str(min(max(float(strength), 0.0), 1.0))),
        ]
        if pitch_shift:
            fields.append(("pitchShift", str(int(min(max(pitch_shift, -24), 24)))))
        job = self._post_multipart(
            cfg, "/voice-conversions", fields, [("soundFile", filename, data)], 600
        )
        if not job.get("id"):
            raise ProviderError(f"换声任务创建失败: {json.dumps(job, ensure_ascii=False)[:300]}")
        job = self._poll_job(cfg, "voice-conversions", job["id"], 900)
        out_url = job.get("outputFileUrl") or job.get("lossyOutputFileUrl")
        if not out_url:
            raise ProviderError("换声完成但未返回结果音频 URL")
        return {"audio": http_download(out_url, timeout=300), "url": out_url}
