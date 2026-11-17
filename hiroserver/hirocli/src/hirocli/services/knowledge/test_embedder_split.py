"""Tests for the split embedder model (default + per-tool overrides), no forced default, and the
per-tool locks (knowledge points / graph-indexed marker)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.preferences import WorkspacePreferences
from hirocli.services.knowledge.embedder import UnconfiguredEmbedder, resolve_knowledge_embedder
from hirocli.services.knowledge.embedder_registry import (
    get_local_embedder,
    is_downloaded,
    is_local_embedder,
    list_local_embedders,
)
from hiro_memory.graph.graph_index_marker import (
    clear_graph_indexed,
    is_graph_indexed,
    mark_graph_indexed,
)


def test_no_forced_default_returns_unconfigured(tmp_path: Path) -> None:
    embedder = resolve_knowledge_embedder(tmp_path, None)
    assert isinstance(embedder, UnconfiguredEmbedder)
    # Using it fails fast (indexing blocked) rather than silently picking a model.
    with pytest.raises(RuntimeError, match="No embedding profile picked"):
        _ = embedder.dimension


def test_unknown_embedder_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown embedder model"):
        resolve_knowledge_embedder(tmp_path, "not-a-real:model")


def test_local_embedder_registry_lists_minilm() -> None:
    specs = list_local_embedders()
    ids = {s.id for s in specs}
    assert "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" in ids
    assert is_local_embedder("sentence-transformers/all-MiniLM-L6-v2")
    assert not is_local_embedder("openai:text-embedding-3-small")
    spec = get_local_embedder("sentence-transformers/all-MiniLM-L6-v2")
    assert spec is not None and spec.dimension == 384


def test_local_embedder_download_marker_roundtrip(tmp_path: Path) -> None:
    from hirocli.services.knowledge.download_markers import write_marker

    spec = list_local_embedders()[0]
    cache = tmp_path / "fastembed_cache"
    assert not is_downloaded(spec, cache)
    write_marker(cache, spec.id, content=spec.id)
    assert is_downloaded(spec, cache)


def test_graph_index_marker_roundtrip(tmp_path: Path) -> None:
    assert not is_graph_indexed(tmp_path)
    mark_graph_indexed(tmp_path)
    assert is_graph_indexed(tmp_path)
    clear_graph_indexed(tmp_path)
    assert not is_graph_indexed(tmp_path)


def test_graph_has_data_false_without_db(tmp_path: Path) -> None:
    import asyncio

    from hiro_memory.graph.graph_index_marker import graph_has_data

    # No Kuzu DB file → definitively no data (cheap short-circuit, no graph open).
    assert asyncio.run(graph_has_data(tmp_path)) is False


def test_sync_marker_clears_stale_marker_when_no_data(tmp_path: Path) -> None:
    import asyncio

    from hiro_memory.graph.graph_index_marker import sync_graph_indexed_marker

    # A stale marker with no underlying graph DB → reconcile clears it (unlock after a full wipe).
    mark_graph_indexed(tmp_path)
    assert is_graph_indexed(tmp_path)
    locked = asyncio.run(sync_graph_indexed_marker(tmp_path))
    assert locked is False
    assert not is_graph_indexed(tmp_path)


def _with_profiles(**picks: str | None) -> WorkspacePreferences:
    return WorkspacePreferences.model_validate({
        "embedding": {"profiles": {
            "small": {"label": "Small", "model": "openai:text-embedding-3-small"},
            "mini": {"label": "Mini", "model": "sentence-transformers/all-MiniLM-L6-v2"},
            "small-too": {"label": "Small too", "model": "openai:text-embedding-3-small"},
        }},
        "graph": {"embedder_profile": picks.get("graph")},
        "knowledge": {"embedder_profile": picks.get("knowledge")},
    })


def test_graph_embedder_change_blocked_when_indexed(tmp_path: Path) -> None:
    from hirocli.runtime.preferences_runtime import (
        PreferencePathError,
        _validate_knowledge_embedding_transition,
    )

    previous = _with_profiles(graph="small")
    updated = _with_profiles(graph="mini")
    edits = {"graph.embedder_profile": "mini"}

    # Not indexed → allowed.
    _validate_knowledge_embedding_transition(tmp_path, previous, updated, edits)

    # Indexed → blocked.
    mark_graph_indexed(tmp_path)
    with pytest.raises(PreferencePathError, match="memory graph's embedder can't change"):
        _validate_knowledge_embedding_transition(tmp_path, previous, updated, edits)

    # Another profile with the same model is fine: the vectors stay valid.
    _validate_knowledge_embedding_transition(tmp_path, previous, _with_profiles(graph="small-too"), {})


def test_editing_the_picked_profiles_model_is_blocked_when_indexed(tmp_path: Path) -> None:
    from hirocli.runtime.preferences_runtime import (
        PreferencePathError,
        _validate_knowledge_embedding_transition,
    )

    previous = _with_profiles(graph="small")
    updated = previous.model_copy(deep=True)
    updated.embedding.profiles["small"].model = "google:gemini-embedding-001"
    mark_graph_indexed(tmp_path)
    with pytest.raises(PreferencePathError, match="from openai:text-embedding-3-small to google:gemini-embedding-001"):
        _validate_knowledge_embedding_transition(tmp_path, previous, updated, {})

    # A profile the graph doesn't use is free to change.
    other = previous.model_copy(deep=True)
    other.embedding.profiles["mini"].model = "google:gemini-embedding-001"
    _validate_knowledge_embedding_transition(tmp_path, previous, other, {})
