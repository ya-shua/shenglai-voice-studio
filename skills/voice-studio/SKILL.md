---
name: voice-studio
description: 声来——AI 角色的声音引擎。对外只提供两个能力：说话（文本转语音）与唱歌（歌曲翻唱），音色注册、Key 配置、素材管理等均在 Web 面板完成。用户要让角色开口说话、朗读、配音、翻唱歌曲，或提到"音色/说话/唱歌/试听/TTS"时使用。
---

# 声来（voice-studio）

AI 角色的声音引擎。**对外只有两个 MCP 工具**；其余能力（配 Key、注册/克隆音色、素材、换声、声音大厅、供应商路由等）全部内部实现，管理操作在 Web 面板完成。

## 对外工具（仅这两个）

### 1. voice_speak —— 说话
把文本合成为语音，返回 wav/mp3 文件路径。
- `voice_speak(text=...)`：用**当前音色**
- `voice_speak(text=..., voice_name=音色名)`：指定音色
- 可选：emotion、rate、pitch、volume、format、sample_rate

### 2. voice_sing —— 唱歌
稳定翻唱流水线（人声/伴奏分离 → 人声换声 → 混回伴奏），返回成品路径，伴奏全程不动只换人声。
- `voice_sing(song_path=...)`：用当前音色
- `voice_sing(song_path=..., voice_name=音色名)`：指定音色
- 可选：engine（kits 云端 / local-svc 本机免费）、strength、pitch_shift

## 参数速查

| 参数 | 含义 | 范围/取值 | 默认 |
|---|---|---|---|
| emotion | 情绪 | 默认/开心/兴奋/温柔/生气/委屈/难过/撒娇/困倦/得意 | 默认 |
| rate | 语速倍数 | 0.5~2.0 | 1.0 |
| pitch | 音调倍数 | 0.5~2.0 | 1.0 |
| volume | 音量 | 0~100 | 50 |
| format | 格式 | wav/mp3 | wav |
| engine | 翻唱引擎 | kits/local-svc | kits |
| strength | 换声强度 | 0~1 | 0.8 |
| pitch_shift | 半音偏移 | -24~24 | 0 |

## 管理操作走 Web 面板

配 Key、注册/克隆音色、上传素材、改名/删除、设当前音色、试听记录等都在面板：
- 地址 http://127.0.0.1:17878（端口以数据目录 `.panel.json` 为准），或用 /voice:panel
- 没有可用音色时，先引导用户在面板注册并设为当前音色，再调 voice_speak / voice_sing
- 素材要求：≥10 秒清晰人声、无伴奏/混响/噪音，wav/mp3/m4a，详见 docs/素材采集指南.md

## 原则

- 对外极简：一个目标一个入口，说话、唱歌各只有一个工具，不让用户接触内部供应商细节
- 密钥只存本机、不进对话；供应商路由、音色克隆等由内部自动处理
