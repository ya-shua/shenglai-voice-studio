# 声来（voice-studio）

> **一句话，一个声音，一首歌。**
> 你的声音，生来就会唱 —— 克隆 / 说话 / 翻唱，云端优先，也能全本地免费。

声来是一个 **声音工作台插件**（ZCode 插件形态）：默认纯云端 Key 驱动，一个面板打通「音色获取 → 素材补全 → 说话合成 → 稳定翻唱」全流程，内置 **6 家云端供应商 + 万能自定义接入**，模型自由选。

另可选接入**本机 Seed-VC + demucs**：翻唱与换声全程免费（不花一分钱、CPU 也能跑），造声音也能用免费的小米 MiMo。

---

## 功能地图

| 任务页 | 能力 |
|---|---|
| 🏠 我的声音 | 空态 = 三步创建向导（凭空造 / 克隆音频 / 用现成的）；有音色 = 音色库管理（专属色头像、删除、两段确认） |
| 🎙️ 说话 | 用当前音色合成（语速/音调/音量调参）+ **MiMo 快速试玩**（内置音色 / 声音设计 / 声音克隆·全模型通用）+ A/B 对比 + 产出记录 |
| 🧬 素材 | ⚡一键补 3 条（AI 朗读口播稿直接入库）+ 拖拽上传 + 时长探测 + 四家注册通道 |
| 🎧 音色大厅 | 聚合 25+ 官方免费音色，男女/风格筛选（温柔型/活力型/沉稳型…）、搜索、在线试听、一键登记使用 |
| 🎵 翻唱 | 双引擎：**本地 Seed-VC（免费）** 或 Kits.AI（付费）；人声/伴奏分离 → 只换人声 → 混回伴奏（`voice_sing`）；清唱直接换声（`voice_convert`） |
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
| **本地 Seed-VC**（可选） | 参考音频 1~30 秒零样本换声 + demucs 人声分离 | **完全免费**（本机 CPU 可跑，整曲约 3~10 分钟） |
| **自定义模型** | 任意 OpenAI 风格 TTS：填 API 地址（base）+ 协议 + Key | — |

## 快速开始

0. **独立启动（推荐）**：双击桌面「声来」快捷方式 —— **无窗口**在后台起面板并自动打开浏览器，无需打开 ZCode；已在运行则只再开一个标签页；**要关闭就点页面右上角「⏻ 关闭」**（或以 `python panel/launch.py --stop` 关闭）
1. **安装**：ZCode → Plugin Marketplace → Add → 粘贴插件市场目录 → 安装「声来」
2. **接入模型**：面板「设置 → 模型接入」选小米 MiMo（[platform.xiaomimimo.com](https://platform.xiaomimimo.com) 取 Key，TTS 限时免费）；或首次使用时按弹窗引导接入
3. **造第一个声音**：✨ 造声音 → 「描述生成」→ 生成方式选 **小米 MiMo（免费）** → 一句描述 → 生成并试听
4. **说话**：🗣️ 输入文本 → Ctrl+Enter 合成
5. **翻唱**（可选，免费路线）：装本地 Seed-VC（见下）→ 🎵 翻唱页引擎选「本地 Seed-VC」→ 上传歌曲一键翻唱

## 本地免费引擎（可选）

翻唱想完全不花钱，就接本机的 [Seed-VC](https://github.com/Plachtaa/seed-vc)：

```bash
git clone https://github.com/Plachtaa/seed-vc.git D:\AI\Models\seed-vc
cd D:\AI\Models\seed-vc
# Windows 建议 Python 3.10/3.11（3.14 装不了 torch 2.x）
python -m venv .venv311 && .venv311\Scripts\pip install -r requirements.txt
pip install demucs
```

然后在面板「设置 → 本地 Seed-VC」填：
- **Seed-VC 目录**：`D:\AI\Models\seed-vc`
- **扩散步数**：15（CPU 上 15 步约 5~6 分钟，步数越低越快）
- **模型下载源**：`https://hf-mirror.com`（国内访问 huggingface 不通时用）

最后登记音色：造声音 → 「登记已有」→ 来源选「本地 Seed-VC」→ voice_id 填**参考音频的绝对路径**（10~30 秒干净干声）。

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
- **怎么关掉面板**：页面右上角「⏻ 关闭」；或 `python panel/launch.py --stop`；启动出错看数据目录的 `panel.log`
- **改完前端没生效**：版本号改了面板会自动提示刷新，或按 `Ctrl+F5` 强制清缓存

## 更新与发布（GitHub）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/ya-shua/shenglai-voice-studio （Public · MIT · `main`） |
| 下载 | [main.zip](https://github.com/ya-shua/shenglai-voice-studio/archive/refs/heads/main.zip) |
| 本地仓库 | 就在插件目录 `D:\AI\插件\plugins\voice-studio` |

发版三件事：

1. **版本号三处同步**：`lib/config.py` 的 `VERSION`、`.zcode-plugin/plugin.json` 的 `version`、市场清单 `marketplace.json` 的 `version`
2. **写 CHANGELOG**：`docs/CHANGELOG.md` 顶部加一条
3. **提交并推送**：`git add -A && git commit` → 推 `main`（HTTPS + PAT）

> 仓库带 **仅本仓库生效** 的 pre-push 隐私门禁：拦截 `sk-…`、`ghp_…`、邮箱、手机号等硬编码密钥与隐私，本机绝对路径只警告。
> `git push` 连不上 github.com 时（hosts 里 IP 失效是常见原因），改用 GitHub API 创建 commit 推送，已写好脚本示例。

完整操作（含 PAT 用法、API 推送脚本、发版检查清单）见 [docs/RELEASING.md](docs/RELEASING.md)。

---

版本历史见 [docs/CHANGELOG.md](docs/CHANGELOG.md) ｜ 素材采集指南见 [docs/素材采集指南.md](docs/素材采集指南.md) ｜ 环形的心对接见 [docs/环形的心对接.md](docs/环形的心对接.md)

## 许可证

[MIT License](LICENSE) © 2026 ya-shua
