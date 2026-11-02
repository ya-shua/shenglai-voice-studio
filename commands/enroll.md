---
description: 注册（克隆）一个新音色
---
参数 $ARGUMENTS：音色名 [素材文件路径]。

步骤：
1. 调 voice_status 确认供应商已配置；未配置则引导用户在面板「设置」页填阿里云百炼 API Key；
2. 若给了素材路径，调 voice_material_add 入库；否则检查该音色名下是否已有素材（voice_library section="materials"）；
3. 没有素材时向用户说明素材要求（≥10 秒清晰人声、无伴奏无混响，详见 docs/素材采集指南.md）并请用户提供，或让用户在面板「素材库」页上传；
4. 调 voice_enroll(voice_name) 完成声音复刻（约 10~60 秒）；
5. 成功后建议立即用一句问候语 voice_tts 试听，并引导用户到试听台调参对比。
