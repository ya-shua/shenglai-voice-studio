"""业务流程：音色注册、快速克隆、手动登记、语音合成、翻唱换声（MCP 与面板共用）。"""
from __future__ import annotations

import time
from pathlib import Path

from lib import config, library
from lib.providers import get_provider
from lib.providers.base import ProviderError, audio_data_uri, http_download, poll_until


def enroll_voice(
    voice_name: str,
    provider_id: str | None = None,
    material_file: str | None = None,
    note: str = "",
) -> dict:
    """用已入库素材在供应商侧注册（克隆）音色，并登记到本地音色库。"""
    name = library.sanitize_name(voice_name)
    provider_id = provider_id or "bailian"
    provider = get_provider(provider_id)
    if "enroll" not in provider.capabilities:
        raise ProviderError(
            f"{provider.display_name} 不支持音色注册（能力: {', '.join(provider.capabilities)}）。"
            "如音色已在供应商控制台创建，可用 voice_register_manual 手动登记。"
        )
    material = library.find_material(name, material_file)
    cfg = config.provider_config(provider_id)
    created, status, detail = provider.enroll_and_wait(
        material.read_bytes(),
        material.suffix.lstrip(".").lower(),
        name,
        cfg.get("target_model", ""),
        cfg,
        note=note,
    )
    entry = {
        "name": name,
        "provider": provider_id,
        "voice_id": created["voice_id"],
        "target_model": created.get("target_model", ""),
        "status": status,
        "note": note or "",
        "material_used": material.name,
        "materials": [m["name"] for m in library.list_materials(name)],
    }
    library.upsert_voice(entry)
    if status == "processing":
        entry["notice"] = f"音色仍在云端处理中（{detail}），稍后可直接 voice_tts 试用。"
    return entry


def register_voice_manual(
    voice_name: str, provider_id: str, voice_id: str, target_model: str = "", note: str = ""
) -> dict:
    """手动登记一个已在供应商侧存在的音色（控制台创建 / 自定义供应商固定音色）。"""
    if not (voice_id or "").strip():
        raise ProviderError("voice_id 不能为空")
    provider = get_provider(provider_id)
    entry = {
        "name": library.sanitize_name(voice_name),
        "provider": provider.id,
        "voice_id": voice_id.strip(),
        "target_model": (target_model or "").strip(),
        "status": "ready",
        "note": note or "手动登记",
        "materials": [m["name"] for m in library.list_materials(voice_name)],
    }
    return library.upsert_voice(entry)


def design_voice(
    voice_name: str,
    description: str,
    preview_text: str | None = None,
    provider_id: str = "bailian",
    target_model: str = "",
    language: str = "zh",
    save_preview_material: bool = False,
) -> dict:
    """AI 生成音色（声音设计）：文字描述直接生成音色 ID，无需任何素材。"""
    name = library.sanitize_name(voice_name)
    if not (description or "").strip():
        raise ProviderError("音色描述不能为空（例如：年轻女性，声音清亮干净，语速适中）")
    provider = get_provider(provider_id)
    if "design" not in provider.capabilities:
        raise ProviderError(f"{provider.display_name} 不支持声音设计")
    preview = (preview_text or "").strip() or (
        "你好，欢迎使用声来，这是我由一句文字描述直接生成的声音。"
    )
    cfg = config.provider_config(provider_id)
    result = provider.design(
        description, preview, name, target_model, cfg, language=language
    )
    status, detail = str(result.get("status") or "unknown"), ""
    if "query" in provider.capabilities:
        def step():
            return provider.voice_status(result["voice_id"], cfg)
        def check(st):
            if st["status"] == "ready":
                return True, "ready"
            if st["status"] == "failed":
                return True, "failed"
            return False, st["status"]
        try:
            _, status = poll_until(step, check, 90, 3, "声音设计")
        except ProviderError as e:
            status, detail = "processing", str(e)
    if status == "failed":
        if "delete" in provider.capabilities:
            try:
                provider.delete(result["voice_id"], cfg)
            except Exception:
                pass
        raise ProviderError("生成的音色未通过审核（描述可能含敏感内容），请调整描述后重试")
    preview_path = ""
    if result.get("preview"):
        preview_path = str(library.save_output(name, "wav", result["preview"]))
        if save_preview_material:
            library.save_generated_material(name, "wav", result["preview"])
    entry = {
        "name": name,
        "provider": provider_id,
        "voice_id": result["voice_id"],
        "target_model": result.get("target_model", ""),
        "status": "ready" if status == "ready" else status,
        "note": "AI生成：%s" % description.strip()[:80],
        "design_prompt": result.get("design_prompt", ""),
        "materials": [m["name"] for m in library.list_materials(name)],
    }
    library.upsert_voice(entry)
    entry["preview_path"] = preview_path
    if status == "processing":
        entry["notice"] = f"音色仍在云端部署中（{detail}），稍后可直接合成。"
    return entry


