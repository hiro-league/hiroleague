"""Local (in-process) downloadable models — first-class companions to the catalog.

The catalog (``catalog.yaml``) holds cloud / server-provider models. In-process library models
(local rerankers + the local default embedder) have no API key or endpoint and carry per-workspace
**download** state, so they are not catalog YAML rows. They live in code registries
(``services.knowledge.reranker_registry``; the FastEmbed embedder) and are surfaced here as
first-class browse citizens:

- one synthetic **"local" provider** (``LocalProviderRow``) shown in the Providers tabs, so models
  never reference an invisible provider;
- ``LocalModelRow`` rows with full metadata (context, features, a *free* flag, the backend as a
  tag) so the Models browse columns are populated like cloud rows;
- a per-workspace ``downloaded`` overlay (a pure marker check — see ``download_markers``).

``hosting`` is always ``"local"`` and availability means *downloaded*, not *provider configured*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

LOCAL_PROVIDER_ID = "local"


@dataclass(frozen=True)
class LocalProviderRow:
    """The single synthetic provider that owns all in-process local models."""

    id: str = LOCAL_PROVIDER_ID
    display_name: str = "Local (in-process)"
    hosting: str = "local"
    credential_env_keys: list[str] = field(default_factory=list)
    docs_url: str | None = None
    metadata_updated_at: str = "2026-05-30"
    notes: str = "In-process models (FlashRank / FastEmbed / sentence-transformers). No API key; download on demand."


@dataclass(frozen=True)
class LocalModelRow:
    """A local in-process model, shaped for the Catalog browse (read-only)."""

    id: str
    provider_id: str  # always the synthetic "local" provider
    display_name: str
    model_kind: str  # "rerank" | "embedding"
    hosting: str  # always "local"
    backend: str  # flashrank | fastembed | sentence_transformers (shown as a tag/feature)
    size_label: str
    languages: str
    description: str
    context_window: int | None
    modalities: list[str]
    features: list[str]
    free: bool  # local models cost nothing to run → pricing shows a Free indicator
    downloaded: bool  # per-workspace overlay (marker check)
    # Where the user manages availability when not downloaded — kind-specific, since rerankers
    # are explicit opt-in downloads while the default embedder auto-downloads on first ingest.
    manage_hint: str
    source: str = "local"


def list_local_providers() -> list[LocalProviderRow]:
    """The synthetic local provider(s). One bucket today: ``local``."""
    return [LocalProviderRow()]


def list_local_model_rows(
    workspace_path: Path,
    *,
    model_kind: str | None = None,
) -> list[LocalModelRow]:
    """Aggregate registered local models into browse rows, overlaying download status.

    Covers local rerankers and the local default embedder. This aggregator IS the lightweight
    "unified local registry" — no separate abstraction is needed until many more kinds accrue.
    """
    rows: list[LocalModelRow] = []
    if model_kind in (None, "rerank"):
        rows.extend(_reranker_rows(workspace_path))
    if model_kind in (None, "embedding"):
        rows.extend(_embedder_rows(workspace_path))
    return rows


def _features(backend: str, *, multilingual: bool) -> list[str]:
    feats = [backend]
    feats.append("multilingual" if multilingual else "monolingual")
    feats.append("torch" if backend == "sentence_transformers" else "onnx")
    return feats


def _reranker_rows(workspace_path: Path) -> list[LocalModelRow]:
    from hirocli.services.knowledge.reranker_registry import (
        is_downloaded,
        list_local_rerankers,
        reranker_cache_dir,
    )

    cache = reranker_cache_dir(workspace_path)
    return [
        LocalModelRow(
            id=spec.id,
            provider_id=LOCAL_PROVIDER_ID,
            display_name=spec.display_name,
            model_kind="rerank",
            hosting="local",
            backend=spec.backend,
            size_label=spec.size_label,
            languages=spec.languages,
            description=spec.description,
            context_window=spec.context_window,
            modalities=["text"],
            features=_features(spec.backend, multilingual=spec.multilingual),
            free=True,
            downloaded=is_downloaded(spec, cache),
            manage_hint="Download in Preferences → Knowledge → Reranker",
        )
        for spec in list_local_rerankers()
    ]


def _embedder_rows(workspace_path: Path) -> list[LocalModelRow]:
    """Local FastEmbed embedders (curated registry) with per-workspace download status.

    These are pickable options (no forced default): the user chooses one as the workspace default
    or a per-tool override, and downloads it like a reranker. ``downloaded`` is the shared marker.
    """
    from hirocli.services.knowledge.embedder_registry import (
        embedder_cache_dir,
        is_downloaded,
        list_local_embedders,
    )

    cache = embedder_cache_dir(workspace_path)
    return [
        LocalModelRow(
            id=spec.id,
            provider_id=LOCAL_PROVIDER_ID,
            display_name=spec.display_name,
            model_kind="embedding",
            hosting="local",
            backend="fastembed",
            size_label=spec.size_label,
            languages=spec.languages,
            description=spec.description,
            context_window=None,
            modalities=["text"],
            features=_features("fastembed", multilingual=spec.multilingual),
            free=True,
            downloaded=is_downloaded(spec, cache),
            manage_hint="Download in Preferences → General → Default models (or a Knowledge/Graph embedder)",
        )
        for spec in list_local_embedders()
    ]
