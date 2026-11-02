"""本地 Seed-VC 适配器：免费的零样本换声 / 歌声转换。

需要本机部署一份 Seed-VC（https://github.com/Plachtaa/seed-vc，约 2~3GB）：
- 参考音频只要 1~30 秒，不需要训练，直接就能换声
- 唱歌转换要开 f0 条件（本适配器默认开）
- CPU 也能跑（关掉 fp16），有 N 卡会快很多

音色约定：voice_id 填参考音频的绝对路径（或以 `seedvc:` 前缀开头），
例如 `seedvc:D:\\AI\\声音工坊\\materials\\小明\\ref.wav`。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from lib.providers.base import Provider, ProviderError


class LocalSeedVCProvider(Provider):
    id = "local-svc"
    display_name = "本地 Seed-VC（免费换声）"
    capabilities = ("convert", "separate")
    config_schema = (
        {
            "key": "svc_dir",
            "label": "Seed-VC 目录",
            "required": True,
            "secret": False,
            "placeholder": r"D:\AI\Models\seed-vc",
            "help": "本机 Seed-VC 的安装目录（里面有 inference.py）",
        },
        {
            "key": "python_exe",
            "label": "Python 解释器（可留空）",
            "required": False,
            "secret": False,
            "placeholder": r"D:\AI\Models\seed-vc\.venv311\Scripts\python.exe",
            "help": "留空会自动找 .venv311 / .venv 里的 python",
        },
        {
            "key": "steps",
            "label": "扩散步数（越小越快）",
            "required": False,
            "secret": False,
            "placeholder": "25",
            "help": "默认 25；CPU 上可以降到 10~15 换速度",
        },
        {
            "key": "hf_endpoint",
            "label": "模型下载源",
            "required": False,
            "secret": False,
            "placeholder": "https://hf-mirror.com",
            "help": "国内访问 huggingface 不通时用镜像（默认已填）",
        },
        {
            "key": "timeout",
            "label": "超时秒数",
            "required": False,
            "secret": False,
            "placeholder": "1800",
        },
    )

    def _root(self, cfg: dict) -> Path:
        d = str(cfg.get("svc_dir", "")).strip()
        if not d:
            raise ProviderError("还没填 Seed-VC 目录（设置 → 本地 Seed-VC）")
        root = Path(d)
        if not (root / "inference.py").is_file():
            raise ProviderError(f"Seed-VC 目录里没有 inference.py: {root}")
        return root

    def _python(self, cfg: dict, root: Path) -> Path:
        p = str(cfg.get("python_exe", "")).strip()
        if p and Path(p).is_file():
            return Path(p)
        for cand in (
            root / ".venv311" / "Scripts" / "python.exe",
            root / ".venv" / "Scripts" / "python.exe",
        ):
            if cand.is_file():
                return cand
        raise ProviderError("找不到 Seed-VC 的 Python 环境，请先跑一次安装")

    @staticmethod
    def _resolve_ref(voice_id: str) -> Path:
        v = str(voice_id or "").strip()
        if v.startswith("seedvc:"):
            v = v[len("seedvc:"):]
        if not v:
            raise ProviderError("本地换声需要参考音频路径（音色的 voice_id 填 ref 音频）")
        p = Path(v)
        if not p.is_file():
            raise ProviderError(f"参考音频不存在: {p}")
        return p

    @staticmethod
    def _to_pcm16(py: Path, src: Path, dst: Path) -> Path:
        """Seed-VC/demucs 输出的是 float32 wav，插件的纯 stdlib 混音器只认 PCM16。"""
        script = (
            "import sys, soundfile as sf\n"
            "d, sr = sf.read(sys.argv[1])\n"
            "sf.write(sys.argv[2], d, sr, subtype='PCM_16')\n"
        )
        proc = subprocess.run(
            [str(py), "-c", script, str(src), str(dst)],
            capture_output=True, timeout=300,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).decode("utf-8", "replace")[-500:]
            raise ProviderError(f"音频转码失败: {err}")
        return dst

    def convert(self, data: bytes, filename: str, voice_id: str, cfg: dict,
                strength: float = 0.8, pitch_shift: int = 0) -> dict:
        self.validate_config(cfg)
        root = self._root(cfg)
        py = self._python(cfg, root)
        ref = self._resolve_ref(voice_id)
        steps = int(cfg.get("steps") or 25)
        timeout = int(cfg.get("timeout") or 1800)
        env = dict(os.environ)
        env["HF_ENDPOINT"] = str(cfg.get("hf_endpoint") or "https://hf-mirror.com").strip()
        env["PYTHONIOENCODING"] = "utf-8"
        # 外部环境里的离线开关会让 Seed-VC 找不到已下载的模型，必须清掉
        env.pop("HF_HUB_OFFLINE", None)
        with tempfile.TemporaryDirectory(prefix="svc_") as td:
            work = Path(td)
            src = work / "source.wav"
            src.write_bytes(data)
            outdir = work / "out"
            cmd = [
                str(py), "inference.py",
                "--source", str(src),
                "--target", str(ref),
                "--output", str(outdir),
                "--f0-condition", "True",
                "--auto-f0-adjust", "True",
                "--diffusion-steps", str(steps),
                "--fp16", "False",
            ]
            if pitch_shift:
                cmd += ["--semi-tone-shift", str(int(pitch_shift))]
            try:
                proc = subprocess.run(
                    cmd, cwd=str(root), env=env, capture_output=True, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                raise ProviderError(
                    f"本地换声超时（>{timeout}s）：调小扩散步数，或用短一点的音频"
                ) from None
            except OSError as e:
                raise ProviderError(f"启动 Seed-VC 失败: {e}") from None
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout).decode("utf-8", "replace")[-800:]
                raise ProviderError(f"Seed-VC 执行失败: {err}")
            outs = sorted(outdir.glob("vc_*.wav"), key=lambda p: p.stat().st_mtime)
            if not outs:
                raise ProviderError("Seed-VC 没有产出音频（检查控制台输出）")
            pcm = self._to_pcm16(py, outs[-1], work / "converted_pcm16.wav")
            audio = pcm.read_bytes()
        return {"audio": audio, "url": ""}

    _ALIGN_SCRIPT = r"""