def generate_material(text: str, voice_name: str, source_voice: str,
                      opts: dict | None = None) -> dict:
    """模型生成素材：用已有音色把文本读成音频，直接存为 voice_name 名下的素材。"""
    if not (text or "").strip():
        raise ProviderError("生成文本不能为空")
    src = library.get_voice(source_voice)
    if not src:
        raise ProviderError(
            f"源音色「{library.sanitize_name(source_voice)}」未登记。"
            "先登记官方音色或注册一个音色，再用它来生成素材"
        )
    provider_id = src.get("provider", "bailian")
    provider = get_provider(provider_id)
    if "tts" not in provider.capabilities:
        raise ProviderError(f"{provider.display_name} 不支持语音合成")
    data, ext = provider.tts(
        text,
        src["voice_id"],
        src.get("target_model", ""),
        opts or {},
        config.provider_config(provider_id),
        voice_meta=src,
    )
    name = library.sanitize_name(voice_name)
    path = library.save_generated_material(name, ext, data)
    return {
        "voice": name,
        "source": src["name"],
        "material": path.name,
        "path": str(path),
        "size": len(data),
    }


def mimo_synthesize(mode: str, text: str, style: str = "", voice: str = "",
                    voice_prompt: str = "", reference_audio_path: str = "",
                    reference_data_uri: str = "") -> dict:
    """小米 MiMo 三模式直接合成：builtin（内置音色）/ design（描述生音色）/ clone（参考音频复刻）。

    参考音频传路径或 data URL 均可；这是"一句话克隆"的云端原生形态，无需任何注册流程。
    """
    provider = get_provider("mimo")
    cfg = config.provider_config("mimo")
    ref_uri = (reference_data_uri or "").strip()
    if mode == "clone" and not ref_uri:
        p = Path(reference_audio_path or "")
        if not p.is_file():
            raise ProviderError(f"参考音频不存在: {p}")
        if p.suffix.lower() not in (".mp3", ".wav"):
            raise ProviderError("参考音频仅支持 mp3/wav")
        if p.stat().st_size > 7_500_000:
            raise ProviderError("参考音频太大（base64 后需 ≤10MB），请剪到 30 秒内")
        ref_uri = audio_data_uri(p.read_bytes(), p.suffix.lstrip("."))
    data = provider.synthesize_mode(
        mode, text, style=style, voice=voice, voice_prompt=voice_prompt,
        ref_data_uri=ref_uri, cfg=cfg,
    )
    names = {
        "builtin": f"MiMo_{(voice or 'mimo_default').strip() or 'default'}",
        "design": "MiMo_设计音色",
        "clone": "MiMo_克隆",
    }
    path = library.save_output(names.get(mode, "MiMo"), "wav", data)
    return {"mode": mode, "file": path.name, "path": str(path), "size": len(data)}


def hall_voices() -> list:
    """声音大厅：聚合各家官方免费音色目录（带分类标签）。未接入的供应商自动跳过。"""
    out = []
    for pid in ("mimo", "bailian", "siliconflow", "elevenlabs"):
        try:
            p = get_provider(pid)
            if "catalog" not in p.capabilities:
                continue
            items = p.catalog(config.provider_config(pid))
        except ProviderError:
            continue  # 未配置 Key 或目录暂不可用：大厅里不展示该来源
        for it in items:
            vid = it.get("voice_id")
            configured = bool(str(config.provider_config(pid).get("api_key", "")).strip())
            demo = None
            if not configured:
                try:
                    from lib import preview_audio
                    demo = preview_audio.official_demo(pid, vid)
                except Exception:
                    demo = None
            out.append({
                "provider": pid,
                "provider_name": p.display_name,
                "voice_id": vid,
                "name": it.get("name", ""),
                "tags": it.get("tags", []),
                "target_model": it.get("target_model", ""),
                "official_demo": bool(demo),
                "free_preview": configured or bool(demo),
            })
    return out


