"""Join catalog models with workspace credential state → available models."""

from __future__ import annotations

from dataclasses import dataclass

from .credential_store import CredentialStore
from .model_catalog import (
    DeprecatedModelInfo,
    ModelCatalog,
    ModelSpec,
    get_model_catalog,
)


@dataclass
class ConfiguredProviderSummary:
    provider_id: str
    display_name: str
    hosting: str
    auth_method: str
    available_model_count: int
    has_chat: bool
    has_tts: bool
    has_stt: bool


@dataclass
class CharacterModelValidation:
    unknown_llm: list[str]
    unknown_voice: list[str]
    deprecated_llm: list[DeprecatedModelInfo]
    deprecated_voice: list[DeprecatedModelInfo]
    wrong_kind_llm: list[str]
    wrong_kind_voice: list[str]
    unavailable_llm: list[str]
    unavailable_voice: list[str]


class AvailableModelsService:
    """Catalog models filtered to providers with workspace credentials."""

    def __init__(self, catalog: ModelCatalog, store: CredentialStore) -> None:
        self._catalog = catalog
        self._store = store

    def list_configured_providers(self) -> list[ConfiguredProviderSummary]:
        summaries: list[ConfiguredProviderSummary] = []
        for meta in self._store.list_configured():
            prov = self._catalog.get_provider(meta.provider_id)
            if prov is None:
                continue
            models = self._catalog.list_models(provider_id=meta.provider_id)
            has_chat = any(m.supports_kind("chat") for m in models)
            has_tts = any(m.supports_kind("tts") for m in models)
            has_stt = any(m.supports_kind("stt") for m in models)
            summaries.append(
                ConfiguredProviderSummary(
                    provider_id=meta.provider_id,
                    display_name=prov.display_name,
                    hosting=prov.hosting,
                    auth_method=meta.auth_method,
                    available_model_count=len(models),
                    has_chat=has_chat,
                    has_tts=has_tts,
                    has_stt=has_stt,
                )
            )
        return sorted(summaries, key=lambda s: s.provider_id)

    def list_available_models(
        self,
        *,
        model_kind: str | None = None,
        model_class: str | None = None,
    ) -> list[ModelSpec]:
        out: list[ModelSpec] = []
        for m in self._catalog.list_models(model_kind=model_kind, model_class=model_class):
            if self._store.is_configured(m.provider_id):
                out.append(m)
        return out

    def is_model_available(self, model_id: str) -> bool:
        spec = self._catalog.get_model(model_id)
        if spec is None:
            return False
        return self._store.is_configured(spec.provider_id)

    def validate_character_models(
        self,
        llm_models: list[str],
        voice_models: list[str],
    ) -> CharacterModelValidation:
        unknown_llm: list[str] = []
        unknown_voice: list[str] = []
        deprecated_llm: list[DeprecatedModelInfo] = []
        deprecated_voice: list[DeprecatedModelInfo] = []
        wrong_kind_llm: list[str] = []
        wrong_kind_voice: list[str] = []
        unavailable_llm: list[str] = []
        unavailable_voice: list[str] = []

        seen_llm: set[str] = set()
        for mid in llm_models:
            if mid in seen_llm:
                continue
            seen_llm.add(mid)
            spec = self._catalog.get_model(mid)
            if spec is None:
                unknown_llm.append(mid)
                continue
            if spec.deprecated_since:
                deprecated_llm.append(
                    DeprecatedModelInfo(
                        model_id=mid,
                        deprecated_since=spec.deprecated_since,
                        replacement_id=spec.replacement_id,
                    )
                )
                # Deprecated is the primary finding; skip wrong_kind/unavailable for the same id.
                continue
            if spec.model_kind != "chat":
                wrong_kind_llm.append(mid)
                continue
            if not self._store.is_configured(spec.provider_id):
                unavailable_llm.append(mid)

        seen_v: set[str] = set()
        for mid in voice_models:
            if mid in seen_v:
                continue
            seen_v.add(mid)
            spec = self._catalog.get_model(mid)
            if spec is None:
                unknown_voice.append(mid)
                continue
            if spec.deprecated_since:
                deprecated_voice.append(
                    DeprecatedModelInfo(
                        model_id=mid,
                        deprecated_since=spec.deprecated_since,
                        replacement_id=spec.replacement_id,
                    )
                )
                continue
            if not (spec.supports_kind("tts") or spec.supports_kind("stt")):
                wrong_kind_voice.append(mid)
                continue
            if not self._store.is_configured(spec.provider_id):
                unavailable_voice.append(mid)

        return CharacterModelValidation(
            unknown_llm=sorted(unknown_llm),
            unknown_voice=sorted(unknown_voice),
            deprecated_llm=sorted(deprecated_llm, key=lambda d: d.model_id),
            deprecated_voice=sorted(deprecated_voice, key=lambda d: d.model_id),
            wrong_kind_llm=sorted(wrong_kind_llm),
            wrong_kind_voice=sorted(wrong_kind_voice),
            unavailable_llm=sorted(unavailable_llm),
            unavailable_voice=sorted(unavailable_voice),
        )


def build_available_models_service(
    workspace_path,
    workspace_id: str,
    *,
    store: CredentialStore | None = None,
) -> AvailableModelsService:
    """Convenience: bundled catalog + credential store for a workspace."""
    from pathlib import Path

    ws = Path(workspace_path)
    st = store or CredentialStore(ws, workspace_id)
    return AvailableModelsService(get_model_catalog(), st)
