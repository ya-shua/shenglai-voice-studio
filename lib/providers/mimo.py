"""小米 MiMo TTS 云端适配器（OpenAI 兼容 chat/completions，当前限时免费）。

三个模型（API 文档命名）：
- mimo-v2.5-tts            内置精品音色（支持 (唱歌) 等音频标签）
- mimo-v2.5-tts-voicedesign 文字描述定制音色
- mimo-v2.5-tts-voiceclone  参考音频复刻（数秒样本，无需训练）

请求（POST {base}/chat/completions，Header: api-key: <key>）：
- 合成文本 → assistant 消息 content；风格指令/音色描述 → user 消息 content
- audio: {"format": "wav", "voice": <内置音色名 | data:audio/...;base64,...>}
- 响应：choices[0].message.audio.data（base64 音频）

Base URL：全球 https://api.xiaomimimo.com/v1；中国区 Token Plan
https://token-plan-cn.xiaomimimo.com/v1。模型名若官方更迭，自动在 v2.5/v2.6 候选间回退。
"""
from __future__ import annotations

import base64
import json
import uuid

from lib.providers.base import Provider, ProviderError, http_send

# 文字设计出来的音色没有云端 voice_id，用这个前缀标记，合成时按原描述重新演绎
DESIGN_PREFIX = "mimo-design:"

BUILTIN_VOICES = [
    {"voice_id": "mimo_default", "name": "默认音色", "tags": ["推荐"]},
    {"voice_id": "冰糖", "name": "冰糖（中文女·清亮）", "tags": ["女声", "温柔型"]},
    {"voice_id": "茉莉", "name": "茉莉（中文女·温柔）", "tags": ["女声", "温柔型"]},
    {"voice_id": "苏打", "name": "苏打（中文女·活泼）", "tags": ["女声", "活力型"]},
    {"voice_id": "白桦", "name": "白桦（中文男·沉稳）", "tags": ["男声", "沉稳型"]},
    {"voice_id": "Mia", "name": "Mia（英文女）", "tags": ["女声", "英文"]},
    {"voice_id": "Chloe", "name": "Chloe（英文女）", "tags": ["女声", "英文"]},
    {"voice_id": "Milo", "name": "Milo（英文男）", "tags": ["男声", "英文"]},
    {"voice_id": "Dean", "name": "Dean（英文男）", "tags": ["男声", "英文"]},
]


