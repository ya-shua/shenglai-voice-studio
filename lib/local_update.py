# -*- coding: utf-8 -*-
"""更新检查与一键更新：对比 GitHub 最新 Release 与本地版本。

- /api/update-check：拉 releases/latest（10 分钟缓存，失败不影响面板），对比 semver。
- /api/update：git fetch + checkout 最新 tag（fast-forward 语义），成功后调度
  「延迟重启面板」——旧进程退出 3 秒后由独立中转进程拉起新面板（避免端口争抢）。
- 均在后台线程/子进程执行，不阻塞面板主循环。
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from lib import config

REPO = "ya-shua/shenglai-voice-studio"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_CHECK_CACHE: dict = {}
_CHECK_TTL = 600  # 10 分钟

ROOT = Path(__file__).resolve().parents[1]


def _local_version() -> str:
    try:
        return str(config.VERSION)
    except Exception:
        return ""


def _parse_semver(v: str):
    m = [int(x) for x in v.strip().lstrip("vV.").split(".") if x.isdigit()]
    while len(m) < 3:
        m.append(0)
    return m[:3]


def _newer(remote: str, local: str) -> bool:
    try:
        return _parse_semver(remote) > _parse_semver(local)
    except Exception:
        return False


def check(force: bool = False) -> dict:
    local = _local_version()
    hit = _CHECK_CACHE.get("v")
    if hit and not force and time.time() - hit[0] < _CHECK_TTL:
        return {**hit[1], "local": local, "cached": True}
    import urllib.request
    try:
        req = urllib.request.Request(RELEASES_API, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "shenglai-panel",
        })
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        tag = str(data.get("tag_name") or "").lstrip("v")
        out = {"has_update": _newer(tag, local), "latest": tag,
               "notes": str(data.get("body") or "")[:400],
               "url": data.get("html_url") or f"https://github.com/{REPO}/releases/latest"}
    except Exception as e:
        # 网络不通/限流：静默降级，绝不影响面板使用
        out = {"has_update": False, "latest": "", "error": str(e)[:120]}
    _CHECK_CACHE["v"] = (time.time(), out)
    return {**out, "local": local}


def do_update() -> dict:
    """一键更新：fetch 最新 tag → 强制检出 → 调度延迟重启。"""
    local = _local_version()
    info = check(force=True)
    tag = info.get("latest") or ""
    if not tag:
        return {"ok": False, "error": "无法获取远端版本（网络或限流），请稍后重试"}
    if not _newer(tag, local):
        return {"ok": True, "updated": False, "message": f"已是最新版本 v{local}"}
    full = f"v{tag}" if not tag.startswith("v") else tag

    def run(cmd, timeout=120):
        return subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                              text=True, timeout=timeout)

    r = run(["git", "fetch", "origin", "--tags"])
    if r.returncode != 0:
        return {"ok": False, "error": f"git fetch 失败: {r.stderr[:200]}"}
    r = run(["git", "checkout", "-f", full])
    if r.returncode != 0:
        return {"ok": False, "error": f"切到 {full} 失败: {r.stderr[:200]}"}

    # 调度延迟重启：本进程 2.5 秒后退出，中转进程随后拉起新面板
    import os
    import sys
    python = sys.executable or "pythonw"
    relay = (
        'timeout /t 3 /nobreak >nul\r\n'
        f'cd /d "{ROOT}"\r\n'
        f'start "" "{python}" panel\\server.py --port 17878\r\n'
    )
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["cmd", "/c", relay], creationflags=flags, close_fds=True)
    threading.Timer(1.2, lambda: os._exit(0))
    return {"ok": True, "updated": True, "tag": full,
            "message": f"已更新到 {full}，面板重启中…页面将在几秒后自动恢复"}
