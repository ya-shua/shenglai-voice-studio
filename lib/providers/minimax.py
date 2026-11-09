"""MiniMax 云端适配器——中文高性能档（Speech-02/HD 系列，情感表现力强）。

- 合成: POST https://api.minimaxi.com/v1/t2a_v2
  body: {model, text, voice_setting:{voice_id,...}, audio_setting:{format...}}
  响应: data.audio（HEX 编码音频，需 bytes.fromhex）
- 克隆: POST /v1/voice_clone (multipart: file, voice_id 自定义名)
  注意：克隆免费，但首次用该音色合成会收 50 元音色解锁费
- 认证: Authorization: Bearer <API Key>（platform.minimaxi.com 创建）
"""
from __future__ import annotations

import json
import uuid

from lib.providers.base import Provider, ProviderError, http_send, multipart_body

# 预置音色（MiniMax 官方 voice_id）
PRESET_VOICES = [
    ("female-shaonv", "少女（女·清亮）", ["女声", "活力型"]),
    ("female-yujie", "御姐（女·成熟）", ["女声", "沉稳型"]),
    ("female-perfect", "完美女声", ["女声", "温柔型"]),
    ("male-qn-qingse", "青涩青年（男）", ["男声", "活力型"]),
    ("male-qn-jingying", "精英青年（男）", ["男声", "沉稳型"]),
    ("presenter_male", "男主持人", ["男声", "播报"]),
    ("presenter_female", "女主持人", ["女声", "播报"]),
    ("audiobook_female_1", "有声书女声", ["女声", "小说"]),
    ("audiobook_male_1", "有声书男声", ["男声", "小说"]),
]


class MiniMaxProvider(Provider):
    id = "minimax"
    display_name = "MiniMax（高性能·中文）"
    capabilities = ("tts", "enroll", "catalog")
    tier = "高性能"

    config_schema = (
        {
            "key": "api_key",
            "label": "API Key",
            "required": True,
            "secret": True,
            "placeholder": "platform.minimaxi.com 创建",
            "help": "中文情感表现力天花板；克隆音色首次使用收 50 元解锁费",
        },
        {
            "key": "model",
            "label": "合成模型",
            "required": False,
            "secret": False,
            "placeholder": "speech-02-hd",
            "help": "speech-02-hd 高保真 / speech-02-turbo 快速便宜",
        },
        {
            "key": "group_id",
            "label": "GroupId（可选）",
            "required": False,
            "secret": False,
            "placeholder": "",
            "help": "旧版账号才需要；新版 API Key 留空",
        },
    )

    def _base(self, cfg: dict) -> str:
        return "https://api.minimaxi.com"

    def _headers(self, cfg: dict) -> dict:
        return {"Authorization": "Bearer %s" % str(cfg.get("api_key", "")).strip(),
                "Content-Type": "application/json"}

    def _url(self, path: str, cfg: dict) -> str:
        url = self._base(cfg) + path
        gid = str(cfg.get("group_id", "")).strip()
        if gid:
            url += ("&" if "?" in url else "?") + "GroupId=" + gid
        return url

    # ---- 合成（t2a_v2，HEX 音频） ----

    def tts(self, text: str, voice_id: str, target_model: str, opts: dict,
            cfg: dict, voice_meta: dict | None = None):
        self.validate_config(cfg)
        model = target_model or str(cfg.get("model", "")).strip() or "speech-02-hd"
        rate = float((opts or {}).get("rate") or 1.0)
        pitch = float((opts or {}).get("pitch") or 1.0)
        vol = float((opts or {}).get("volume") or 50)
        voice_setting = {
            "voice_id": voice_id,
            "speed": max(0.5, min(2.0, rate)),
            "vol": max(0.2, min(2.0, vol / 50.0)),
            "pitch": int(max(-12, min(12, round((pitch - 1.0) * 12)))),
        }
        # 原生情绪：t2a_v2 的 voice_setting.emotion（中文标签 → MiniMax 枚举）
        mm_emotion = {"开心": "happy", "兴奋": "happy", "生气": "angry", "难过": "sad", "委屈": "sad"}
        tag = str((opts or {}).get("emotion") or "")
        if tag in mm_emotion:
            voice_setting["emotion"] = mm_emotion[tag]
            voice_setting["emotion_scale"] = 1.3
        payload = {
            "model": model,
            "text": text,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": 32000,
                "format": "mp3",
                "channel": 1,
            },
        }
        raw, _ctype = http_send(self._url("/v1/t2a_v2", cfg), payload,
                                self._headers(cfg), 180, method="POST")
        data = json.loads(raw.decode("utf-8", "replace"))
        audio_hex = ((data.get("data") or {}).get("audio")) or ""
        if not audio_hex:
            msg = (data.get("base_resp") or {}).get("status_msg") or json.dumps(data, ensure_ascii=False)[:250]
            raise ProviderError(f"MiniMax 合成失败: {msg}")
        return bytes.fromhex(audio_hex), "mp3"

    def verify_key(self, cfg: dict) -> None:
        """零成本探活：故意用不存在的模型名打一次鉴权。
        MiniMax 返回 HTTP 200 + base_resp.status：1004 = 鉴权失败；其他任何错误 = 已通过鉴权。"""
        self.validate_config(cfg)
        raw, _ct = http_send(self._url("/v1/t2a_v2", cfg),
                             {"model": "key-check-probe", "text": ""},
                             self._headers(cfg), 30, method="POST")
        data = json.loads(raw.decode("utf-8", "replace"))
        br = data.get("base_resp") or {}
        status = str(br.get("status_code") or br.get("status") or "")
        if status == "1004" or "login fail" in str(br.get("status_msg") or ""):
            raise ProviderError("MiniMax API Key 无效——到「模型接入」页重新粘贴保存"
                                "（platform.minimaxi.com → 账户管理 → 接口密钥）")
        # 其他任何状态（模型不存在/参数错误等）= 已通过鉴权，Key 有效

    # ---- 音色克隆（voice_clone，50 元/音色首用解锁） ----

    def enroll(self, material: bytes, ext: str, prefix: str, target_model: str,
               cfg: dict, note: str = "") -> dict:
        self.validate_config(cfg)
        voice_name = "mimic_" + uuid.uuid4().hex[:8]
        boundary = uuid.uuid4().hex
        body = multipart_body(
            [("voice_id", voice_name)],
            [("file", f"ref.{ext or 'mp3'}", material)],
            boundary,
        )
        headers = {"Authorization": "Bearer %s" % str(cfg.get("api_key", "")).strip(),
                   "Content-Type": f"multipart/form-data; boundary={boundary}"}
        raw, _ctype = http_send(self._url("/v1/voice_clone", cfg), body, headers, 180, method="POST")
        data = json.loads(raw.decode("utf-8", "replace"))
        if str((data.get("base_resp") or {}).get("status")) not in ("0", "None", "0.0"):
            msg = (data.get("base_resp") or {}).get("status_msg") or json.dumps(data, ensure_ascii=False)[:250]
            raise ProviderError(f"MiniMax 克隆失败: {msg}")
        returned = data.get("voice_id") or voice_name
        return {"voice_id": str(returned), "target_model": model_name(cfg)}

    # ---- 音色目录 ----

    def catalog(self, cfg: dict) -> list:
        return [
            {"voice_id": vid, "name": f"{name}（MiniMax 预置）", "tags": tags}
            for vid, name, tags in PRESET_VOICES
        ]


def model_name(cfg: dict) -> str:
    return str(cfg.get("model", "")).strip() or "speech-02-hd"
