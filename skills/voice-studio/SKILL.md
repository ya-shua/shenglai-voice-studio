---
name: voice-studio
description: 声来——纯云端 Key 驱动的音色克隆与语音合成工具集，多供应商自由选模型，支持 AI 生成音色（声音设计）与模型生成素材。当用户想要克隆音色说话、一句话克隆、用文字描述生成音色、模型生成素材、文字转语音（TTS/配音/朗读）、登记或管理音色、查看可用音色目录、浏览声音大厅挑选免费音色、打开声音控制面板，或提到"音色/克隆声音/配音/换声/唱歌/试听"等需求时使用。
---

# 声来（voice-studio）

纯云端 Key 驱动的声音工作台（**不做本地模型部署**）。内置 6 家云端模型 + 万能自定义接入；说话、克隆、翻唱全流程已实现。

## 供应商与音色来源（自由选模型，内置 5 家 + 任意自定义）

- **mimo**（小米 MiMo TTS，**当前限时免费**，推荐首选）：三模式直接合成**无需注册音色**——
  `voice_mimo_tts(mode="builtin", text, style?, voice?)` 内置音色（冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean，支持风格指令与 (唱歌) 标签）；
  `voice_mimo_tts(mode="design", text, voice_prompt)` 文字描述直接生成；
  `voice_mimo_tts(mode="clone", text, reference_audio_path)` 一句话复刻（mp3/wav，10~30 秒）
- **bailian**（阿里百炼 CosyVoice）：官方预置音色免克隆直接用（`voice_catalog`）；声音复刻（≥10 秒素材，免费）；声音设计（voice_design，需 Workspace ID）
- **siliconflow**（硅基流动，一个 Key 多个底模，送额度）：`voice_enroll(provider="siliconflow")` 3~10 秒素材克隆拿 URI；预置音色走 `voice_catalog(provider="siliconflow")`；CosyVoice2 语境/方言表现好
- **elevenlabs**（ElevenLabs，国际标杆，有免费额度）：Instant Voice Cloning（`voice_enroll(provider="elevenlabs")`）+ 多语言合成；目录含账号全部音色
- **fish**（Fish Audio，有免费层）：网页端克隆 → Model ID 登记，或 `voice_enroll(provider="fish")`
- **kits**（Kits.AI，订阅制）：唱歌换声线（见翻唱节）
- **custom:<id>**：通用 HTTP 模板适配器，接入任意 OpenAI 风格 TTS（MiniMax/火山引擎/讯飞/PlayHT/Cartesia 等未内置的供应商都可走这条路上，或按 base.py 接口写适配器）

「模型接入」面板（DS 式）：已接入模型为状态行列表（编辑/断开），「＋添加模型」双页签（常规模型下拉 / 自定义模型 API：填 base 地址+协议自动拼端点）。未接入的模型在合成/登记时触发**按需引导弹窗**（只含该模型字段，保存后继续原操作）；也可 `voice_provider_setup` 直接写入。新增供应商适配器后界面零改动自动出现。

## 标准工作流程

1. **先体检**：`voice_status` 确认数据目录与供应商配置。
2. **配置供应商**：引导用户在面板「设置」页填百炼 API Key（sk- 开头）或 Fish Audio Key；用户明确提供时才用 `voice_provider_setup` 写入。不要把密钥抄进对话。
3. **开口说话（推荐从 MiMo 开始，免费且零注册）**：
   - 用户想挑现成声音 → 面板「🎧 声音大厅」或 `voice_catalog`：25+ 官方免费音色按分类筛选（温柔型/活力型/沉稳型等），试听后 `voice_register_manual` 登记
   - 有一句话参考音频 → `voice_mimo_tts(mode="clone", text, reference_audio_path)` 直接复刻
   - 参考音频 + 指定任意已接入模型 → `voice_clone_universal(provider, text, reference_audio_path)`（mimo 内联直传；bailian/fish/siliconflow/elevenlabs 自动临时注册→合成→清理，keep=true 保留）
   - 想凭空造声音 → `voice_mimo_tts(mode="design", text, voice_prompt)` 或 `voice_design`（百炼，需 Workspace ID）
   - 用内置音色 → `voice_mimo_tts(mode="builtin", text, voice="冰糖", style="用开心的语气")`
   - 要可长期管理的音色库 → 向导三意图（voice_design / voice_quick_clone / voice_catalog+voice_register_manual）+ 素材页补全后 `voice_enroll`
