"""Text-to-speech provider package.

Public API
----------
    TTSProvider          — ABC for all TTS providers
    TTSModelInfo         — dataclass describing a single model
    TTSResult            — dataclass carrying synthesis output (audio bytes, MIME, duration)
    TTSService           — orchestrator that aggregates providers and routes by model ID
    OpenAITTSProvider    — OpenAI gpt-4o-mini-tts
    GeminiTTSProvider    — Google Gemini multimodal TTS (preview)
    create_tts_service   — factory that builds a TTSService from workspace preferences
"""

from __future__ import annotations

from pathlib import Path

from hiro_commons.log import Logger

from .gemini_provider import GeminiTTSProvider
from .openai_provider import OpenAITTSProvider
from .provider import TTSModelInfo, TTSProvider, TTSResult
from .service import TTSService

__all__ = [
    "TTSProvider",
    "TTSModelInfo",
    "TTSResult",
    "TTSService",
    "OpenAITTSProvider",
    "GeminiTTSProvider",
    "create_tts_service",
]

_log = Logger.get("TTS")

# Catalog provider_id → TTS implementation (API key from credential store).
_PROVIDER_MAP: dict[str, type[TTSProvider]] = {
    "openai": OpenAITTSProvider,
    "google": GeminiTTSProvider,
}


def create_tts_service(workspace_path: Path) -> TTSService | None:
    """Build a TTSService from workspace preferences, or None if TTS is disabled.

    Resolves the TTS model from ``preferences.llm.default_tts`` through the
    catalog and credential store — same pattern as ``create_stt_service``.
    """
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.model_catalog import get_model_catalog
    from hirocli.domain.preferences import load_preferences, resolve_llm
    from hirocli.domain.workspace import workspace_id_for_path

    prefs = load_preferences(workspace_path)
    if not prefs.audio.agent_replies_in_voice:
        _log.info("TTS disabled in preferences (agent_replies_in_voice=false)")
        return None

    wid = workspace_id_for_path(workspace_path)
    store = CredentialStore(workspace_path, wid) if wid is not None else None
    if store is None:
        _log.warning("TTS enabled but workspace is not in registry — cannot build credential store")
        return None

    cat = get_model_catalog()
    providers: list[TTSProvider] = []
    # Phase 5: load every TTS provider the workspace has credentials for so character
    # voice_models can use a different vendor than llm.default_tts.
    for provider_id, cls in _PROVIDER_MAP.items():
        if not store.is_configured(provider_id):
            continue
        if not any(
            m.model_kind == "tts" for m in cat.list_models(provider_id=provider_id)
        ):
            continue
        inst = cls(api_key=store.get_api_key(provider_id))
        if inst.is_available():
            providers.append(inst)

    tts_resolved = resolve_llm(prefs, workspace_path, "tts", credential_store=store)
    default_model: str | None = None
    if tts_resolved is not None:
        spec = cat.get_model(tts_resolved.model_id)
        if spec is None:
            _log.warning("TTS model id not in catalog", model_id=tts_resolved.model_id)
        else:
            default_model = tts_resolved.model_id.split(":", 1)[1]
    else:
        _log.warning("TTS enabled but no TTS model resolved — set llm.default_tts in preferences")

    if not providers:
        _log.warning("TTS enabled but no TTS providers loaded (check API keys and SDKs)")
        return None

    return TTSService(providers=providers, default_model=default_model)
