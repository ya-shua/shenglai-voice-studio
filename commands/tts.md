---
description: 用已注册音色合成语音（文字转语音）
---
参数 $ARGUMENTS 格式：「音色名」+ 要合成的文本（音色名在最前，文本可含空格与标点）。

步骤：
1. 未指定音色时，先调 voice_library(section="voices") 列出已有音色让用户选；
2. 调 voice_tts(text=文本, voice_name=音色名)；
3. 把返回的产出文件路径以 Markdown 链接发给用户，并提示可调 rate（0.5~2.0）/ pitch（0.5~2.0）/ volume（0~100）重新合成，或 /voice:panel 打开试听台做 A/B 对比。

出错时把错误信息解释给用户。常见原因：音色未注册（先 /voice:enroll）、Key 未配置（面板「设置」页）、素材不合格（见采集指南）。
