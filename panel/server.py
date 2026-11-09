"""声来本地面板服务（仅标准库，绑定 127.0.0.1）。

REST API + 静态前端（panel/www）。由 mcp/server.py 的 voice_panel 工具拉起，
也可手动运行: python panel/server.py [--port 17878]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import local_modules  # noqa: E402  本地引擎模块管理器
from lib import usage as local_usage  # noqa: E402  用量记账
from lib import local_update  # noqa: E402  更新检查与一键更新

from lib import config, flows, library, mine  # noqa: E402
from lib.providers import ProviderError, get_provider, list_providers  # noqa: E402

WWW = PLUGIN_ROOT / "panel" / "www"
METADATA_FILE = PLUGIN_ROOT / "metadata.json"
STARTED_AT = time.time()  # 进程启动时刻（uptime 基准）
STARTED_ISO = datetime.now().astimezone().isoformat(timespec="seconds")

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}
AUDIO_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
}


def api_status() -> dict:
    providers = list_providers()
    return {
        "app": "voice-studio",
        "version": config.VERSION,
        "data_root": str(config.data_root()),
        "any_provider": any(p["configured"] for p in providers),
        "providers": providers,
        "voices": library.list_voices(),
        "material_voices": library.list_material_voices(),
        "outputs_count": len(library.list_outputs(500)),
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }


def plugin_metadata() -> dict:
    """仓库根 metadata.json 原文（身份以文件为准；读不到时给最小可用身份，不让面板挂掉）。"""
    try:
        data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {"id": "voice", "version": config.VERSION}


def api_health() -> dict:
    """只读探活：宿主据此判断「这是谁、什么版本、活了多久」。"""
    meta = plugin_metadata()
    return {
        "ok": True,
        "id": str(meta.get("id") or "voice"),
        "version": config.VERSION,  # 真实版本只维护在 lib/config.py
        "uptime_s": int(time.time() - STARTED_AT),
    }


def api_manifest(port: int) -> dict:
    """只读身份与运行态：metadata 全文 + 实际监听端口 / pid / 启动时间。"""
    return {
        "ok": True,
        "metadata": plugin_metadata(),
        "runtime": {
            "port": int(port),
            "pid": os.getpid(),
            "started_at": STARTED_ISO,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "VoiceStudioPanel/" + config.VERSION

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    # ---- 输出助手 ----

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: Path) -> None:
        ctype = STATIC_TYPES.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _audio_file(self, path: Path) -> None:
        path = path.resolve()
        allowed = [
            (config.data_root() / "materials").resolve(),
            (config.data_root() / "outputs").resolve(),
        ]
        if not any(path.is_relative_to(root) for root in allowed):
            return self._json({"error": "路径越界"}, 403)
        if not path.is_file():
            return self._json({"error": "文件不存在"}, 404)
        ctype = AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            start_s, _, end_s = rng[6:].partition("-")
            try:
                start = int(start_s or 0)
                end = int(end_s) if end_s else len(data) - 1
            except ValueError:
                start, end = 0, len(data) - 1
            end = min(end, len(data) - 1)
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _body_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length)

    # ---- 路由 ----

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                html = (WWW / "index.html").read_text(encoding="utf-8")
                # 把真实版本注入前端：app.js 用 window.__APP_VERSION__ 判断「自己是不是旧版」，
                # 版本号只在这一处（lib/config.py）维护，避免前后端各写一份对不上。
                html = html.replace(
                    '<script src="/app.js">',
                    '<script>window.__APP_VERSION__="' + config.VERSION + '";</script>\n'
                    '  <script src="/app.js">',
                )
                v = config.VERSION + "-" + str(int(time.time()))  # 启动戳：每次重启必拉新静态资源
                html = html.replace('href="/style.css"', f'href="/style.css?v={v}"')
                html = html.replace('src="/app.js"', f'src="/app.js?v={v}"')
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if route in ("/app.js", "/style.css", "/logo.svg"):
                return self._static(WWW / route.lstrip("/"))
            if route == "/api/status":
                return self._json(api_status())
            if route == "/api/health":
                return self._json(api_health())
            if route == "/api/manifest":
                # 端口以实际监听为准（--port 被占用时 main() 会自动 +1）
                return self._json(api_manifest(self.server.server_address[1]))
            if route == "/api/config":
                return self._json(config.public_config())
            if route == "/api/providers":
                return self._json({"providers": list_providers()})
            if route == "/api/voices":
                return self._json({"voices": library.list_voices()})
            if route == "/api/material-voices":
                return self._json({"voices": library.list_material_voices()})
            if route == "/api/hall":
                return self._json({"ok": True, "voices": flows.hall_voices()})
            if route == "/api/local-modules":
                return self._json({"ok": True, "modules": local_modules.list_modules()})
            if route == "/api/update-check":
                return self._json({"ok": True, **local_update.check()})
            if route == "/api/usage":
                return self._json({"ok": True, **local_usage.aggregate(14)})
            if route == "/api/speak" or route == "/api/speak/voices":
                return self._handle_speak(route, q)
            if route == "/api/preview-cache":
                from lib import preview_store
                pid = (q.get("provider") or [""])[0]
                vid = (q.get("voice_id") or [""])[0]
                text = (q.get("text") or [""])[0]
                hit = preview_store.get(pid, vid, text)
                if hit:
                    return self._json({"ok": True, "cached": True,
                                       "url": "/api/preview-file?name=" + urllib.parse.quote(hit.name)})
                # 官方样音兜底（bailian/siliconflow 未接入也可直接播）
                from lib import preview_audio
                demo = preview_audio.official_demo(pid, vid)
                if demo:
                    return self._json({"ok": True, "official_demo": True,
                                       "url": demo[0]})
                return self._json({"ok": True, "miss": True})
            if route == "/api/preview-file":
                name = urllib.parse.unquote((q.get("name") or [""])[0])
                from lib import preview_store
                p2 = (config.data_root() / "preview_cache" / name).resolve()
                if not p2.is_relative_to((config.data_root() / "preview_cache").resolve()) or not p2.is_file():
                    return self._json({"error": "文件不存在"}, 404)
                data = p2.read_bytes()
                ctype = {".mp3": "audio/mpeg", ".wav": "audio/wav"}.get(p2.suffix.lower(), "audio/mpeg")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return

            if route == "/api/catalog":
                pid = (q.get("provider") or [""])[0]
                if not pid:
                    raise ProviderError("缺少 provider")
                p = get_provider(pid)
                if "catalog" not in p.capabilities:
                    raise ProviderError(f"{p.display_name} 不提供音色目录")
                items = p.catalog(config.provider_config(pid))
                return self._json({"ok": True, "provider": pid, "items": items})
            if route == "/api/materials":
                name = (q.get("voice") or [""])[0]
                return self._json({"materials": library.list_materials(name)})
            if route == "/api/materials/file":
                voice = (q.get("voice") or [""])[0]
                name = urllib.parse.unquote((q.get("name") or [""])[0])
                return self._audio_file(library.materials_dir(voice) / name)
            if route == "/api/outputs":
                return self._json({"outputs": library.list_outputs(100)})
            if route == "/api/outputs/file":
                name = urllib.parse.unquote((q.get("name") or [""])[0])
                return self._audio_file(config.data_root() / "outputs" / name)
            if route == "/api/mine/settings":
                return self._json({"ok": True, "settings": mine.load_settings()})
            if route == "/api/mine/history":
                return self._json({"ok": True, "history": mine.list_history()})
            return self._json({"error": "not found"}, 404)
        except ProviderError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _handle_speak(self, route: str, q: dict) -> None:
        """GET /api/speak 与 /api/speak/voices：对外语音接口（环形的心/任意框架对接）。"""
        uq = lambda k, d="": urllib.parse.unquote((q.get(k) or [d])[0])
        if route == "/api/speak/voices":
            voices = []
            for v in library.list_voices():
                if (v.get("status") or "ready") != "failed":
                    voices.append({"name": v["name"], "provider": v.get("provider", ""),
                                   "model": v.get("target_model", "")})
            return self._json({"ok": True, "voices": voices, "current": library.get_current_voice()})
        voice = uq("voice") or library.get_current_voice() or "测试御姐"
        text = uq("text")
        rate = float(uq("rate", "1.0") or 1.0)
        emotion = uq("emotion")  # 情绪标签（开心/生气/温柔…）：情绪插件联动入口
        if not text.strip():
            return self._json({"error": "text 不能为空"}, 400)
        try:
            result = flows.synthesize(text, voice, {"rate": rate, "emotion": emotion})
        except ProviderError as e:
            return self._json({"error": str(e)}, 400)
        ctype = "audio/wav" if result["ext"] == "wav" else "audio/mpeg"
        if (q.get("json") or ["0"])[0] == "1":
            body = json.dumps({"ok": True, "file": result["file"],
                               "url": "/api/outputs/file?name=" + urllib.parse.quote(result["file"])},
                              ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        audio = open(result["path"], "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(audio)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        try:
            if route == "/api/shutdown":
                self._json({"ok": True, "message": "面板已关闭"})
                # 先把响应发出去，再退出进程
                threading.Timer(0.4, lambda: os._exit(0)).start()
                return
            if route == "/api/config":
                body = self._body_json()
                pid = str(body.get("provider") or "")
                if not pid:
                    raise ProviderError("缺少 provider")
                config.set_provider_config(pid, body.get("values") or {})
                get_provider(pid).validate_config(config.provider_config(pid))
                return self._json({"ok": True})
            if route == "/api/materials/upload":
                voice = urllib.parse.unquote((q.get("voice") or [""])[0])
                if not voice:
                    raise ProviderError("缺少音色名（?voice=）")
                filename = Path(urllib.parse.unquote(
                    self.headers.get("X-Filename") or "material.wav")).name
                incoming = config.data_root() / "materials" / "_incoming"
                incoming.mkdir(parents=True, exist_ok=True)
                tmp = incoming / filename
                tmp.write_bytes(self._body_bytes())
                try:
                    dest = library.add_material(voice, tmp)
                finally:
                    tmp.unlink(missing_ok=True)
                return self._json({"ok": True, "material": dest.name,
                                   "materials": library.list_materials(voice)})
            if route == "/api/voices/enroll":
                body = self._body_json()
                entry = flows.enroll_voice(
                    str(body.get("voice_name") or ""),
                    provider_id=body.get("provider") or None,
                    material_file=body.get("material_file") or None,
                    note=str(body.get("note") or ""),
                )
                return self._json({"ok": True, "voice": entry})
            if route == "/api/voices/manual":
                body = self._body_json()
                entry = flows.register_voice_manual(
                    str(body.get("voice_name") or ""),
                    str(body.get("provider") or "bailian"),
                    str(body.get("voice_id") or ""),
                    target_model=str(body.get("target_model") or ""),
                    note=str(body.get("note") or ""),
                )
                return self._json({"ok": True, "voice": entry})
            if route == "/api/voices/current":
                # 设为 TTS 输出默认音色（大厅「用她说话」/顶栏切换都会调这里）
                body = self._body_json()
                name = str(body.get("name") or "")
                if not library.set_current_voice(name):
                    return self._json({"ok": False, "error": f"音色「{name}」不存在"}, 404)
                return self._json({"ok": True, "current": name})
            if route == "/api/verify-key":
                # 在线校验某供应商的 Key（零成本探活，5 分钟缓存）
                body = self._body_json()
                try:
                    return self._json(flows.verify_provider_key(str(body.get("provider") or "")))
                except ProviderError as e:
                    return self._json({"ok": False, "message": str(e)}, 400)
            if route == "/api/cross-clone":
                # 跨平台复刻：源音色样音素材 → 目标平台克隆登记
                body = self._body_json()
                try:
                    return self._json(flows.cross_clone(
                        str(body.get("source") or ""), str(body.get("voice_id") or ""),
                        str(body.get("target") or ""), new_name=str(body.get("name") or "")))
                except ProviderError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            if route == "/api/local-modules/install":
                body = self._body_json()
                return self._json(local_modules.start_install(str(body.get("id") or ""),
                                                             dir_override=str(body.get("dir") or "")))
            if route == "/api/local-modules/cancel":
                body = self._body_json()
                return self._json(local_modules.cancel_install(str(body.get("id") or "")))
            if route == "/api/update":
                return self._json(local_update.do_update())
            if route == "/api/local-modules/uninstall":
                body = self._body_json()
                return self._json(local_modules.uninstall(str(body.get("id") or "")))
            if route == "/api/voices/delete":
                body = self._body_json()
                return self._json({"ok": True, **flows.delete_voice(
                    str(body.get("voice_name") or ""),
                    also_cloud=bool(body.get("also_cloud")),
                )})
            if route == "/api/voices/rename":
                body = self._body_json()
                try:
                    entry = library.rename_voice(
                        str(body.get("from") or ""), str(body.get("to") or "")
                    )
                except (ValueError, FileNotFoundError) as e:
                    raise ProviderError(str(e))
                return self._json({"ok": True, "voice": entry})
            if route == "/api/voices/sing-ready":
                body = self._body_json()
                try:
                    entry = library.set_sing_ready(
                        str(body.get("name") or ""), bool(body.get("ready"))
                    )
                except FileNotFoundError as e:
                    raise ProviderError(str(e))
                return self._json({"ok": True, "voice": entry})
            if route == "/api/quick-clone":
                qv = lambda key, default="": urllib.parse.unquote((q.get(key) or [default])[0])  # noqa: E731
                filename = Path(urllib.parse.unquote(
                    self.headers.get("X-Filename") or "ref.wav")).name
                incoming = config.data_root() / "materials" / "_incoming"
                incoming.mkdir(parents=True, exist_ok=True)
                tmp = incoming / filename
                tmp.write_bytes(self._body_bytes())
                try:
                    opts = {}
                    for key in ("rate", "pitch", "volume"):
                        raw_val = qv(key)
                        if raw_val:
                            opts[key] = float(raw_val) if key != "volume" else int(float(raw_val))
                    result = flows.quick_clone(
                        str(tmp),
                        qv("text"),
                        provider_id=qv("provider") or "bailian",
                        voice_name=qv("voice_name") or None,
                        keep_voice=qv("keep_voice") == "1",
                        opts=opts,
                    )
                finally:
                    tmp.unlink(missing_ok=True)
                result["url"] = "/api/outputs/file?name=" + urllib.parse.quote(result["file"])
                return self._json({"ok": True, **result})
            if route == "/api/voices/design":
                body = self._body_json()
                entry = flows.design_voice(
                    str(body.get("voice_name") or ""),
                    str(body.get("description") or ""),
                    preview_text=body.get("preview_text") or None,
                    provider_id=body.get("provider") or "bailian",
                    target_model=str(body.get("target_model") or ""),
                    save_preview_material=bool(body.get("save_preview_material")),
                )
                if entry.get("preview_path"):
                    entry["preview_url"] = "/api/outputs/file?name=" + urllib.parse.quote(
                        Path(entry["preview_path"]).name
                    )
                return self._json({"ok": True, "voice": entry})
            if route == "/api/materials/generate":
                body = self._body_json()
                opts = {}
                for key in ("rate", "pitch", "volume"):
                    if body.get(key) not in (None, ""):
                        opts[key] = float(body[key]) if key != "volume" else int(float(body[key]))
                result = flows.generate_material(
                    str(body.get("text") or ""),
                    str(body.get("voice_name") or ""),
                    str(body.get("source_voice") or ""),
                    opts,
                )
                return self._json({"ok": True, **result})
            if route in ("/api/kits/sing", "/api/kits/convert"):
                voice_name = urllib.parse.unquote((q.get("voice_name") or [""])[0])
                strength = float((q.get("strength") or ["0.8"])[0] or 0.8)
                pitch = int(float((q.get("pitch_shift") or ["0"])[0] or 0))
                engine = (q.get("engine") or ["kits"])[0] or "kits"
                filename = Path(urllib.parse.unquote(
                    self.headers.get("X-Filename") or "song.mp3")).name
                incoming = config.data_root() / "materials" / "_incoming"
                incoming.mkdir(parents=True, exist_ok=True)
                tmp = incoming / filename
                tmp.write_bytes(self._body_bytes())
                try:
                    if route == "/api/kits/sing":
                        result = flows.sing_cover(str(tmp), voice_name, strength, pitch, engine=engine)
                        for key in ("vocal", "backing", "converted", "final"):
                            if result.get(key):
                                result[key + "_url"] = "/api/outputs/file?name=" + urllib.parse.quote(
                                    Path(result[key]).name)
                    else:
                        result = flows.convert_vocal(str(tmp), voice_name, strength, pitch, engine=engine)
                        result["url"] = "/api/outputs/file?name=" + urllib.parse.quote(
                            Path(result["path"]).name)
                finally:
                    tmp.unlink(missing_ok=True)
                return self._json({"ok": True, **result})
            if route == "/api/mimo/synthesize":
                body = self._body_json()
                result = flows.mimo_synthesize(
                    str(body.get("mode") or "builtin"),
                    str(body.get("text") or ""),
                    style=str(body.get("style") or ""),
                    voice=str(body.get("voice") or ""),
                    voice_prompt=str(body.get("voice_prompt") or ""),
                    reference_data_uri=str(body.get("ref_data_uri") or ""),
                )
                result["url"] = "/api/outputs/file?name=" + urllib.parse.quote(result["file"])
                return self._json({"ok": True, **result})
            if route == "/api/warm-previews":
                body = self._body_json()
                pid = str(body.get("provider") or (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("provider") or [""])[0])
                def _warm():
                    try:
                        n = flows.warm_previews(pid)
                        print(f"warm {pid}: {n} previews", file=sys.stderr)
                    except Exception as e:
                        print(f"warm {pid} fail: {e}", file=sys.stderr)
                threading.Thread(target=_warm, daemon=True).start()
                return self._json({"ok": True, "started": pid})
            if route == "/api/preview":
                body = self._body_json()
                result = flows.preview_voice(
                    str(body.get("provider") or ""),
                    str(body.get("voice_id") or ""),
                    target_model=str(body.get("target_model") or ""),
                    text=str(body.get("text") or ""),
                )
                result["url"] = "/api/preview-file?name=" + urllib.parse.quote(result["file"])
                return self._json({"ok": True, **result})
            if route == "/api/clone-universal":
                body = self._body_json()
                result = flows.universal_clone(
                    str(body.get("provider") or ""),
                    str(body.get("text") or ""),
                    style=str(body.get("style") or ""),
                    reference_data_uri=str(body.get("ref_data_uri") or ""),
                    keep=bool(body.get("keep")),
                )
                result["url"] = "/api/preview-file?name=" + urllib.parse.quote(result["file"])
                return self._json({"ok": True, **result})
            if route == "/api/speak":
                body = self._body_json()
                result = flows.synthesize(
                    str(body.get("text") or ""),
                    str(body.get("voice") or ""),
                    {"rate": float(body.get("rate") or 1.0),
                     "emotion": str(body.get("emotion") or ""),
                     "mood": str(body.get("mood") or "")})
                result["url"] = "/api/preview-file?name=" + urllib.parse.quote(result["file"])
                return self._json({"ok": True, **result})
            if route == "/api/tts":
                body = self._body_json()
                opts = {}
                for key in ("format", "sample_rate", "rate", "pitch", "volume", "emotion", "mood"):
                    if body.get(key) not in (None, ""):
                        opts[key] = body[key]
                result = flows.synthesize(
                    str(body.get("text") or ""), str(body.get("voice_name") or ""), opts
                )
                result["url"] = "/api/outputs/file?name=" + urllib.parse.quote(result["file"])
                return self._json({"ok": True, **result})
            if route == "/api/mine/settings":
                return self._json({"ok": True, "settings": mine.save_settings(self._body_json())})
            if route == "/api/mine/reset":
                return self._json({"ok": True, "settings": mine.reset_settings()})
            if route == "/api/mine/history":
                return self._json({"ok": True, "history": mine.add_history(self._body_json())})
            return self._json({"error": "not found"}, 404)
        except ProviderError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def _already_serving(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def main() -> None:
    if _already_serving(17878) or _already_serving(17879):
        print("声来面板已在运行（本次启动取消，防止多进程僵尸）", file=sys.stderr)
        sys.exit(0)
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=17878)
    args = parser.parse_args()
    port = args.port
    server = None
    for _ in range(50):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    if server is None:
        print("无可用端口", file=sys.stderr)
        sys.exit(1)
    meta = config.data_root() / ".panel.json"
    meta.write_text(json.dumps({"port": port}), encoding="utf-8")
    print(f"voice-studio panel: http://127.0.0.1:{port}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
