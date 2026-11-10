"""Catalog-driven default model suggestions for empty preference slots (Phase 3c).

First provider in ``provider_ids_ordered`` wins per kind (chat / tts / stt). Embedding and
image_gen recommendations are ignored — no matching preference slots yet.

Phase 7b step 5: the chat slot is Hiro's chat AI profile (``llm.chat_profile``: a ``hiro-chat``
profile with the chat preset tuning is made for the model) and the speech slot is Hiro's voice
(``voice.hiro_profile``: a ``hiro-voice`` voice profile with the provider's default voice). The
speech-to-text slot is still the model field ``llm.default_stt``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .available_models import AvailableModelsService
from .credential_store import CredentialStore
from .model_catalog import ModelCatalog, get_model_catalog
from .preferences import VoiceProfile, WorkspacePreferences, load_preferences, save_preferences
from .preferences.jobs import preset_profile, unique_profile_id

# A provider's voice for Hiro's default voice profile (Gemini studio voice / OpenAI voice).
DEFAULT_HIRO_VOICE = {"google": "kore", "openai": "sage"}


@dataclass(frozen=True)
class DefaultSuggestion:
    """One catalog recommendation that passed availability and empty-slot checks."""

    catalog_kind: str  # chat, tts, stt
    model_id: str
    display_name: str
    provider_id: str
    provider_display_name: str


def compute_suggested_defaults(
    provider_ids_ordered: list[str],
    catalog: ModelCatalog,
    available: AvailableModelsService,
    current_prefs: WorkspacePreferences,
) -> list[DefaultSuggestion]:
    """Build suggestions from providers in order; first provider wins each kind.

    Skips kinds already set in ``current_prefs``, unavailable models, and non-chat/tts/stt
    catalog kinds (e.g. embedding).
    """
    claimed_kinds: set[str] = set()
    out: list[DefaultSuggestion] = []

    for pid in provider_ids_ordered:
        prov = catalog.get_provider(pid)
        # Hidden providers must not seed default suggestions, even when already configured
        # (suggestions are an "offering" surface like pickers).
        if prov is None or prov.hidden:
            continue

        for kind, mid in catalog.suggested_defaults(pid).items():
            if kind in ("embedding", "image_gen"):
                continue
            if kind not in ("chat", "tts", "stt"):
                continue
            if kind in claimed_kinds:
                continue

            if _slot_filled(current_prefs, kind):
                continue
            if kind == "tts" and pid not in DEFAULT_HIRO_VOICE:
                continue  # the core speaks with google / openai voices only
            if not available.is_model_available(mid):
                continue
            spec = catalog.get_model(mid)
            if spec is None:
                continue

            out.append(
                DefaultSuggestion(
                    catalog_kind=kind,
                    model_id=mid,
                    display_name=spec.display_name,
                    provider_id=prov.id,
                    provider_display_name=prov.display_name,
                )
            )
            claimed_kinds.add(kind)

    return out


def _slot_filled(prefs: WorkspacePreferences, kind: str) -> bool:
    if kind == "chat":
        return prefs.llm.chat_profile is not None
    if kind == "tts":
        return prefs.voice.hiro_profile is not None
    return prefs.llm.default_stt is not None


def apply_suggested_defaults(
    prefs: WorkspacePreferences,
    suggestions: list[DefaultSuggestion],
) -> list[DefaultSuggestion]:
    """Write suggestions into empty slots (chat → a hiro-chat AI profile, tts → a hiro-voice voice
    profile, stt → ``llm.default_stt``)."""
    applied: list[DefaultSuggestion] = []
    for s in suggestions:
        if _slot_filled(prefs, s.catalog_kind):
            continue
        if s.catalog_kind == "chat":
            pid = unique_profile_id(prefs.ai.profiles, "hiro-chat")
            prefs.ai.profiles[pid] = preset_profile("chat", s.model_id)
            prefs.llm.chat_profile = pid
        elif s.catalog_kind == "tts":
            if s.provider_id not in DEFAULT_HIRO_VOICE:
                continue  # a speech model the core can't speak with (google / openai only)
            pid = unique_profile_id(prefs.voice.profiles, "hiro-voice")
            prefs.voice.profiles[pid] = VoiceProfile(
                label="Hiro's voice", model=s.model_id, voice=DEFAULT_HIRO_VOICE[s.provider_id]
            )
            prefs.voice.hiro_profile = pid
        else:
            prefs.llm.default_stt = s.model_id
        applied.append(s)
    return applied


def apply_onboarding_defaults_to_preferences(
    workspace_path: Path,
    workspace_id: str,
    provider_ids_ordered: list[str],
) -> list[DefaultSuggestion]:
    """Compute suggestions, apply to empty slots, persist preferences. Returns applied rows."""
    prefs = load_preferences(workspace_path)
    cat = get_model_catalog()
    store = CredentialStore(workspace_path, workspace_id)
    ams = AvailableModelsService(cat, store)
    suggestions = compute_suggested_defaults(
        provider_ids_ordered, cat, ams, prefs,
    )
    if not suggestions:
        return []
    applied = apply_suggested_defaults(prefs, suggestions)
    if applied:
        save_preferences(workspace_path, prefs)
    return applied
