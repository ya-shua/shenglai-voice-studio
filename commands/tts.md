---
description: 用音色合成语音（说话）
---
参数 $ARGUMENTS 格式：「音色名」+ 要合成的文本（音色名可省略，省略用当前音色；文本可含空格与标点）。

步骤：
1. 调 voice_speak：
   - 指定音色：voice_speak(text=文本, voice_name=音色名)
   - 用当前音色：voice_speak(text=文本)
2. 把返回的文件路径以 Markdown 链接发给用户，并提示可选 emotion（情绪）、rate（语速 0.5~2.0）、pitch（音调 0.5~2.0）、volume（音量 0~100）、format（wav/mp3）重新合成。

出错时把错误信息解释给用户。常见原因：没有可用音色（先 /voice:panel 在面板注册并设为当前音色）、Key 未配置（面板「设置」页）。
