"""声来启动器：双击桌面「声来」即可，不需要任何命令行窗口。

行为：
- 面板已在运行（健康检查通过）→ 直接打开浏览器，自己退出
- 未运行 → 用 pythonw 在后台启动面板服务（**无控制台窗口**）→ 等就绪 → 打开浏览器 → 自己退出
- 想停掉面板：点页面右上角的「⏻ 关闭」，或再运行一次本文件加 --stop

日志写在数据目录的 panel.log（出问题时看这个）。

用法：pythonw panel/launch.py [--no-browser|--stop]
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
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


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


def _healthy(port: int, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as r:
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


def _running_port() -> int:
    for port in (_meta_port(), PREFERRED_PORT):
        if port and _healthy(port):
            return port
    return 0


def _pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.is_file() else exe)


def _log_path() -> Path:
    root = _data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "panel.log"


def main() -> None:
    no_browser = "--no-browser" in sys.argv

    if "--stop" in sys.argv:
        port = _running_port()
        if not port:
            print("面板没有在运行")
            return
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", method="POST")
        try:
            urllib.request.urlopen(req, timeout=3).read()
            print("已通知面板关闭")
        except OSError:
            print("关闭请求失败（可能已经退出）")
        return

    # 1) 已在运行：直接开浏览器
    port = _running_port()
    if port:
        if not no_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return

    # 2) 后台启动（无窗口），然后开浏览器
    log = open(_log_path(), "ab")
    try:
        subprocess.Popen(
            [str(_pythonw()), "-u", str(PLUGIN_ROOT / "panel" / "server.py"),
             "--port", str(PREFERRED_PORT)],
            cwd=str(PLUGIN_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    finally:
        log.close()

    ready = 0
    for _ in range(120):  # 最多等 24 秒
        port = _meta_port() or PREFERRED_PORT
        if _healthy(port):
            ready = port
            break
        time.sleep(0.2)

    if ready:
        if not no_browser:
            webbrowser.open(f"http://127.0.0.1:{ready}/")
    else:
        print(f"启动失败，详见 {_log_path()}", file=sys.stderr)


if __name__ == "__main__":
    main()