class MiMoProvider(Provider):
    id = "mimo"
    display_name = "小米 MiMo TTS"
    capabilities = ("tts", "design", "clone", "catalog")
    config_schema = (
        {
            "key": "api_key",
            "label": "API Key",
            "required": True,
            "secret": True,
            "placeholder": "MiMo 开放平台创建",
            "help": "platform.xiaomimimo.com 获取；TTS 当前限时免费",
        },
        {
            "key": "api_base",
            "label": "API 地址（可选）",
            "required": False,
            "secret": False,
            "placeholder": "https://api.xiaomimimo.com/v1",
            "help": "中国区 Token Plan：https://token-plan-cn.xiaomimimo.com/v1",
        },
    )

    MODELS = {
        "builtin": ["mimo-v2.5-tts", "mimo-v2.6-tts"],
        "design": ["mimo-v2.5-tts-voicedesign", "mimo-v2.6-tts-voicedesign"],
        "clone": ["mimo-v2.5-tts-voiceclone", "mimo-v2.6-tts-voiceclone"],
    }

    def _base(self, cfg: dict) -> str:
        base = str(cfg.get("api_base", "")).strip().rstrip("/")
        return base or "https://api.xiaomimimo.com/v1"

    def _headers(self, cfg: dict) -> dict:
        return {"api-key": str(cfg.get("api_key", "")).strip(), "Content-Type": "application/json"}

    def _chat(self, mode: str, messages: list, audio: dict, cfg: dict) -> bytes:
        last: ProviderError | None = None
        for model in self.MODELS[mode]:
            payload = {"model": model, "messages": messages, "audio": audio}
            try:
                raw, _ctype = http_send(
                    f"{self._base(cfg)}/chat/completions", payload, self._headers(cfg),
                    timeout=300, method="POST",
                )
                data = json.loads(raw.decode("utf-8", "replace"))
                choices = data.get("choices") or [{}]
                audio_b64 = ((choices[0].get("message") or {}).get("audio") or {}).get("data")
                if not audio_b64:
                    msg = ((data.get("error") or {}).get("message")) or json.dumps(data, ensure_ascii=False)[:300]
                    raise ProviderError(f"MiMo 未返回音频: {msg}")
                return base64.b64decode(audio_b64)
            except ProviderError as e:
                last = e
                text = str(e).lower()
                if "404" in text or "model" in text or "不存在" in text:
                    continue  # 模型名更迭时自动回退候选
                raise
        raise last or ProviderError("MiMo 合成失败")

    def synthesize_mode(self, mode: str, text: str, style: str = "", voice: str = "",
                        voice_prompt: str = "", ref_data_uri: str = "", cfg: dict | None = None) -> bytes:
        """三种模式统一入口：builtin / design / clone。"""
        cfg = cfg or {}
        self.validate_config(cfg)
        text = (text or "").strip()
        if not text:
            raise ProviderError("合成文本不能为空")
        messages = []
        if mode == "design":
            if not (voice_prompt or "").strip():
                raise ProviderError("声音设计需要音色描述（例：年轻女性，声音清亮干净）")
            messages.append({"role": "user", "content": voice_prompt.strip()})
            messages.append({"role": "assistant", "content": text})
        else:
            if (style or "").strip():
                messages.append({"role": "user", "content": style.strip()})
            messages.append({"role": "assistant", "content": text})
        audio: dict = {"format": "wav"}
        if mode == "builtin":
            audio["voice"] = (voice or "mimo_default").strip() or "mimo_default"
        elif mode == "clone":
            if not ref_data_uri.startswith("data:audio/"):
                raise ProviderError("声音克隆需要参考音频（mp3/wav，10~30 秒，base64 后 ≤10MB）")
            audio["voice"] = ref_data_uri
        return self._chat(mode, messages, audio, cfg)

    def catalog(self, cfg: dict) -> list:
        return [
            {"voice_id": v["voice_id"], "name": v["name"] + "（MiMo 内置）", "tags": v["tags"]}
            for v in BUILTIN_VOICES
        ]

    def design(self, voice_prompt: str, preview_text: str, prefix: str,
               target_model: str, cfg: dict, language: str = "zh") -> dict:
        """文字描述造音色（当前免费）：直接生成试听音频，返回带描述的虚拟音色。"""
        prompt = (voice_prompt or "").strip()
        if not prompt:
            raise ProviderError("声音设计需要音色描述（例：年轻女性，声音清亮干净）")
        data = self.synthesize_mode("design", preview_text, voice_prompt=prompt, cfg=cfg)
        return {
            "voice_id": DESIGN_PREFIX + uuid.uuid4().hex[:8],
            "preview": data,
            "target_model": "mimo-v2.5-tts-voicedesign",
            "status": "ready",
            "design_prompt": prompt,
        }

    def tts(self, text: str, voice_id: str, target_model: str, opts: dict,
            cfg: dict, voice_meta: dict | None = None):
        self.validate_config(cfg)
        vid = str(voice_id or "")
        # 文字设计出来的音色没有云端 ID：每次按存下来的描述重新演绎
        if vid.startswith(DESIGN_PREFIX):
            prompt = str((voice_meta or {}).get("design_prompt") or "").strip()
            if not prompt:
                raise ProviderError("这个 MiMo 设计音色缺少原始描述，无法合成；请重新生成一个")
            data = self.synthesize_mode("design", text, voice_prompt=prompt, cfg=cfg)
            return data, "wav"
        data = self.synthesize_mode(
            "builtin", text, style=str((opts or {}).get("style") or ""),
            voice=vid or "mimo_default", cfg=cfg,
        )
        return data, "wav"