def preview_voice(provider_id: str, voice_id: str, target_model: str = "", text: str = "") -> dict:
    """大厅试听：缓存优先（同一音色+文字只合成一次）；
    已接入 → 自定义文字合成；未接入 → 回放官方样音（免费无需 Key）。"""
    provider = get_provider(provider_id)
    if "tts" not in provider.capabilities:
        raise ProviderError(f"{provider.display_name} 不支持合成，无法试听")
    cfg = config.provider_config(provider_id)
    from lib import preview_store
    text = (text or "").strip() or preview_store.DEFAULT_PREVIEW_TEXT
    cached = preview_store.get(provider_id, voice_id, text)
    if cached:
        return {"file": cached.name, "path": str(cached), "size": cached.stat().st_size,
                "cached": True}
    configured = True
    try:
        provider.validate_config(cfg)
    except ProviderError:
        configured = False
    if not configured:
        from lib import preview_audio
        demo = preview_audio.official_demo(provider_id, voice_id)
        if demo:
            from lib.providers.base import http_download
            data = http_download(demo[0], timeout=60)
            path = preview_store.put(provider_id, voice_id, text, data, ext="mp3")
            return {"file": path.name, "path": str(path), "size": len(data),
                    "official_demo": True}
    data, ext = provider.tts(
        (text or "").strip() or "你好，我是你的专属声音，很高兴为你朗读这段话。",
        voice_id,
        target_model,
        {},
        cfg,
    )
    path = preview_store.put(provider_id, voice_id, text, data, ext=ext)
    return {"file": path.name, "path": str(path), "size": len(data)}


def universal_clone(provider_id: str, text: str, style: str = "",
                    reference_audio_path: str = "", reference_data_uri: str = "",
                    keep: bool = False) -> dict:
    """通用音色克隆：任何支持克隆的模型都能用同一个入口。

    - mimo：参考音频内联直传，一次请求出声
    - bailian / fish / siliconflow / elevenlabs：自动「临时注册音色 → 合成 → 清理」
    """
    provider = get_provider(provider_id)
    if provider_id == "mimo":
        return mimo_synthesize(
            "clone", text, style=style,
            reference_audio_path=reference_audio_path,
            reference_data_uri=reference_data_uri,
        )
    if provider_id == "kits":
        raise ProviderError("Kits.AI 走唱歌训练线：请在 kits.ai 网页端训练后到「翻唱」页使用")
    if "enroll" not in provider.capabilities or "tts" not in provider.capabilities:
        raise ProviderError(f"{provider.display_name} 不支持音色克隆")

    src = Path(reference_audio_path or "")
    tmp = None
    if not src.is_file():
        if not reference_data_uri.startswith("data:audio/"):
            raise ProviderError("需要参考音频（文件路径或 data URL，mp3/wav）")
        import base64 as _b64
        head, b64 = reference_data_uri.split(",", 1)
        ext = "mp3" if "mpeg" in head else "wav"
        tmp = config.data_root() / "materials" / "_incoming" / f"ref_{int(time.time()*1000)}.{ext}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(_b64.b64decode(b64))
        src = tmp
    if src.suffix.lower() not in (".mp3", ".wav", ".m4a"):
        raise ProviderError(f"参考音频格式 {src.suffix} 不支持（mp3/wav/m4a）")
    try:
        result = quick_clone(str(src), text, provider_id=provider_id, keep_voice=keep)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return {"mode": f"clone:{provider_id}", "provider_name": provider.display_name, **result}


