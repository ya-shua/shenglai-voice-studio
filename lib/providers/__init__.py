"""供应商注册表：内置云端适配器 + 用户自定义通用适配器。"""
from __future__ import annotations

from lib import config
from lib.providers.base import GenericTTSProvider, Provider, ProviderError
from lib.providers import bailian, elevenlabs, fish, kits, local_svc, minimax, mimo, siliconflow

__all__ = ["get_provider", "list_providers", "Provider", "ProviderError"]

_BUILTIN = ("bailian", "elevenlabs", "fish", "kits", "local-svc", "minimax", "mimo", "siliconflow")


def get_provider(provider_id: str) -> Provider:
    if provider_id == "bailian":
        return bailian.BailianProvider()
    if provider_id == "elevenlabs":
        return elevenlabs.ElevenLabsProvider()
    if provider_id == "fish":
        return fish.FishAudioProvider()
    if provider_id == "kits":
        return kits.KitsAIProvider()
    if provider_id == "local-svc":
        return local_svc.LocalSeedVCProvider()
    if provider_id == "minimax":
        return minimax.MiniMaxProvider()
    if provider_id == "mimo":
        return mimo.MiMoProvider()
    if provider_id == "siliconflow":
        return siliconflow.SiliconFlowProvider()
    if provider_id.startswith("custom:"):
        cid = provider_id[len("custom:"):]
        definition = config.load_config()["custom"].get(cid)
        if not definition:
            raise ProviderError(f"自定义供应商 {provider_id} 未配置，请先在面板「设置」页添加")
        return GenericTTSProvider(cid, definition)
    raise ProviderError(f"未知供应商: {provider_id}")


def provider_ids() -> list[str]:
    """全部供应商 id（内置 + 用户自定义）。大厅等聚合场景动态遍历用——
    此前 hall_voices 写死四家 id，新适配器永远进不了大厅（MiniMax 就这么漏掉的）。"""
    cfg = config.load_config()
    return list(_BUILTIN) + ["custom:" + cid for cid in cfg["custom"]]


def list_providers() -> list[dict]:
    cfg = config.load_config()
    out = []
    for pid in _BUILTIN:
        p = get_provider(pid)
        pcfg = cfg["providers"].get(pid, {})
        if pid == "local-svc":
            configured = bool(str(pcfg.get("svc_dir", "")).strip())
        else:
            configured = bool(str(pcfg.get("api_key", "")).strip())
        out.append(
            {
                "id": p.id,
                "display_name": p.display_name,
                "tier": p.tier,
                "capabilities": list(p.capabilities),
                "configured": configured,
                "config_schema": list(p.config_schema),
            }
        )
    for cid, definition in cfg["custom"].items():
        p = GenericTTSProvider(cid, definition)
        out.append(
            {
                "id": p.id,
                "display_name": p.display_name,
                "tier": p.tier,
                "capabilities": list(p.capabilities),
                "configured": bool(str(definition.get("url", "")).strip()),
                "config_schema": list(p.config_schema),
            }
        )
    return out
