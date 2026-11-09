"""voice-studio MCP 服务器（stdio 传输，JSON-RPC 2.0，仅标准库）。

协议：stdin/stdout 上每行一条 JSON-RPC 消息（MCP stdio 约定）；
stdout 只输出协议消息，诊断日志走 stderr。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import config, library  # noqa: E402
from lib import flows  # noqa: E402
from lib.providers import ProviderError, get_provider, list_providers  # noqa: E402

SERVER_INFO = {"name": "voice-studio", "version": config.VERSION}


def log(*args) -> None:
    print("[voice-studio]", *args, file=sys.stderr, flush=True)


# ---------------- 工具实现 ----------------

def tool_status(args: dict) -> str:
    root = config.data_root()
    providers = list_providers()
    voices = library.list_voices()
    lines = [
        f"数据目录: {root}",
        f"音色 {len(voices)} 个 · 产出 {len(library.list_outputs(500))} 条",
        "供应商:",
    ]
    for p in providers:
        mark = "✓ 已配置" if p["configured"] else "✗ 未配置"
        lines.append(
            f"  - {p['display_name']}（{p['id']}）[{mark}] 能力: {', '.join(p['capabilities'])}"
        )
    if not any(p["configured"] for p in providers):
        lines.append(
            "⚠ 尚未配置任何供应商。请用户在阿里云百炼控制台创建 API Key（sk- 开头），"
            "在面板「设置」页填写，或提供后用 voice_provider_setup 写入。"
        )
    return "\n".join(lines)


def tool_provider_setup(args: dict) -> str:
    provider = str(args.get("provider") or "").strip()
    if not provider:
        raise ProviderError("缺少 provider（如 bailian 或 custom:<id>）")
    if provider.startswith("custom:"):
        cc = args.get("custom_config")
        if not isinstance(cc, dict) or not cc:
            raise ProviderError(
                '自定义供应商需提供 custom_config，例如 {"url": "https://api.xxx/v1/audio/speech", '
                '"headers": {"Authorization": "Bearer {{api_key}}"}, '
                '"body": {"model": "tts-1", "input": "{{text}}", "voice": "{{voice_id}}"}, '
                '"audio_from": "binary", "voice_id": "alloy", "display_name": "我的TTS"}'
            )
        values = dict(cc)
        if args.get("api_key"):
            values["api_key"] = str(args["api_key"]).strip()
    else:
        values = {}
        if args.get("api_key"):
            values["api_key"] = str(args["api_key"]).strip()
        if args.get("workspace_id") is not None:
            values["workspace_id"] = str(args["workspace_id"]).strip()
        if args.get("target_model"):
            values["target_model"] = str(args["target_model"]).strip()
        if not values:
            raise ProviderError("没有提供任何要写入的配置项（api_key / workspace_id / target_model）")
    config.set_provider_config(provider, values)
    p = get_provider(provider)
    p.validate_config(config.provider_config(provider))
    caps = ", ".join(p.capabilities) or "无"
    return (
        f"供应商 {p.display_name}（{provider}）配置已保存并通过校验。能力: {caps}。\n"
        "密钥只存本机 config.json。下一步：voice_material_add 入库素材 → voice_enroll 注册音色。"
    )


def tool_material_add(args: dict) -> str:
    name = library.sanitize_name(args.get("voice_name") or "")
    if name == "unnamed":
        raise ProviderError("缺少 voice_name")
    dest = library.add_material(name, args.get("file_path") or "")
    mats = library.list_materials(name)
    return (
        f"素材已入库: {dest}\n音色「{name}」现有 {len(mats)} 个素材: "
        + ", ".join(m["name"] for m in mats)
    )


def tool_enroll(args: dict) -> str:
    name = args.get("voice_name") or ""
    entry = flows.enroll_voice(
        name,
        provider_id=args.get("provider"),
        material_file=args.get("material_file"),
        note=str(args.get("note") or ""),
    )
    lines = [
        f"✅ 音色「{entry['name']}」注册成功（状态: {entry.get('status', 'ready')}）",
        f"voice_id: {entry.get('voice_id')}",
        f"供应商/模型: {entry.get('provider')} / {entry.get('target_model') or '默认'}",
        f"使用素材: {entry.get('material_used', '-')}",
    ]
    if entry.get("notice"):
        lines.append("⚠ " + entry["notice"])
    lines.append(f'下一步: voice_tts(text="你好，欢迎来到声来。", voice_name="{entry["name"]}") 试听。')
    return "\n".join(lines)


def tool_register_manual(args: dict) -> str:
    entry = flows.register_voice_manual(
        args.get("voice_name") or "",
        args.get("provider") or "bailian",
        args.get("voice_id") or "",
        target_model=str(args.get("target_model") or ""),
        note=str(args.get("note") or ""),
    )
    return (
        f"✅ 音色「{entry['name']}」已手动登记（voice_id: {entry['voice_id']}，"
        f"供应商: {entry['provider']}）。可直接 voice_tts 使用。"
    )


def tool_tts(args: dict) -> str:
    opts = {}
    for key in ("format", "sample_rate", "rate", "pitch", "volume", "emotion", "mood"):
        if args.get(key) is not None:
            opts[key] = args[key]
    result = flows.synthesize(args.get("text") or "", args.get("voice_name") or "", opts)
    kb = result["size"] / 1024
    return (
        f"✅ 合成完成（音色「{result['voice']}」）\n"
        f"文件: {result['path']}\n"
        f"大小 {kb:.0f} KB · 格式 {result['ext']}\n"
        "把上面的文件路径发给用户即可播放；调 rate/pitch/volume 可重新合成对比，"
        "或 /voice:panel 打开试听台做 A/B。"
    )


def tool_quick_clone(args: dict) -> str:
    opts = {}
    for key in ("rate", "pitch", "volume"):
        if args.get(key) is not None:
            opts[key] = args[key]
    result = flows.quick_clone(
        args.get("audio_path") or "",
        args.get("text") or "",
        provider_id=args.get("provider") or "bailian",
        voice_name=args.get("voice_name"),
        keep_voice=bool(args.get("keep_voice")),
        opts=opts,
    )
    lines = [
        f"✅ 一句话快速克隆完成（音色「{result['voice']}」"
        + ("已保留到音色库" if result["kept"] else "临时音色已用后即弃）"),
        f"文件: {result['path']}",
        f"大小 {result['size'] / 1024:.0f} KB · 格式 {result['ext']}",
    ]
    if result.get("notice"):
        lines.append("⚠ " + result["notice"])
    lines.append("把文件路径发给用户播放。想要这个音色长期可用？用 keep_voice=true 重跑，或 voice_enroll 正式注册。")
    return "\n".join(lines)


def tool_catalog(args: dict) -> str:
    """列出供应商可用的预置/自有音色目录（自由选模型）。"""
    pid = str(args.get("provider") or "").strip()
    cfg_all = config.load_config()
    if pid:
        targets = [pid]
    else:
        targets = ["bailian", "fish"] + ["custom:" + k for k in cfg_all["custom"]]
    lines = []
    for p_id in targets:
        try:
            p = get_provider(p_id)
        except ProviderError as e:
            lines.append(f"- {p_id}: {e}")
            continue
        if "catalog" not in p.capabilities:
            continue
        try:
            items = p.catalog(config.provider_config(p_id))
        except ProviderError as e:
            lines.append(f"【{p.display_name}】目录获取失败: {e}")
            continue
        lines.append(f"【{p.display_name}】可用音色 {len(items)} 个：")
        for it in items[:20]:
            model = f" | 模型 {it['target_model']}" if it.get("target_model") else ""
            lines.append(f"  - {it.get('voice_id')} | {it.get('name', '')}{model}")
        if len(items) > 20:
            lines.append(f"  …其余 {len(items) - 20} 个")
        lines.append(
            f"  登记使用: voice_register_manual(voice_name=自定义名, provider='{p_id}', "
            "voice_id=上面的音色ID"
            + (", target_model=对应模型" if p_id == "bailian" else "") + ")"
        )
    return "\n".join(lines) if lines else "（暂无提供音色目录的供应商）"


def tool_design(args: dict) -> str:
    entry = flows.design_voice(
        args.get("voice_name") or "",
        args.get("description") or "",
        preview_text=args.get("preview_text"),
        provider_id=args.get("provider") or "bailian",
        target_model=str(args.get("target_model") or ""),
        language=str(args.get("language") or "zh"),
        save_preview_material=bool(args.get("save_preview_material")),
    )
    lines = [
        f"✅ AI 音色「{entry['name']}」已生成（{entry.get('provider')} / {entry.get('target_model')}）",
        f"voice_id: {entry['voice_id']}",
        f"音色描述: {entry.get('note')}",
    ]
    if entry.get("preview_path"):
        lines.append(f"试听已保存: {entry['preview_path']}")
    if entry.get("notice"):
        lines.append("⚠ " + entry["notice"])
    lines.append(f'下一步: voice_tts(text="...", voice_name="{entry["name"]}")')
    return "\n".join(lines)


def tool_material_generate(args: dict) -> str:
    opts = {}
    for key in ("rate", "pitch", "volume"):
        if args.get(key) is not None:
            opts[key] = args[key]
    r = flows.generate_material(
        args.get("text") or "",
        args.get("voice_name") or "",
        args.get("source_voice") or "",
        opts,
    )
    return (
        f"✅ 素材已生成并存入「{r['voice']}」的素材库（源音色: {r['source']}）\n"
        f"文件: {r['path']}\n"
        f"大小 {r['size'] / 1024:.0f} KB。凑够 ≥10 秒素材后，voice_enroll(voice_name=\"{r['voice']}\") "
        "即可克隆成正式音色。"
    )


def tool_convert(args: dict) -> str:
    r = flows.convert_vocal(
        args.get("audio_path") or "",
        args.get("voice_name") or "",
        strength=float(args.get("strength") or 0.8),
        pitch_shift=int(args.get("pitch_shift") or 0),
        engine=(args.get("engine") or "kits"),
    )
    return (
        f"✅ 换声完成（音色「{r['voice']}」）\n"
        f"文件: {r['path']}\n"
        f"大小 {r['size'] / 1024:.0f} KB。要出完整翻唱请用 voice_sing（自动分离伴奏并混回）。"
    )


def tool_sing_cover(args: dict) -> str:
    r = flows.sing_cover(
        args.get("song_path") or "",
        args.get("voice_name") or "",
        strength=float(args.get("strength") or 0.8),
        pitch_shift=int(args.get("pitch_shift") or 0),
        engine=(args.get("engine") or "kits"),
    )
    lines = [f"✅ 翻唱完成（{r['voice']} × {r['song']}）"]
    if r.get("final"):
        lines.append(f"成品: {r['final']}\n混音方式: {r['mix_method']}")
    lines.append(f"换声干声: {r['converted']}")
    if r.get("backing"):
        lines.append(f"原曲伴奏: {r['backing']}")
    lines.append("云端处理约 1~5 分钟属正常；伴奏全程未动，只换人声音色，保证稳定。")
    return "\n".join(lines)


def tool_mimo_tts(args: dict) -> str:
    r = flows.mimo_synthesize(
        args.get("mode") or "builtin",
        args.get("text") or "",
        style=str(args.get("style") or ""),
        voice=str(args.get("voice") or ""),
        voice_prompt=str(args.get("voice_prompt") or ""),
        reference_audio_path=str(args.get("reference_audio_path") or ""),
    )
    return (
        f"✅ MiMo 合成完成（模式: {r['mode']}）\n"
        f"文件: {r['path']}\n"
        f"大小 {r['size'] / 1024:.0f} KB。内置音色支持风格指令与 (唱歌) 等音频标签。"
    )


def tool_clone_universal(args: dict) -> str:
    r = flows.universal_clone(
        args.get("provider") or "",
        args.get("text") or "",
        style=str(args.get("style") or ""),
        reference_audio_path=str(args.get("reference_audio_path") or ""),
        keep=bool(args.get("keep")),
    )
    lines = [
        f"✅ 通用克隆完成（模型: {r.get('provider_name', r.get('mode'))} · 模式: {r['mode']}）",
        f"文件: {r['path']}",
        f"大小 {r['size'] / 1024:.0f} KB",
    ]
    if r.get("kept"):
        lines.append(f"音色已保留: {r.get('voice')}")
    return "\n".join(lines)


def tool_library(args: dict) -> str:
    section = str(args.get("section") or "all")
    lines = []
    if section in ("all", "voices"):
        voices = library.list_voices()
        lines.append(f"【音色】{len(voices)} 个")
        for v in voices:
            lines.append(
                f"  - {v['name']} | {v.get('provider')} | {v.get('voice_id')}"
                f" | 模型 {v.get('target_model') or '默认'} | {v.get('status', 'ready')}"
            )
        if not voices:
            lines.append("  （空）先用 voice_material_add 入库素材，再 voice_enroll 注册")
    if section in ("all", "materials"):
        names = library.list_material_voices()
        lines.append(f"【素材】{len(names)} 个音色名下有素材")
        for n in names:
            mats = library.list_materials(n)
            preview = ", ".join(m["name"] for m in mats[:5]) + ("…" if len(mats) > 5 else "")
            lines.append(f"  - {n}: {len(mats)} 个（{preview}）")
    if section in ("all", "outputs"):
        outs = library.list_outputs(20)
        lines.append(f"【最近产出】{len(outs)} 条")
        for o in outs:
            lines.append(f"  - {o['name']}（{o['size'] // 1024} KB）")
    return "\n".join(lines) if lines else "（空）"


def _port_open(port: int) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/status", headers={"Connection": "close"}
        )
        with urllib.request.urlopen(req, timeout=1.5):
            return True
    except OSError:
        return False


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def tool_panel(args: dict) -> str:
    meta_path = config.data_root() / ".panel.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            port = int(meta.get("port", 0))
            if port and _port_open(port):
                return (
                    f"面板已在运行: http://127.0.0.1:{port}\n"
                    "页签：设置（Key）/ 素材库 / 音色 / 试听台 / 采集指南"
                )
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    port = 17878
    for _ in range(50):
        if _port_free(port):
            break
        port += 1
    log_file = open(config.data_root() / ".panel.log", "ab")
    try:
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [sys.executable, "-u", str(PLUGIN_ROOT / "panel" / "server.py"), "--port", str(port)],
            cwd=str(PLUGIN_ROOT),
            stdout=log_file,
            stderr=log_file,
            creationflags=flags,
        )
    finally:
        log_file.close()
    deadline = time.time() + 15
    while time.time() < deadline:
        if _port_open(port):
            meta_path.write_text(json.dumps({"port": port}), encoding="utf-8")
            return (
                f"✅ 面板已启动: http://127.0.0.1:{port}\n"
                "首次使用请先在「设置」页填 API Key，再到「素材库」上传素材。"
            )
        time.sleep(0.3)
    raise ProviderError(
        f"面板启动超时，请查看日志 {config.data_root() / '.panel.log'}"
    )


# ---------------- 对外门面（facade） ----------------
# 设计：MCP 对外只暴露「说话 voice_speak」「唱歌 voice_sing」两个工具；
# 上面的 tool_* 全部是内部能力（配 Key、注册、克隆、素材、换声等），由门面内部编排，
# 管理类操作统一引导用户在 Web 面板完成。

def _resolve_voice(voice_name) -> str:
    """解析目标音色：显式指定优先，否则用当前音色；都没有则引导去面板。"""
    name = library.sanitize_name(voice_name or "")
    if name == "unnamed":
        name = library.sanitize_name(library.get_current_voice())
    if name == "unnamed":
        raise ProviderError(
            "没有可用音色：请先在 Web 面板注册音色并设为当前音色（/voice:panel 打开面板）。"
        )
    return name


def tool_speak(args: dict) -> str:
    """对外·说话：文本 → 语音（默认用当前音色）。"""
    name = _resolve_voice(args.get("voice_name"))
    opts = {}
    for key in ("format", "sample_rate", "rate", "pitch", "volume", "emotion", "style"):
        if args.get(key) is not None:
            opts[key] = args[key]
    result = flows.synthesize(args.get("text") or "", name, opts)
    return (
        f"✅ 说话完成（音色「{result['voice']}」）\n"
        f"文件: {result['path']}\n"
        f"AUDIO: {result['path']}\n"
        f"大小 {result['size'] / 1024:.0f} KB · 格式 {result['ext']}"
    )


def tool_sing(args: dict) -> str:
    """对外·唱歌：歌曲 → 稳定翻唱成品（默认用当前音色）。"""
    name = _resolve_voice(args.get("voice_name"))
    r = flows.sing_cover(
        args.get("song_path") or "",
        name,
        strength=float(args.get("strength") or 0.8),
        pitch_shift=int(args.get("pitch_shift") or 0),
        engine=(args.get("engine") or "kits"),
    )
    lines = [f"✅ 唱歌完成（{r['voice']} × {r['song']}）"]
    if r.get("final"):
        lines.append(f"成品: {r['final']}\n混音方式: {r['mix_method']}")
    lines.append(f"换声干声: {r['converted']}")
    if r.get("backing"):
        lines.append(f"原曲伴奏: {r['backing']}")
    lines.append("伴奏全程未动，只换人声音色，保证稳定。")
    return "\n".join(lines)


# 对外工具契约：只有这两个会出现在 tools/list
HANDLERS = {
    "voice_speak": tool_speak,
    "voice_sing": tool_sing,
}

TOOLS = [
    {
        "name": "voice_speak",
        "description": (
            "说话：把文本合成为语音，产出 wav/mp3 文件并返回路径。"
            "voice_name 省略时用当前音色。可选 emotion 情绪、style 语气描述、rate 语速 0.5~2.0、"
            "pitch 音调 0.5~2.0、volume 音量 0~100、format 格式。"
            "caller 可直接给 rate/pitch 数值覆盖心情预设；style 与 emotion 不要同时传。"
            "配 Key、注册/克隆音色等管理操作请在 Web 面板完成。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要合成的文本"},
                "voice_name": {"type": "string", "description": "目标音色名，省略用当前音色"},
                "emotion": {"type": "string", "enum": ["默认", "开心", "兴奋", "温柔", "生气", "委屈", "难过", "撒娇", "困倦", "得意"], "description": "情绪，默认 默认"},
                "format": {"type": "string", "enum": ["wav", "mp3"], "description": "默认 wav"},
                "sample_rate": {"type": "integer", "description": "默认 24000"},
                "rate": {"type": "number", "description": "语速 0.5~2.0，默认 1.0"},
                "pitch": {"type": "number", "description": "音调 0.5~2.0，默认 1.0"},
                "volume": {"type": "integer", "description": "音量 0~100，默认 50"},
                "style": {"type": "string", "description": "语气描述，如「语速偏快，句尾上扬」。省略则按 emotion 或基准"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "voice_sing",
        "description": (
            "唱歌：稳定翻唱流水线——歌曲人声/伴奏分离 → 人声换声 → 混回伴奏 → 成品。"
            "voice_name 省略时用当前音色。engine=local-svc 走本机免费引擎（慢），"
            "engine=kits 走云端（需 Key，约 1~5 分钟）。伴奏全程不动只换人声。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "song_path": {"type": "string", "description": "歌曲文件（wav/mp3/flac/webm ≤50MB）"},
                "voice_name": {"type": "string", "description": "目标音色名，省略用当前音色"},
                "strength": {"type": "number", "description": "转换强度 0~1，默认 0.8"},
                "pitch_shift": {"type": "integer", "description": "半音偏移，默认 0"},
                "engine": {"type": "string", "enum": ["kits", "local-svc"], "description": "引擎，默认 kits"},
            },
            "required": ["song_path"],
        },
    },
]


# ---------------- MCP 协议层 ----------------

def dispatch(method: str, params: dict) -> dict:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = str(params.get("name") or "")
        handler = HANDLERS.get(name)
        if handler is None:
            raise LookupError(f"未知工具: {name}")
        text = handler(dict(params.get("arguments") or {}))
        return {"content": [{"type": "text", "text": text}], "isError": False}
    raise LookupError(f"不支持的方法: {method}")


def main() -> None:
    log("started, plugin root:", PLUGIN_ROOT)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = str(msg.get("method") or "")
        msg_id = msg.get("id")
        if method.startswith("notifications/"):
            continue
        try:
            result = dispatch(method, dict(msg.get("params") or {}))
            resp = {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except LookupError as e:
            resp = {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": str(e)}}
        except Exception as e:  # 业务错误以 isError 结果返回，便于客户端展示
            if method == "tools/call":
                resp = {"jsonrpc": "2.0", "id": msg_id,
                        "result": {"content": [{"type": "text", "text": f"出错: {e}"}],
                                   "isError": True}}
            else:
                resp = {"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32000, "message": str(e)}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
