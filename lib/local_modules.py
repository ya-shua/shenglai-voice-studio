# -*- coding: utf-8 -*-
"""本地引擎模块管理器：注册表 + 一键安装管线 + 进度上报。

设计要点：
- 每个模块描述"部署位置 / 算力需求 / 体积"，安装过程分阶段并把百分比写进内存状态；
- 前端轮询 /api/local-modules 画进度条；
- 安装在后台线程跑，面板重启会中断（临时文件保留，重新点安装会续传下载范围外的解压/校验步骤会重来——
  下载本身支持断点：已存在的临时文件按字节数续传）。
- 只用标准库。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from lib import config
from lib.providers.base import ProviderError

# ── 安装进度状态（内存）───────────────────────────────────────────────────────
_PROGRESS: dict = {}
_THREADS: dict = {}
_CANCEL: set = set()

HFMIRROR = "https://hf-mirror.com"
RVC_URL = HFMIRROR + "/lj1995/VoiceConversionWebUI/resolve/main/RVC-beta0717.7z"
RVC_DEFAULT_DIR = Path(r"D:\AI\Models\rvc")


def _rvc_dir() -> Path:
    """RVC 安装目录：config.json 的 local_modules.rvc_dir 可自定义，默认 D:\\AI\\Models\\rvc。"""
    try:
        cfg = json.loads((config.data_root() / "config.json").read_text(encoding="utf-8"))
        d = str((cfg.get("local_modules") or {}).get("rvc_dir", "")).strip()
        if d:
            return Path(d)
    except Exception:
        pass
    return RVC_DEFAULT_DIR


def _rvc_installed_flag() -> bool:
    """RVC 安装完成的判定文件（管线最后一步写入）。"""
    return (_rvc_dir() / ".shenglai-installed").is_file()


def _seedvc_status() -> dict:
    cfg = config.provider_config("local-svc")
    d = Path(str(cfg.get("svc_dir", "")).strip())
    installed = bool(d) and (d / "inference.py").is_file()
    return {
        "installed": installed,
        "dir": str(d) if d else "",
        "detail": f"就绪 · {d}" if installed else "未安装——需手动准备 Seed-VC 目录（见说明）",
    }


def registry() -> list:
    """模块注册表：描述 + 实时状态。"""
    return [
        {
            "id": "seed-vc",
            "name": "Seed-VC 换声引擎",
            "deploy": "本地部署",
            "compute": "CPU 可跑（整曲 3~10 分钟）· NVIDIA 显卡更快 · 零训练",
            "size": "已安装于本机（约 2~4 GB）",
            "desc": "参考音频 10~30 秒直接换声，免费翻唱的主力引擎（含 demucs 分离）。已安装无安装按钮——重装请手动覆盖目录。",
            "dir": _seedvc_status().get("dir", ""),
            **_seedvc_status(),
            "installable": False,  # 手动部署型：面板只做检测与路径配置
        },
        {
            "id": "rvc",
            "name": "RVC 换声引擎",
            "deploy": "本地部署",
            "compute": "推理：CPU 可跑 / NVIDIA 显卡接近实时 · 训练模型需另行准备（本模块只含推理环境）",
            "size": "便携包约 4.8 GB（含内置 Python + 预训练底模；支持断点续传）",
            "desc": "社区标准训练式换声：外部训练好的 .pth 模型放进来即可高音色贴合度换声。",
            "installed": _rvc_installed_flag(),
            "dir": str(_rvc_dir()),
            "installable": True,
        },
    ]


def status_of(module_id: str) -> dict:
    reg = {m["id"]: m for m in registry()}
    base = reg.get(module_id)
    if not base:
        return {"id": module_id, "status": "unknown"}
    prog = dict(_PROGRESS.get(module_id, {}))
    return {**base, **prog, "cancelled": module_id in _CANCEL}


def list_modules() -> list:
    return [status_of(m["id"]) for m in registry()]


# ── 安装管线 ─────────────────────────────────────────────────────────────────

def _set(module_id: str, step: int, total: int, pct: float, detail: str,
         status: str = "running"):
    _PROGRESS[module_id] = {
        "step": step, "total": total, "pct": round(max(0, min(100, pct)), 1),
        "detail": detail, "status": status,
    }


def is_running(module_id: str) -> bool:
    t = _THREADS.get(module_id)
    return bool(t and t.is_alive())


def start_install(module_id: str, dir_override: str = "") -> dict:
    if module_id not in ("rvc",):
        return {"ok": False, "error": "该模块不支持面板内自动安装（手动部署型）"}
    if is_running(module_id):
        return {"ok": False, "error": "已在安装中"}
    # 安装目录可自定义：写入配置，管线里 _rvc_dir() 会读到
    d = str(dir_override or "").strip()
    if d:
        cfgp = config.data_root() / "config.json"
        try:
            cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        cfg.setdefault("local_modules", {})["rvc_dir"] = d
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    _CANCEL.discard(module_id)
    t = threading.Thread(target=_install_rvc, daemon=True)
    _THREADS[module_id] = t
    t.start()
    return {"ok": True, "started": True}


def uninstall(module_id: str) -> dict:
    """一键卸载：删除安装目录 + 判定文件 + 清掉 local_rvc 配置项。"""
    if module_id != "rvc":
        return {"ok": False, "error": "该模块不支持卸载"}
    if is_running(module_id):
        return {"ok": False, "error": "正在安装中——先取消安装再卸载"}
    rd = _rvc_dir()
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)
    cfgp = config.data_root() / "config.json"
    try:
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    changed = False
    if cfg.get("providers", {}).pop("local_rvc", None) is not None:
        changed = True
    if (cfg.get("local_modules") or {}).pop("rvc_dir", None) is not None:
        changed = True
    if changed:
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    _PROGRESS.pop(module_id, None)
    return {"ok": True, "message": f"已卸载并删除 {rd}"}


def cancel_install(module_id: str) -> dict:
    if is_running(module_id):
        _CANCEL.add(module_id)
        _set(module_id, step=0, total=4, pct=0, detail="已请求取消，等待当前分块结束…", status="cancelling")
        return {"ok": True, "cancelling": True}
    return {"ok": False, "error": "没有进行中的安装"}


def _find_7z() -> str:
    """按优先找可用的 7z 解压器（7-Zip 安装版 / PATH 里的 7z）。"""
    cands = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    which = shutil.which("7z") or shutil.which("7za")
    if which:
        cands.append(which)
    for c in cands:
        if Path(c).is_file():
            return c
    return ""


def _install_rvc():
    mid = "rvc"
    try:
        # ── 步骤 1/4：下载便携包（0~70%）──────────────────────────────────
        _set(mid, 1, 4, 0, "连接下载源（hf-mirror）…")
        import urllib.request
        rd = _rvc_dir()
        tmp = rd / "RVC-beta0717.7z"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(RVC_URL, method="GET")
        # 断点续传：已有临时文件则从其大小继续
        done = tmp.stat().st_size if tmp.is_file() else 0
        if done:
            req.add_header("Range", f"bytes={done}-")
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0) + done
            mode = "ab" if done else "wb"
            got = done
            with open(tmp, mode) as f:
                while True:
                    if mid in _CANCEL:
                        _set(mid, 1, 4, got * 70 / max(total, 1), f"已取消（已下载 {got // (1024*1024)} MB，临时文件保留，再次点击安装会续传）", status="cancelled")
                        return
                    chunk = resp.read(1024 * 512)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    pct = 70.0 * got / max(total, 1)
                    _set(mid, 1, 4, pct, f"下载中 {got // (1024*1024)} / {max(total // (1024*1024), 1)} MB")

        # ── 步骤 2/4：解压（70~90%）────────────────────────────────────────
        _set(mid, 2, 4, 70, "寻找解压器…")
        seven = _find_7z()
        if not seven:
            raise RuntimeError(
                "没有找到 7-Zip——请安装 7-Zip（7-zip.org）后重新点安装；"
                "已下载的 3.9 GB 包已保留，不会重新下载"
            )
        _set(mid, 2, 4, 72, f"解压中（{seven}）… 约 3~8 分钟")
        proc = subprocess.run(
            [seven, "x", str(tmp), f"-o{rd}", "-y"],
            capture_output=True, text=True, timeout=3600,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"解压失败：{(proc.stderr or proc.stdout)[-400:]}")
        _set(mid, 2, 4, 90, "解压完成")

        # ── 步骤 3/4：校验 ────────────────────────────────────────────────
        _set(mid, 3, 4, 92, "校验安装内容…")
        runtime = next((p for p in rd.rglob("python.exe")), None)
        if not runtime:
            raise RuntimeError("包里没找到内置 Python（python.exe）——包可能不完整，删除后重新下载")
        _set(mid, 3, 4, 96, f"校验完成：{runtime.parent}")

        # ── 步骤 4/4：登记 ────────────────────────────────────────────────
        _set(mid, 4, 4, 98, "写入配置…")
        cfgp = config.data_root() / "config.json"
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        cfg.setdefault("providers", {})["local_rvc"] = {
            "svc_dir": str(runtime.parent),
            "python_exe": str(runtime),
        }
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        (rd / ".shenglai-installed").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        _set(mid, 4, 4, 100, "安装完成——把训练好的 .pth 放进 models/ 目录即可使用", status="done")
    except Exception as e:
        _set(mid, 0, 4, 0, str(e), status="error")
