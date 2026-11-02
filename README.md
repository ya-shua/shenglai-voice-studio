# 声来（voice-studio）

> **一句话，一个声音，一首歌。**
> 你的声音，生来就会唱 —— 克隆 / 说话 / 翻唱，全部云端。

声来是一个 **纯云端 Key 驱动** 的声音工作台插件（ZCode 插件形态）：不部署任何本地模型，一个面板打通「音色获取 → 素材补全 → 说话合成 → 稳定翻唱」全流程，并内置 **6 家供应商 + 万能自定义接入**，模型自由选。

---

## 功能地图

| 任务页 | 能力 |
|---|---|
| 🏠 我的声音 | 空态 = 三步创建向导（凭空造 / 克隆音频 / 用现成的）；有音色 = 音色库管理（专属色头像、删除、两段确认） |
| 🎙️ 说话 | 用当前音色合成（语速/音调/音量调参）+ **MiMo 快速试玩**（内置音色 / 声音设计 / 声音克隆·全模型通用）+ A/B 对比 + 产出记录 |
| 🧬 素材 | ⚡一键补 3 条（AI 朗读口播稿直接入库）+ 拖拽上传 + 时长探测 + 四家注册通道 |
| 🎧 声音大厅 | 聚合 25+ 官方免费音色，分类筛选（温柔型/活力型/沉稳型…）、搜索、在线试听、一键登记使用 |
| 🎵 翻唱 | Kits.AI 流水线：人声/伴奏分离 → 只换人声 → 混回伴奏（`voice_sing`）；清唱直接换声（`voice_convert`） |
| 设置 | 模型接入（DS 式：状态行列表 + ＋添加模型双页签 + 按需引导弹窗）+ 自定义模型 |

## 供应商矩阵（6 内置 + 万能自定义）

| 模型 | 克隆方式 | 费用 |
|---|---|---|
| **小米 MiMo TTS** | 一句话参考音频内联直传（零注册）+ 声音设计 | **限时免费**，合成台首推 |
| **阿里百炼 CosyVoice** | ≥10 秒素材复刻（免费）+ 声音设计（需 Workspace ID）+ 官方音色 | 复刻免费，合成按字符 |
| **硅基流动 SiliconFlow** | 3~10 秒素材上传拿 URI，一个 Key 多底模 | 注册送额度 |
| **ElevenLabs** | Instant Voice Cloning | 有免费额度 |
| **Fish Audio** | 网页端/API 克隆（15 秒） | 有免费层 |
| **Kits.AI** | 多段唱歌素材训练（网页端）→ 翻唱换声 | 订阅制 |
| **自定义模型** | 任意 OpenAI 风格 TTS：填 API 地址（base）+ 协议 + Key | — |

## 快速开始

0. **独立启动（推荐）**：双击数据目录下的 `声来面板.bat`（或桌面「声来」快捷方式）——自动起面板并打开浏览器，无需打开 ZCode；已在运行则直接开浏览器；关闭启动器窗口即停止面板
1. **安装**：ZCode → Plugin Marketplace → Add → 粘贴插件市场目录 → 安装「声来」
2. **接入模型**：面板「设置 → 模型接入」选小米 MiMo（[platform.xiaomimimo.com](https://platform.xiaomimimo.com) 取 Key，TTS 限时免费）；或首次使用时按弹窗引导接入
3. **造第一个声音**：🏠 我的声音 → 「✨ 凭空造一个」→ 一句描述 → 生成并试听
4. **说话**：🎙️ 输入文本 → Ctrl+Enter 合成
5. **翻唱**（可选）：kits.ai 训练歌手音色 → 🎵 上传歌曲一键翻唱

## 数据结构

```
数据根目录（默认 `~/.voice-studio`，环境变量 `VOICE_STUDIO_HOME` 可覆盖）
├── config.json      # 模型 Key 与设置（只存本机）
├── materials/       # 素材库（按音色名分目录）
├── outputs/         # 合成产出（说话/试听/翻唱成品）
└── voices.json      # 音色注册表（名称/供应商/voice_id/模型/素材）
```

## MCP 工具清单（16）

`voice_status` · `voice_provider_setup` · `voice_material_add` · `voice_enroll` · `voice_quick_clone` · `voice_register_manual` · `voice_catalog` · `voice_design` · `voice_material_generate` · `voice_mimo_tts` · `voice_clone_universal` · `voice_convert` · `voice_sing` · `voice_tts` · `voice_library` · `voice_panel`

## 架构

```
声来插件
├── MCP 服务器（stdio，16 工具）──────── AI 对话驱动入口
├── Web 面板（127.0.0.1:17878）──────── 任务流工作台
├── 供应商适配层（capabilities 声明式）
│   ├── mimo / bailian / fish / siliconflow / elevenlabs / kits
│   └── custom:<id> 通用 HTTP 模板适配器（OpenAI 风格自动生成）
├── 业务层 flows（注册/快速克隆/通用克隆/合成/素材/翻唱/大厅）
└── audiomix（wav 纯标准库混音，回退 ffmpeg）
```

新增供应商 = 按约定实现 catalog/enroll/tts 等能力并在注册表登记，**界面零改动**自动出现在模型接入面板。

## 常见问题

- **Key 去哪拿**：MiMo [platform.xiaomimimo.com](https://platform.xiaomimimo.com)｜百炼控制台 API-KEY 管理｜硅基流动 [cloud.siliconflow.cn](https://cloud.siliconflow.cn)｜ElevenLabs/Fish/Kits 各自控制台
- **唱歌素材**：模型生成的素材是"说话"，翻唱歌手音色需真人清唱素材（≥10 分钟干净干声最稳），在 kits.ai 训练
- **混音**：未装 ffmpeg 时 wav 可直混；mp3 伴奏建议安装 ffmpeg
- **翻唱稳定性**：伴奏全程不动只换人声；音域不合调 pitch_shift（男转女 +4~+7 半音试起）

---

版本历史见 [docs/CHANGELOG.md](docs/CHANGELOG.md) ｜ 素材采集指南见 [docs/素材采集指南.md](docs/素材采集指南.md)
