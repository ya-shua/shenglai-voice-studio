"""阿里云百炼适配器：声音复刻（音色注册）+ CosyVoice 语音合成。

合成接口：cosyvoice-v2/v3 走 WebSocket 流式（dashscope 域名直连，无需业务空间 ID）：
- 经典 DashScope 接口（默认，只需 api_key，模型 cosyvoice-v2）
    enrollment: POST https://dashscope.aliyuncs.com/api/v1/services/audio/tts/voice-enrollment
                action: create / query / release；音色存 voice_data.audio
    synthesis : POST https://dashscope.aliyuncs.com/api/v1/services/audio/tts/generation
                参数放 parameters；音频在 output.audio.data（base64）
- WebSocket：run-task → continue-task → finish-task（duplex），官方唯一现役接口形态
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
import os
import re
import time

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


def key_hint(msg: str) -> str:
    """把 dashscope 的错误翻译成可读指引。鉴权错给一句人话；其他 dashscope 错误加前缀与兜底指引。"""
    if "418" in msg:
        return ("CosyVoice 服务未开通——到百炼控制台「模型广场」搜索 CosyVoice 点开通（免费，需实名账号），"
                "开通后无需任何其他配置即可合成")
    if "401" in msg or "InvalidApiKey" in msg:
        return ("百炼 API Key 无效或已过期——到「模型接入」页重新粘贴保存"
                "（DashScope Key 为 sk- 开头、约 50 字符；阿里云百炼控制台 → API-KEY 管理获取）")
    if "dashscope" in msg:
        return ("百炼合成失败：" + msg + "\n（若详情提示鉴权/Key 问题，到「模型接入」页重新粘贴 Key 后点「测试」验证）")
    return msg



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
    tier = "性价比"
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
            "key": "target_model",
            "label": "默认目标模型",
            "required": False,
            "secret": False,
            "placeholder": "cosyvoice-v2",
            "help": "复刻音色与模型绑定；v2/v3 均走 MaaS 接口（需业务空间 ID）",
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
            # 经典 voice-enrollment 接口同样要求顶层 model 字段（缺了报 BadRequest.EmptyModel）
            payload = {
                "model": "voice-enrollment",
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
        """官方音色目录：内置精选（带标签）+ 官方文档全量（均带试听样音）。"""
        items = [dict(v) for v in PRESET_VOICES]
        seen = {v["voice_id"] for v in items}
        try:
            from lib import preview_audio
            for v in preview_audio.ali_voices_full():
                if v["voice_id"] in seen:
                    continue
                items.append({"voice_id": v["voice_id"], "name": v["name"],
                              "tags": ["百炼官方", "免费试听"], "target_model": "cosyvoice-v2"})
                seen.add(v["voice_id"])
        except Exception:
            pass
        return items

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
        # cosyvoice-v2/v3 只提供 WebSocket 流式接口：HTTP 端点会报 "url error"（端点不匹配）。
        # 实测 dashscope 域名 + Bearer 头 + run-task/continue-task/finish-task(duplex) 可直达引擎。
        if target_model.startswith("cosyvoice-v"):
            return self._ws_tts(text, voice_id, target_model, opts, cfg)
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

        try:
            resp = http_json(self._tts_url(cfg), payload, self._headers(cfg), timeout=180)
        except ProviderError as e:
            # 401/InvalidApiKey → 一句人话 + 去哪修；其余错误原样
            raise ProviderError(key_hint(str(e)))
        audio = (resp.get("output") or {}).get("audio") or {}
        if audio.get("data"):
            return base64.b64decode(audio["data"]), fmt
        if audio.get("url"):
            return http_download(audio["url"]), fmt
        raise ProviderError(
            "合成响应中没有音频数据，响应: %s" % json.dumps(resp, ensure_ascii=False)[:400]
        )

    def _ws_tts(self, text: str, voice_id: str, model: str, opts: dict, cfg: dict):
        """CosyVoice v2/v3 WebSocket 流式合成（官方唯一接口形态）。

        链路：dashscope 域名 + Bearer 头握手 → run-task → task-started
             → continue-task(文本) → finish-task → 收集二进制音频帧 → task-finished。
        需要：控制台开通 CosyVoice 服务（未开通引擎报 418）。
        """
        import base64 as _b64
        import socket as _socket
        import ssl as _ssl
        import struct as _struct
        import uuid as _uuid

        key = str(cfg.get("api_key", "")).strip()
        fmt = str((opts or {}).get("format") or "wav").lower()
        if fmt not in ("wav", "mp3", "pcm", "opus"):
            fmt = "wav"
        sample_rate = int((opts or {}).get("sample_rate") or 24000)
        rate = float((opts or {}).get("rate") or 1.0)
        pitch = float((opts or {}).get("pitch") or 1.0)
        volume = int((opts or {}).get("volume") or 50)
        text = str(text or "").strip()
        if not text:
            raise ProviderError("合成文本不能为空")

        host = "dashscope.aliyuncs.com"
        sock = _socket.create_connection((host, 443), timeout=30)
        ss = _ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        wskey = _b64.b64encode(_uuid.uuid4().bytes).decode()
        req_head = (
            'GET /api-ws/v1/inference HTTP/1.1\r\n'
            'Host: {host}\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            'Sec-WebSocket-Key: {wskey}\r\n'
            'Sec-WebSocket-Version: 13\r\n'
            'Authorization: Bearer {key}\r\n'
            '\r\n'
        ).format(host=host, wskey=wskey, key=key)
        ss.sendall(req_head.encode("utf-8"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += ss.recv(4096)
        hs_status = buf.split(b"\r\n\r\n")[0].split(b"\r\n")[0].decode("utf-8", "replace")
        leftover = buf.split(b"\r\n\r\n", 1)[1]
        if "101" not in hs_status:
            ss.close()
            raise ProviderError(key_hint(f"WebSocket 握手失败: {hs_status}（Key 无效或网络问题）"))

        def send(obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            h = bytearray([0x81])
            n = len(data)
            if n < 126:
                h.append(0x80 | n)
            elif n < 65536:
                h.append(0x80 | 126)
                h += _struct.pack(">H", n)
            else:
                h.append(0x80 | 127)
                h += _struct.pack(">Q", n)
            mask = os.urandom(4)
            h += mask
            ss.sendall(bytes(h) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

        def recv_frame(buffer):
            while True:
                if len(buffer) >= 2:
                    op = buffer[0] & 0x0F
                    n = buffer[1] & 0x7F
                    off = 2
                    if n == 126:
                        if len(buffer) < 4:
                            buffer += ss.recv(65536)
                            continue
                        n = _struct.unpack(">H", buffer[2:4])[0]
                        off = 4
                    elif n == 127:
                        if len(buffer) < 10:
                            buffer += ss.recv(65536)
                            continue
                        n = _struct.unpack(">Q", buffer[2:10])[0]
                        off = 10
                    if len(buffer) < off + n:
                        buffer += ss.recv(65536)
                        continue
                    return buffer[off:off + n], buffer[off + n:], op
                buffer += ss.recv(65536)

        task_id = _uuid.uuid4().hex
        send({"header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
              "payload": {"task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
                          "model": model, "input": {},
                          "parameters": {"text_type": "PlainText", "voice": voice_id,
                                         "format": fmt, "sample_rate": sample_rate,
                                         "volume": volume, "rate": rate, "pitch": pitch}}})
        started = False
        audio = bytearray()
        deadline = time.time() + 180
        ss.settimeout(60)
        failure = ""
        try:
            while time.time() < deadline:
                try:
                    payload, leftover, op = recv_frame(leftover)
                except _socket.timeout:
                    raise ProviderError("CosyVoice 合成超时（60 秒无响应）——请稍后重试")
                if op == 8:
                    break
                try:
                    ev = json.loads(payload.decode("utf-8", "replace"))
                except Exception:
                    audio += payload
                    continue
                h = ev.get("header") or {}
                event = h.get("event") or ""
                if event == "task-started" and not started:
                    started = True
                    send({"header": {"action": "continue-task", "task_id": task_id, "streaming": "duplex"},
                          "payload": {"input": {"text": text}}})
                    send({"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
                          "payload": {"input": {}}})
                elif event == "task-failed":
                    failure = f"{h.get('error_code', '')}: {h.get('error_message', '')}"
                    break
                elif event == "task-finished":
                    break
        finally:
            try:
                ss.close()
            except Exception:
                pass
        if failure:
            raise ProviderError(key_hint(f"CosyVoice 合成失败: {failure}"))
        if len(audio) < 1000:
            raise ProviderError("CosyVoice 合成未返回音频数据（引擎无输出）")
        return bytes(audio), fmt

    def verify_key(self, cfg: dict) -> None:
        """在线校验：真实走一次 WebSocket 最小合成（1 个字，费用可忽略）。
        Key 无效 → 401 指引；CosyVoice 未开通 → 418 指引；成功 → Key 全链路可用。"""
        self.validate_config(cfg)
        self._ws_tts("你", "longwan", "cosyvoice-v2", {}, cfg)