import sys
from math import gcd
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

vocal_path, backing_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
v, vsr = sf.read(vocal_path, always_2d=True)
b, bsr = sf.read(backing_path, always_2d=True)
# 声道对齐：单声道补成伴奏的声道数
if v.shape[1] != b.shape[1]:
    if v.shape[1] == 1:
        v = np.repeat(v, b.shape[1], axis=1)
    elif b.shape[1] == 1:
        b = np.repeat(b, v.shape[1], axis=1)
# 采样率对齐
if vsr != bsr:
    g = gcd(int(vsr), int(bsr))
    v = resample_poly(v, int(bsr // g), int(vsr // g), axis=0)
# 长度对齐到伴奏
n = b.shape[0]
if v.shape[0] < n:
    v = np.pad(v, ((0, n - v.shape[0]), (0, 0)))
else:
    v = v[:n]
sf.write(out_path, v, int(bsr), subtype="PCM_16")
"""

    def align(self, vocal_path: Path, backing_path: Path, out_path: Path, cfg: dict) -> Path:
        """把换声干声对齐到伴奏的采样率/声道/长度，供纯 stdlib 混音器使用。"""
        root = self._root(cfg)
        py = self._python(cfg, root)
        proc = subprocess.run(
            [str(py), "-c", self._ALIGN_SCRIPT, str(vocal_path), str(backing_path), str(out_path)],
            capture_output=True, timeout=300,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).decode("utf-8", "replace")[-500:]
            raise ProviderError(f"音轨对齐失败: {err}")
        return out_path

    def separate(self, data: bytes, filename: str, cfg: dict) -> dict:
        """人声/伴奏分离（本地 demucs，免费）。"""
        self.validate_config(cfg)
        root = self._root(cfg)
        py = self._python(cfg, root)
        timeout = int(cfg.get("timeout") or 1800)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("HF_HUB_OFFLINE", None)
        with tempfile.TemporaryDirectory(prefix="sep_") as td:
            work = Path(td)
            src = work / "input.wav"
            src.write_bytes(data)
            outdir = work / "out"
            cmd = [
                str(py), "-m", "demucs", "--two-stems", "vocals",
                "-n", "htdemucs", "-o", str(outdir), str(src),
            ]
            try:
                proc = subprocess.run(
                    cmd, cwd=str(root), env=env, capture_output=True, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                raise ProviderError(f"本地人声分离超时（>{timeout}s）") from None
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout).decode("utf-8", "replace")[-800:]
                raise ProviderError(f"demucs 分离失败: {err}")
            base = outdir / "htdemucs" / "input"
            vocal, backing = base / "vocals.wav", base / "no_vocals.wav"
            if not vocal.is_file() or not backing.is_file():
                raise ProviderError("demucs 没有产出人声/伴奏文件")
            vocal = self._to_pcm16(py, vocal, work / "vocals_pcm16.wav")
            backing = self._to_pcm16(py, backing, work / "backing_pcm16.wav")
            return {"vocal": vocal.read_bytes(), "backing": backing.read_bytes()}