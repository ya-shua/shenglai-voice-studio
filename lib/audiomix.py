"""音频混音工具（翻唱合成用）：wav 纯标准库混音；格式不支持时回退 ffmpeg（若本机有）。

这不是本地模型部署——只是把换声后的人声与伴奏拼回一首歌的文件处理。
"""
from __future__ import annotations

import shutil
import struct
import wave
from pathlib import Path

from lib.providers.base import ProviderError


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _url_ext(url: str, default: str = "wav") -> str:
    tail = str(url).split("?")[0].rsplit(".", 1)
    return tail[1].lower()[:5] if len(tail) == 2 and 1 <= len(tail[1]) <= 5 else default


def _mix_wav(vocal: Path, backing: Path, out: Path) -> None:
    """两个参数完全一致的 wav 直接逐样本相加（限幅）。"""
    with wave.open(str(vocal), "rb") as v, wave.open(str(backing), "rb") as b:
        if (v.getframerate(), v.getnchannels(), v.getsampwidth()) != (
            b.getframerate(), b.getnchannels(), b.getsampwidth()
        ):
            raise ValueError("wav 参数不一致")
        rate, ch, sw = v.getframerate(), v.getnchannels(), v.getsampwidth()
        if sw != 2:
            raise ValueError("仅支持 16-bit wav 混音")
        vd, bd = v.readframes(v.getnframes()), b.readframes(b.getnframes())
    n = max(len(vd), len(bd))
    vd += b"\x00" * (n - len(vd))
    bd += b"\x00" * (n - len(bd))
    mixed = bytearray()
    for i in range(0, n, 2):
        s = struct.unpack_from("<h", vd, i)[0] + struct.unpack_from("<h", bd, i)[0]
        mixed += struct.pack("<h", max(-32768, min(32767, s)))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(sw)
        w.setframerate(rate)
        w.writeframes(bytes(mixed))


def mix_audio(vocal: Path, backing: Path, out: Path) -> dict:
    """混音：优先 ffmpeg（任意格式），否则纯 wav 混音；都不行给出清晰指引。"""
    vocal, backing, out = Path(vocal), Path(backing), Path(out)
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(vocal), "-i", str(backing),
             "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0",
             str(out)],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode == 0 and out.is_file():
            return {"method": "ffmpeg", "output": str(out)}
        raise ProviderError(f"ffmpeg 混音失败: {proc.stderr[-300:]}")
    if vocal.suffix.lower() == ".wav" and backing.suffix.lower() == ".wav":
        try:
            _mix_wav(vocal, backing, out)
            return {"method": "wav", "output": str(out)}
        except (ValueError, wave.Error) as e:
            raise ProviderError(
                f"wav 直混失败（{e}）。安装 ffmpeg 后重试，或用任意音频软件把 "
                f"{vocal.name} 与 {backing.name} 合成（人声轨 + 伴奏轨）"
            ) from None
    raise ProviderError(
        "混音需要 ffmpeg（处理非 wav 格式）。请安装 ffmpeg 后重试；"
        f"也可以手动混音：人声 {vocal.name} + 伴奏 {backing.name}"
    )