4. **合成说话**：`voice_tts(text, voice_name, rate?, pitch?, volume?, format?)`，产出文件路径以 Markdown 链接发给用户。

## 一句话快速克隆（GPT-SoVITS 式体验的云端版）

`voice_quick_clone(audio_path, text, voice_name?, keep_voice?)`：一段 ≥10 秒音频 + 文本 → 临时注册 → 立刻合成 → 默认用后即弃（自动清理临时音色）。用户说"就用这句试试 / 临时用一下这个声音"时优先用；要长期保留时 `keep_voice=true` + `voice_name`。

## 音色调试（对应"调试自己喜欢的音色"）

- 参数：语速 `rate` 0.5~2.0、音调 `pitch` 0.5~2.0、音量 `volume` 0~100（gptsovits 类本地参数已移除；fish 仅 rate 有效，pitch/volume 会被忽略）
- 效果不满意：①换更干净的素材重新 enroll ②调 rate/pitch ③面板「试听台」A/B 对比定稿
- `voice_library(section="voices"|"materials"|"outputs")` 随时盘点

## 素材硬性要求（复刻/克隆用）

≥10 秒（10~20 秒最佳）、清晰人声、无伴奏/混响/噪音/他人声、WAV(16bit)/MP3/M4A、≤10MB、≥16kHz（Fish 支持 15 秒起，网页端克隆更灵活）。完整指南在插件 `docs/素材采集指南.md` 与面板「采集指南」页签。

## 面板（任务流工作台）

`voice_panel`（或 `/voice:panel`）启动本地 Web 面板并返回 URL。结构：顶栏**当前音色**选择器（空态隐藏，按钮「开始创建 ↔ ＋新建音色」）+ 任务栏——🏠我的声音（空态=三步向导：凭空造/克隆音频/用现成的；有音色=音色库，删除为两段确认按钮）、🎙️说话（当前音色合成 + MiMo 快速试玩 + A/B 对比）、🧬素材（一键补3条/上传/注册正式音色）、🎧声音大厅（免费音色筛选试听）、🎵翻唱（清单式引导）；设置与指南为次级页签。

## 翻唱线（Kits.AI 唱歌换声，已实现）

- 训练在 kits.ai 网页端完成（用多段唱歌素材训练专属音色模型，API 不开放训练）；API 负责换声与分离
- 工作流：网页端训练 → `voice_register_manual(provider="kits", voice_id=数字ID)` 登记（或 `voice_catalog(provider="kits")` 拉取列表）→ 换声
- `voice_convert(audio_path, voice_name, strength?, pitch_shift?)`：干声/清唱换声
- `voice_sing(song_path, voice_name, strength?, pitch_shift?)`：稳定翻唱流水线——人声/伴奏分离 → 人声换声 → 混回伴奏（伴奏不动，稳定关键）；云端约 1~5 分钟
- 混音：有 ffmpeg 直接用；无 ffmpeg 时 wav 直混，mp3 提示安装 ffmpeg 或手动合成
- 音域不合调 pitch_shift（男转女 +4~+7 半音试起）；strength 0.7~0.85 兼顾音色与咬字

## 边界与原则

- 纯云端设计，**不包含任何本地模型部署**（ffmpeg 仅作可选的音频文件处理工具）；密钥只存本机 `config.json`（数据根目录默认 `~/.voice-studio`，环境变量 `VOICE_STUDIO_HOME` 可覆盖）
- 面板为任务流工作台：🏠音色（三步向导/音色库）→ 🎙️说话 → 🧬素材补全 → 🎧声音大厅 → 🎵翻唱，全部作用于顶栏选中的当前音色
