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
from hirocli.services.knowledge.graph.graph_index_marker import (
    clear_graph_indexed,
    is_graph_indexed,
    mark_graph_indexed,
)


def test_no_forced_default_returns_unconfigured(tmp_path: Path) -> None:
    embedder = resolve_knowledge_embedder(tmp_path, None)
    assert isinstance(embedder, UnconfiguredEmbedder)
    # Using it fails fast (indexing blocked) rather than silently picking a model.
    with pytest.raises(RuntimeError, match="No embedder configured"):
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

    from hirocli.services.knowledge.graph.graph_index_marker import graph_has_data

    # No Kuzu DB file → definitively no data (cheap short-circuit, no graph open).
    assert asyncio.run(graph_has_data(tmp_path)) is False


def test_sync_marker_clears_stale_marker_when_no_data(tmp_path: Path) -> None:
    import asyncio

    from hirocli.services.knowledge.graph.graph_index_marker import sync_graph_indexed_marker

    # A stale marker with no underlying graph DB → reconcile clears it (unlock after a full wipe).
    mark_graph_indexed(tmp_path)
    assert is_graph_indexed(tmp_path)
    locked = asyncio.run(sync_graph_indexed_marker(tmp_path))
    assert locked is False
    assert not is_graph_indexed(tmp_path)


def test_graph_embedder_change_blocked_when_indexed(tmp_path: Path) -> None:
    from hirocli.runtime.preferences_runtime import (
        PreferencePathError,
        _validate_knowledge_embedding_transition,
    )

    previous = WorkspacePreferences()
    updated = WorkspacePreferences()
    updated.graph.embedder_model = "openai:text-embedding-3-small"
    edits = {"graph.embedder_model": "openai:text-embedding-3-small"}

    # Not indexed → allowed.
    _validate_knowledge_embedding_transition(tmp_path, previous, updated, edits)

    # Indexed → blocked.
    mark_graph_indexed(tmp_path)
    with pytest.raises(PreferencePathError, match="graph.embedder_model cannot be changed"):
        _validate_knowledge_embedding_transition(tmp_path, previous, updated, edits)


def test_default_embedder_change_blocked_when_graph_inherits_and_indexed(tmp_path: Path) -> None:
    from hirocli.runtime.preferences_runtime import (
        PreferencePathError,
        _validate_knowledge_embedding_transition,
    )

    previous = WorkspacePreferences()
    updated = WorkspacePreferences()
    updated.llm.default_embedder = "sentence-transformers/all-MiniLM-L6-v2"
    edits = {"llm.default_embedder": updated.llm.default_embedder}

    # Graph indexed AND graph override empty (inherits default) → changing the default is blocked.
    mark_graph_indexed(tmp_path)
    with pytest.raises(PreferencePathError, match="llm.default_embedder cannot be changed"):
        _validate_knowledge_embedding_transition(tmp_path, previous, updated, edits)

    # With a graph override set, the graph no longer inherits → default is free to change.
    previous.graph.embedder_model = "openai:text-embedding-3-small"
    updated.graph.embedder_model = "openai:text-embedding-3-small"
    _validate_knowledge_embedding_transition(tmp_path, previous, updated, edits)