def warm_previews(provider_id: str, limit: int = 12) -> int:
    """后台预热：为某模型的全部目录音色合成默认试听（已有缓存的跳过）。返回新合成数。"""
    provider = get_provider(provider_id)
    if "tts" not in provider.capabilities or "catalog" not in provider.capabilities:
        return 0
    cfg = config.provider_config(provider_id)
    try:
        provider.validate_config(cfg)
    except ProviderError:
        raise
    from lib import preview_store
    items = provider.catalog(cfg)[:limit]
    n = 0
    for it in items:
        vid = it.get("voice_id")
        if preview_store.has_default(provider_id, vid):
            continue
        try:
            data, ext = provider.tts(
                preview_store.DEFAULT_PREVIEW_TEXT, vid,
                it.get("target_model", ""), {}, cfg)
            preview_store.put(provider_id, vid, preview_store.DEFAULT_PREVIEW_TEXT, data, ext=ext)
            n += 1
        except Exception:
            continue
    return n


def _kits_voice(voice_name: str) -> dict:
    return _voice_for_engine(voice_name, "kits")


def _voice_for_engine(voice_name: str, engine: str) -> dict:
    """取指定引擎可用的音色（kits=云端付费 / local-svc=本地免费）。"""
    voice = library.get_voice(voice_name)
    if not voice:
        raise ProviderError(f"音色「{library.sanitize_name(voice_name)}」未登记")
    want = "local-svc" if engine == "local-svc" else "kits"
    if voice.get("provider") != want:
        label = "本地 Seed-VC" if want == "local-svc" else "Kits.AI"
        raise ProviderError(
            f"{label} 音色才能用于这个引擎；「{voice['name']}」是 {voice.get('provider')} 音色"
        )
    return voice


def convert_vocal(audio_path: str, voice_name: str, strength: float = 0.8,
                  pitch_shift: int = 0, engine: str = "kits") -> dict:
    """把一段干声（人声）换成指定音色的声音：Kits.AI 云端，或本地 Seed-VC（免费）。"""
    voice = _voice_for_engine(voice_name, engine)
    src = Path(audio_path or "")
    if not src.is_file():
        raise ProviderError(f"音频文件不存在: {src}")
    if src.suffix.lower() not in {".wav", ".mp3", ".flac"}:
        raise ProviderError("换声输入支持 wav/mp3/flac")
    if engine == "local-svc":
        provider = get_provider("local-svc")
        cfg = config.provider_config("local-svc")
        result = provider.convert(
            src.read_bytes(), src.name, voice["voice_id"], cfg,
            strength=strength, pitch_shift=pitch_shift,
        )
        ext = "wav"
    else:
        provider = get_provider("kits")
        cfg = config.provider_config("kits")
        result = provider.convert(
            src.read_bytes(), src.name, voice["voice_id"], cfg,
            strength=strength, pitch_shift=pitch_shift,
        )
        ext = _url_ext(result["url"], "wav")
    path = library.save_output(f"{voice['name']}_换声", ext, result["audio"])
    return {"voice": voice["name"], "path": str(path), "size": len(result["audio"])}


