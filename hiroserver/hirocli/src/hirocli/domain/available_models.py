"""Join catalog models with workspace credential state → available models."""

from __future__ import annotations

from dataclasses import dataclass

from .credential_store import CredentialStore
from .model_catalog import (
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
    has_embedding: bool
    has_rerank: bool
    has_image_gen: bool


class AvailableModelsService:
    """Catalog models filtered to providers with workspace credentials."""

    def __init__(self, catalog: ModelCatalog, store: CredentialStore) -> None:
        self._catalog = catalog
        self._store = store

    def list_configured_providers(self) -> list[ConfiguredProviderSummary]:
        summaries: list[ConfiguredProviderSummary] = []
        for meta in self._store.list_configured():
            prov = self._catalog.get_provider(meta.provider_id)
            # Hidden providers are suppressed even when credentials are configured (user
            # decision): the Providers page / CLI list must not show them. The credential
            # stays in the store and keeps resolving for existing model selections.
            if prov is None or prov.hidden:
                continue
            models = self._catalog.list_models(provider_id=meta.provider_id)
            has_chat = any(m.supports_kind("chat") for m in models)
            has_tts = any(m.supports_kind("tts") for m in models)
            has_stt = any(m.supports_kind("stt") for m in models)
            has_embedding = any(m.supports_kind("embedding") for m in models)
            has_rerank = any(m.supports_kind("rerank") for m in models)
            has_image_gen = any(m.supports_kind("image_gen") for m in models)
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
                    has_embedding=has_embedding,
                    has_rerank=has_rerank,
                    has_image_gen=has_image_gen,
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
