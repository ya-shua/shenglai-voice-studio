"""供应商适配器接口与 HTTP 工具（仅标准库）。

新供应商接入方式：
- OpenAI 风格等"纯 TTS"HTTP 接口：无需写代码，用 GenericTTSProvider（面板「设置」页或
  voice_provider_setup(provider="custom:<id>", custom_config={...}) 即可接入）。
- 含音色注册/换声等复杂流程的供应商：继承 Provider 实现子类，并在
  lib/providers/__init__.py 的 get_provider/list_providers 中登记。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

MIME_BY_EXT = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
}


class ProviderError(RuntimeError):
    """供应商调用失败（带可读信息，会原样呈现给用户）。"""


def audio_data_uri(data: bytes, ext: str) -> str:
    mime = MIME_BY_EXT.get(ext.lower())
    if not mime:
        raise ProviderError(f"不支持的音频扩展名: .{ext}")
    return "data:%s;base64," % mime + base64.b64encode(data).decode("ascii")


def multipart_body(fields, files, boundary: str) -> bytes:
    """构造 multipart/form-data（fields: [(name,value)]; files: [(name,filename,bytes)]）。"""
    out = []
    for name, value in fields:
        out.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
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


def http_send(url, payload=None, headers=None, timeout=60, method=None):
    """发送 HTTP 请求，返回 (原始字节, content_type)。payload 为 dict/list 时按 JSON 编码。"""
    data = None
    hdrs = {}
    if headers:
        hdrs.update(headers)
    if isinstance(payload, (dict, list)):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
    req = urllib.request.Request(
        url, data=data, headers=hdrs, method=method or ("POST" if data is not None else "GET")
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise ProviderError(f"HTTP {e.code} 来自 {url}\n{detail}") from None
    except urllib.error.URLError as e:
        raise ProviderError(f"无法连接 {url}\n{e.reason}") from None


def http_json(url, payload=None, headers=None, timeout=60) -> dict:
    raw, _ = http_send(url, payload, headers, timeout)
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise ProviderError(f"响应不是 JSON: {raw[:300]!r}") from None


def http_download(url, timeout=120) -> bytes:
    raw, _ = http_send(url, timeout=timeout)
    return raw


def poll_until(step, check, timeout_s=120, interval_s=3, description="任务"):
    """轮询直到 check(result) 返回 (True, detail)。超时抛 ProviderError。

    step() 取一次状态；check(result) -> (ready: bool, detail: str)。
    """
    deadline = time.time() + timeout_s
    result = None
    while True:
        result = step()
        ready, detail = check(result)
        if ready:
            return result, detail
        if time.time() >= deadline:
            raise ProviderError(
                f"{description}等待超时（{timeout_s}s），当前状态: {detail}"
            )
        time.sleep(interval_s)


class Provider:
    """供应商适配器基类。capabilities 声明支持的原子能力。"""

    id = ""
    display_name = ""
    tier = ""          # 档位标签：免费 / 性价比 / 高性能 / 翻唱（空 = 未分类）
    capabilities: tuple = ()
    # 配置字段描述: {key,label,required,secret,placeholder,help}
    config_schema: tuple = ()

    def validate_config(self, cfg: dict) -> None:
        for field in self.config_schema:
            if field.get("required") and not str(cfg.get(field["key"], "")).strip():
                raise ProviderError(
                    f"{self.display_name} 缺少配置项「{field['label']}」"
                    f"（{field['key']}），请在面板「设置」页或用 voice_provider_setup 填写"
                )

    def enroll(self, material: bytes, ext: str, prefix: str, target_model: str,
               cfg: dict, note: str = "") -> dict:
        """上传素材注册音色，返回 {voice_id, target_model}。"""
        raise ProviderError(f"{self.display_name} 不支持音色注册")

    def voice_status(self, voice_id: str, cfg: dict) -> dict:
        raise ProviderError(f"{self.display_name} 不支持音色状态查询")

    def catalog(self, cfg: dict) -> list:
        """供应商可用的预置/自有音色目录（供「自由选模型」），返回 [{voice_id,name,target_model?}]。"""
        raise ProviderError(f"{self.display_name} 不提供音色目录")

    def verify_key(self, cfg: dict) -> None:
        """在线校验 Key 是否有效；无效抛 ProviderError（可读中文，引导去模型接入页）。
        实现要求零成本（免费接口或探活技巧），别为校验偷偷花钱。默认不支持。"""
        raise ProviderError(f"{self.display_name} 暂不支持在线校验，请直接试听验证")

    def delete(self, voice_id: str, cfg: dict) -> bool:
        raise ProviderError(f"{self.display_name} 不支持音色删除")

    def tts(self, text: str, voice_id: str, target_model: str, opts: dict,
            cfg: dict, voice_meta: dict | None = None):
        """合成语音，返回 (音频字节, 扩展名)。voice_meta 为音色库中的完整登记项。"""
        raise ProviderError(f"{self.display_name} 不支持语音合成")

    def enroll_and_wait(self, material: bytes, ext: str, prefix: str, target_model: str,
                        cfg: dict, timeout_s: int = 120, note: str = ""):
        """注册并等待就绪，返回 (created, status, detail)。

        status: ready / processing（云端仍在处理，不视为失败）/ unknown。
        审核未通过（failed）时抛 ProviderError。
        """
        created = self.enroll(material, ext, prefix, target_model, cfg, note)
        if "query" not in self.capabilities:
            return created, "unknown", ""
        def step():
            return self.voice_status(created["voice_id"], cfg)
        def check(st):
            if st["status"] == "ready":
                return True, "ready"
            if st["status"] == "failed":
                return True, "failed"
            return False, st["status"]
        try:
            _, status = poll_until(step, check, timeout_s, 3, "音色注册")
        except ProviderError as e:
            return created, "processing", str(e)
        if status == "failed":
            raise ProviderError(
                "音色处理失败或审核未通过（素材可能含伴奏/噪音/多人声）。"
                "请更换更干净的素材后重试，详见素材采集指南。"
            )
        return created, "ready", ""


def _dig(obj, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


class GenericTTSProvider(Provider):
    """配置驱动的通用 TTS 适配器（自由接入 OpenAI 风格等 HTTP 接口）。

    custom 定义（存于 config.json 的 custom.<id>）：
      display_name  显示名
      api_key       API Key（可空）
      url           接口地址
      headers       请求头 dict（模板）
      body          请求体 dict/list（模板）
      audio_from    "binary"（响应体即音频）或 JSON 路径（如 output.audio.data，值为 base64）
      voice_id      固定音色 ID（该供应商不走音色注册时必填）
      ext           输出扩展名，默认 wav
    模板占位符: {{api_key}} {{text}} {{voice_id}}
    """

    def __init__(self, cid: str, definition: dict):
        self.id = f"custom:{cid}"
        self.display_name = definition.get("display_name") or f"自定义TTS {cid}"
        self.definition = dict(definition)
        self.capabilities = ("tts",)
        self.config_schema = (
            {"key": "api_key", "label": "API Key", "required": False, "secret": True},
        )
        self._vars: dict = {}

    def validate_config(self, cfg: dict) -> None:
        cfg = cfg or {}
        has_url = str(cfg.get("url", "")).strip()
        has_base = str(cfg.get("base", "")).strip() and str(cfg.get("protocol", "")).strip()
        if not has_url and not has_base:
            raise ProviderError(f"{self.display_name} 缺少接口地址 url（或 base + protocol）")

    def _endpoint(self, d: dict) -> str:
        """解析请求端点：openai_speech 协议 = base + /audio/speech；否则用完整 url。"""
        if str(d.get("protocol", "")).strip() == "openai_speech":
            base = str(d.get("base", "")).strip().rstrip("/")
            if base:
                return base + "/audio/speech"
        url = str(d.get("url", "")).strip()
        if not url:
            raise ProviderError(f"{self.display_name} 缺少接口地址")
        return url

    def _render(self, value):
        if isinstance(value, str):
            for key in ("api_key", "text", "voice_id"):
                value = value.replace("{{%s}}" % key, str(self._vars.get(key, "")))
            return value
        if isinstance(value, dict):
            return {k: self._render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render(v) for v in value]
        return value

    def tts(self, text, voice_id, target_model, opts, cfg, voice_meta=None):
        d = self.definition
        self._vars = {
            "api_key": str(d.get("api_key", "")),
            "text": text,
            "voice_id": str(voice_id or d.get("voice_id", "")),
        }
        if not self._vars["voice_id"]:
            raise ProviderError(
                f"{self.display_name} 未提供音色：请在自定义供应商配置中填固定 voice_id，"
                "或用手动登记把音色登记到本地库"
            )
        url = self._endpoint(d)
        method = str(d.get("method", "POST")).upper()
        headers = self._render(d.get("headers") or {})
        payload = self._render(d.get("body")) if "body" in d else None
        audio_from = str(d.get("audio_from", "binary"))
        ext = str(d.get("ext", "wav")).lower()
        raw, ctype = http_send(url, payload, headers, timeout=180, method=method)
        if audio_from == "binary":
            if "audio" not in ctype and "octet-stream" not in ctype:
                raise ProviderError(
                    f"{self.display_name} 返回的不是音频（Content-Type: {ctype}）: "
                    f"{raw[:200]!r}。若响应是 JSON，请把 audio_from 设为对应 JSON 路径"
                )
            return raw, ext
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise ProviderError(f"{self.display_name} 响应不是 JSON: {raw[:300]!r}") from None
        b64 = _dig(data, audio_from)
        if not b64:
            raise ProviderError(
                f"{self.display_name} 响应中路径 {audio_from} 无音频数据: {json.dumps(data)[:300]}"
            )
        return base64.b64decode(b64), ext
