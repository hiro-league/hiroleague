"""Catalog-driven default model suggestions for empty preference slots (Phase 3c).

First provider in ``provider_ids_ordered`` wins per kind (chat / tts / stt). Embedding and
image_gen recommendations are ignored — no matching preference slots yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .available_models import AvailableModelsService
from .credential_store import CredentialStore
from .model_catalog import ModelCatalog, get_model_catalog
from .preferences import LLMPreferences, WorkspacePreferences, load_preferences, save_preferences


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
    current_prefs: LLMPreferences,
) -> list[DefaultSuggestion]:
    """Build suggestions from providers in order; first provider wins each kind.

    Skips kinds already set in ``current_prefs``, unavailable models, and non-chat/tts/stt
    catalog kinds (e.g. embedding).
    """
    claimed_kinds: set[str] = set()
    out: list[DefaultSuggestion] = []

    for pid in provider_ids_ordered:
        prov = catalog.get_provider(pid)
        if prov is None:
            continue

        for kind, mid in catalog.suggested_defaults(pid).items():
            if kind in ("embedding", "image_gen"):
                continue
            if kind not in ("chat", "tts", "stt"):
                continue
            if kind in claimed_kinds:
                continue

            attr = _kind_to_pref_attr(kind)
            if getattr(current_prefs, attr) is not None:
                continue
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


def _kind_to_pref_attr(kind: str) -> str:
    return {"chat": "default_chat", "tts": "default_tts", "stt": "default_stt"}[kind]


def apply_suggested_defaults(
    prefs: WorkspacePreferences,
    suggestions: list[DefaultSuggestion],
) -> list[DefaultSuggestion]:
    """Write suggestions into empty LLM preference fields.

    When a chat default is applied, ``default_summarization`` is set to the same model id
    if that slot is still empty (summarization uses chat-kind models).
    """
    applied: list[DefaultSuggestion] = []
    for s in suggestions:
        attr = _kind_to_pref_attr(s.catalog_kind)
        if getattr(prefs.llm, attr) is not None:
            continue
        setattr(prefs.llm, attr, s.model_id)
        applied.append(s)
        if s.catalog_kind == "chat" and prefs.llm.default_summarization is None:
            prefs.llm.default_summarization = s.model_id
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
        provider_ids_ordered, cat, ams, prefs.llm,
    )
    if not suggestions:
        return []
    applied = apply_suggested_defaults(prefs, suggestions)
    if applied:
        save_preferences(workspace_path, prefs)
    return applied