def sing_cover(song_path: str, voice_name: str, strength: float = 0.8,
               pitch_shift: int = 0, engine: str = "kits") -> dict:
    """稳定翻唱流水线：歌曲 → 人声/伴奏分离 → 人声换声 → 混回伴奏 → 成品。

    「换声只对干声做」是稳定度的关键：伴奏全程不动，最后才拼回去。
    engine=local-svc 时走本地 demucs + Seed-VC，全程免费（慢一些）。
    """
    from lib import audiomix

    if engine == "local-svc":
        return _sing_cover_local(song_path, voice_name, strength, pitch_shift)

    voice = _kits_voice(voice_name)
    song = Path(song_path or "")
    if not song.is_file():
        raise ProviderError(f"歌曲文件不存在: {song}")
    if song.suffix.lower() not in {".wav", ".mp3", ".flac", ".webm"}:
        raise ProviderError("歌曲格式支持 wav/mp3/flac/webm（≤50MB）")
    kits = get_provider("kits")
    cfg = config.provider_config("kits")
    # 1. 人声/伴奏分离
    sep = kits.separate(song.read_bytes(), song.name, cfg)
    vocal_path = library.save_output(
        f"{voice['name']}_原曲人声", audiomix._url_ext(sep["vocal_url"]),
        http_download(sep["vocal_url"], timeout=300),
    )
    backing_path = None
    if sep.get("backing_url"):
        backing_path = library.save_output(
            f"{voice['name']}_原曲伴奏", audiomix._url_ext(sep["backing_url"], "mp3"),
            http_download(sep["backing_url"], timeout=300),
        )
    # 2. 人声换声（保持音高与节奏，只换音色）
    conv = kits.convert(
        vocal_path.read_bytes(), vocal_path.name, voice["voice_id"], cfg,
        strength=strength, pitch_shift=pitch_shift,
    )
    conv_ext = audiomix._url_ext(conv["url"], "wav")
    converted_path = library.save_output(f"{voice['name']}_换声干声", conv_ext, conv["audio"])
    # 3. 混回伴奏
    final_path, mix_method = "", "未混音"
    if backing_path:
        out = library.save_output(
            f"{voice['name']}_翻唱成品", conv_ext if conv_ext == backing_path.suffix.lstrip(".") else backing_path.suffix.lstrip("."), b""
        )
        mix = audiomix.mix_audio(converted_path, backing_path, out)
        final_path, mix_method = mix["output"], mix["method"]
    return {
        "voice": voice["name"],
        "song": song.name,
        "vocal": str(vocal_path),
        "backing": str(backing_path) if backing_path else "",
        "converted": str(converted_path),
        "final": final_path,
        "mix_method": mix_method,
    }


def _sing_cover_local(song_path: str, voice_name: str, strength: float = 0.8,
                      pitch_shift: int = 0) -> dict:
    """本地免费翻唱：demucs 分离 → Seed-VC 换声 → 混回伴奏。"""
    from lib import audiomix

    voice = _voice_for_engine(voice_name, "local-svc")
    song = Path(song_path or "")
    if not song.is_file():
        raise ProviderError(f"歌曲文件不存在: {song}")
    provider = get_provider("local-svc")
    cfg = config.provider_config("local-svc")
    # 1. 分离（本地 demucs）
    sep = provider.separate(song.read_bytes(), song.name, cfg)
    vocal_path = library.save_output(f"{voice['name']}_原曲人声", "wav", sep["vocal"])
    backing_path = library.save_output(f"{voice['name']}_原曲伴奏", "wav", sep["backing"])
    # 2. 换声（Seed-VC，参考音频来自音色的 voice_id）
    conv = provider.convert(
        vocal_path.read_bytes(), vocal_path.name, voice["voice_id"], cfg,
        strength=strength, pitch_shift=pitch_shift,
    )
    converted_path = library.save_output(f"{voice['name']}_换声干声", "wav", conv["audio"])
    # 3. 对齐到伴奏（采样率/声道/长度），再混回伴奏
    aligned_path = converted_path.with_name(converted_path.stem + "_aligned.wav")
    provider.align(converted_path, backing_path, aligned_path, cfg)
    out = library.save_output(f"{voice['name']}_翻唱成品", "wav", b"")
    mix = audiomix.mix_audio(aligned_path, backing_path, out)
    return {
        "voice": voice["name"],
        "song": song.name,
        "vocal": str(vocal_path),
        "backing": str(backing_path),
        "converted": str(converted_path),
        "final": mix["output"],
        "mix_method": mix["method"],
    }


def synthesize(text: str, voice_name: str, opts: dict | None = None) -> dict:
    """用已注册音色合成语音，产出文件写入 outputs/ 并返回路径。"""
    if not (text or "").strip():
        raise ProviderError("合成文本不能为空")
    name = library.sanitize_name(voice_name)
    voice = library.get_voice(name)
    if not voice:
        raise ProviderError(
            f"音色「{name}」未注册。先用 voice_enroll 注册，或用 voice_library 查看已有音色。"
        )
    provider_id = voice.get("provider", "bailian")
    provider = get_provider(provider_id)
    if "tts" not in provider.capabilities:
        raise ProviderError(f"{provider.display_name} 不支持语音合成")
    data, ext = provider.tts(
        text,
        voice["voice_id"],
        voice.get("target_model", ""),
        opts or {},
        config.provider_config(provider_id),
        voice_meta=voice,
    )
    path = library.save_output(name, ext, data)
    return {
        "voice": name,
        "file": path.name,
        "path": str(path),
        "size": len(data),
        "ext": ext,
    }


