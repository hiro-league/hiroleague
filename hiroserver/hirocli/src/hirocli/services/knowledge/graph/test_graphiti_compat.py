"""Tests for the graphiti-core version + signature compat guard."""

from __future__ import annotations

import pytest

from hirocli.services.knowledge.graph import graphiti_compat
from hirocli.services.knowledge.graph.graphiti_compat import (
    PINNED_GRAPHITI_VERSION,
    GraphitiCompatibilityError,
    assert_graphiti_compatible,
)


def test_passes_on_installed_pinned_version() -> None:
    # The repo pins graphiti-core to PINNED_GRAPHITI_VERSION; the guard must pass as-is
    # (and the signature probe must match the live search_utils layout).
    assert_graphiti_compatible()


def test_raises_on_version_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(graphiti_compat, "version", lambda _pkg: "9.9.9")
    with pytest.raises(GraphitiCompatibilityError) as exc:
        assert_graphiti_compatible()
    assert PINNED_GRAPHITI_VERSION in str(exc.value)
    assert "9.9.9" in str(exc.value)


def test_raises_on_signature_drift(monkeypatch) -> None:
    # Keep the version matching so we exercise the signature probe specifically.
    monkeypatch.setattr(graphiti_compat, "version", lambda _pkg: PINNED_GRAPHITI_VERSION)

    def _wrong_sig(driver, NOT_query, search_filter, group_ids, limit):  # noqa: N803
        return None

    from graphiti_core.search import search_utils

    monkeypatch.setattr(search_utils, "edge_fulltext_search", _wrong_sig)
    with pytest.raises(GraphitiCompatibilityError, match="signature changed"):
        assert_graphiti_compatible()


def test_raises_when_function_removed(monkeypatch) -> None:
    monkeypatch.setattr(graphiti_compat, "version", lambda _pkg: PINNED_GRAPHITI_VERSION)
    from graphiti_core.search import search_utils

    monkeypatch.delattr(search_utils, "rrf", raising=True)
    with pytest.raises(GraphitiCompatibilityError, match="missing"):
        assert_graphiti_compatible()
