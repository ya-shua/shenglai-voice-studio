"""声来独立启动器：配合「声来面板.bat」双击启动，无需打开 ZCode。

行为：
- 面板已在运行（健康检查通过）→ 直接打开浏览器
- 未运行 → 启动面板服务 → 等待就绪 → 打开浏览器，前台运行（关闭本窗口即停止面板）

用法：python panel/launch.py [--no-browser]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PREFERRED_PORT = 17878


def _data_root() -> Path:
    env = os.environ.get("VOICE_STUDIO_HOME", "").strip()
    if env:
        return Path(env)
    candidate = Path(r"D:\AI\声音工坊")
    try:
        if candidate.parent.is_dir():
            return candidate
    except OSError:
        pass
    return Path.home() / ".voice-studio"


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def _meta_port() -> int:
    """面板启动后会把实际端口写进数据目录的 .panel.json。"""
    try:
        meta = json.loads((_data_root() / ".panel.json").read_text(encoding="utf-8"))
        return int(meta.get("port", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def main() -> None:
    no_browser = "--no-browser" in sys.argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # 1) 已在运行：直接用
    if _healthy(PREFERRED_PORT):
        print(f"声来面板已在运行: http://127.0.0.1:{PREFERRED_PORT}")
        if not no_browser:
            webbrowser.open(f"http://127.0.0.1:{PREFERRED_PORT}/")
        return

    # 2) 启动面板（前台运行，关闭窗口即停止）
    print("正在启动声来面板…")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(PLUGIN_ROOT / "panel" / "server.py"), "--port", str(PREFERRED_PORT)]
    )
    port = 0
    for _ in range(60):  # 最多等 12 秒
        port = _meta_port() or (PREFERRED_PORT if _healthy(PREFERRED_PORT) else 0)
        if port and _healthy(port):
            break
        time.sleep(0.2)
    if port and _healthy(port):
        print(f"✅ 声来面板已启动: http://127.0.0.1:{port}（关闭本窗口即停止面板）")
        if not no_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
    else:
        print("启动失败，请把上方错误信息发给 AI 助手排查")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    main()