def quick_clone(
    audio_path: str,
    text: str,
    provider_id: str = "bailian",
    voice_name: str | None = None,
    keep_voice: bool = False,
    opts: dict | None = None,
) -> dict:
    """一句话快速克隆：单段素材 → 临时注册音色 → 立即合成 →（默认）用后即弃。

    keep_voice=True 时把音色连同素材正式登记进音色库（此时必须给 voice_name）。
    """
    src = Path(audio_path or "")
    if not src.is_file():
        raise ProviderError(f"音频文件不存在: {src}")
    ext = src.suffix.lstrip(".").lower()
    if ext not in {"wav", "mp3", "m4a"}:
        raise ProviderError(f"不支持的格式 .{ext}（支持 wav/mp3/m4a）")
    if ext == "wav":
        try:
            import wave
            with wave.open(str(src), "rb") as w:
                dur = w.getnframes() / max(w.getframerate(), 1)
            if dur < 5:
                raise ProviderError(
                    f"音频只有 {dur:.1f} 秒，太短了：请给 ≥10 秒（10~20 秒最佳）的清晰人声"
                )
        except wave.Error:
            pass  # 非标准 wav 头交给服务端校验
    if not (text or "").strip():
        raise ProviderError("要合成的文本不能为空")
    if keep_voice and not (voice_name or "").strip():
        raise ProviderError("保留音色时必须给 voice_name")
    provider = get_provider(provider_id)
    if "enroll" not in provider.capabilities or "tts" not in provider.capabilities:
        raise ProviderError(
            f"{provider.display_name} 不支持快速克隆（需要同时具备注册与合成能力）"
        )
    name = library.sanitize_name(voice_name or ("quick_" + time.strftime("%H%M%S")))
    cfg = config.provider_config(provider_id)
    created, status, detail = provider.enroll_and_wait(
        src.read_bytes(), ext, name, cfg.get("target_model", ""), cfg
    )
    voice_id = created["voice_id"]
    try:
        data, out_ext = provider.tts(
            text, voice_id, created.get("target_model", ""), opts or {}, cfg
        )
    finally:
        if not keep_voice and "delete" in provider.capabilities:
            try:
                provider.delete(voice_id, cfg)
            except Exception:
                pass  # 临时音色清理失败不影响本次结果
    path = library.save_output(name, out_ext, data)
    result = {
        "voice": name,
        "voice_id": voice_id,
        "kept": keep_voice,
        "status": status,
        "file": path.name,
        "path": str(path),
        "size": len(data),
        "ext": out_ext,
    }
    if keep_voice:
        library.add_material(name, src)
        library.upsert_voice(
            {
                "name": name,
                "provider": provider_id,
                "voice_id": voice_id,
                "target_model": created.get("target_model", ""),
                "status": "ready",
                "note": "快速克隆保留",
                "materials": [m["name"] for m in library.list_materials(name)],
            }
        )
    if status == "processing":
        result["notice"] = f"音色仍在云端处理中（{detail}）。"
    return result


def delete_voice(name: str, also_cloud: bool = False) -> dict:
    """删除本地音色登记；also_cloud 时连同供应商侧音色一起释放。"""
    voice = library.get_voice(name)
    if not voice:
        raise ProviderError(f"音色「{library.sanitize_name(name)}」不存在")
    cloud_msg = ""
    if also_cloud and voice.get("voice_id"):
        provider = get_provider(voice.get("provider", "bailian"))
        if "delete" in provider.capabilities:
            try:
                provider.delete(voice["voice_id"], config.provider_config(voice.get("provider", "bailian")))
                cloud_msg = "，供应商侧音色已释放"
            except ProviderError as e:
                cloud_msg = f"，云端释放失败（本地已删除）：{e}"
        else:
            cloud_msg = "（该供应商不支持云端删除，仅删除了本地登记）"
    library.remove_voice(name)
    return {"deleted": library.sanitize_name(name), "cloud": cloud_msg}
