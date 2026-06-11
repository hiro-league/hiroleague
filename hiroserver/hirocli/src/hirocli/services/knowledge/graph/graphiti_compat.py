"""Pin the re-hosted fact-search pipeline to a known graphiti-core internal layout.

``graphiti_fact_search`` re-implements graphiti's ``edge_search`` orchestration by
calling its **internal** ``search_utils`` leg functions directly (the only way to
capture per-stage candidates/scores — the public ``search()`` discards them). Those
internals carry **no stability guarantee** (graphiti-core is ``0.x``), so this guard
makes any drift fail **loud and early** with an actionable message instead of
silently returning wrong traces.

Two layers:

1. **Exact version pin** — trips on *any* version change, even a patch, because an
   internal can move in a patch under ``0.x``.
2. **Signature probe** — catches the case where someone bumps ``_PINNED`` after an
   upgrade but the function shapes we replicate have changed.

Per the repo's no-backward-compatibility rule we *want* the hard failure: a version
bump is a deliberate re-validation event (re-read graphiti's ``edge_search`` and the
leg signatures, confirm the re-host still matches, then bump ``_PINNED``)."""

from __future__ import annotations

import inspect
from importlib.metadata import PackageNotFoundError, version

# The graphiti-core version whose ``edge_search`` internals ``graphiti_fact_search``
# was validated against. Bump ONLY after re-validating the re-host (and its parity
# test) against the new source.
PINNED_GRAPHITI_VERSION = "0.29.1"

# Leading positional parameters we depend on for each internal we call. We check a
# prefix (not the full list) so an *added* trailing optional arg doesn't false-trip,
# while a rename/reorder of the params we actually pass does.
_EXPECTED_SIGNATURES: dict[str, list[str]] = {
    "edge_fulltext_search": ["driver", "query", "search_filter", "group_ids", "limit"],
    "edge_similarity_search": [
        "driver",
        "search_vector",
        "source_node_uuid",
        "target_node_uuid",
        "search_filter",
        "group_ids",
        "limit",
        "min_score",
    ],
    "edge_bfs_search": [
        "driver",
        "bfs_origin_node_uuids",
        "bfs_max_depth",
        "search_filter",
        "group_ids",
        "limit",
    ],
    "rrf": ["results", "rank_const", "min_score"],
    "get_embeddings_for_edges": ["driver", "edges"],
    "maximal_marginal_relevance": [
        "query_vector",
        "candidates",
        "mmr_lambda",
        "min_score",
    ],
    # Node (entity) lane — note node_similarity_search has NO source/target, and
    # node_bfs_search puts search_filter BEFORE bfs_max_depth (unlike the edge variant).
    "node_fulltext_search": ["driver", "query", "search_filter", "group_ids", "limit"],
    "node_similarity_search": [
        "driver",
        "search_vector",
        "search_filter",
        "group_ids",
        "limit",
        "min_score",
    ],
    "node_bfs_search": [
        "driver",
        "bfs_origin_node_uuids",
        "search_filter",
        "bfs_max_depth",
        "group_ids",
        "limit",
    ],
    "get_embeddings_for_nodes": ["driver", "nodes"],
    # Episode lane.
    "episode_fulltext_search": ["driver", "query", "_search_filter", "group_ids", "limit"],
    # Internals used by graphiti_bfs (the SHORTEST-path BFS rewrite that replaces
    # the vendored edge/node BFS legs — see graphiti_bfs.py). All are re-exported
    # into the search_utils namespace by its own imports, so we probe them here.
    "edge_search_filter_query_constructor": ["filters", "provider"],
    "node_search_filter_query_constructor": ["filters", "provider"],
    "get_entity_edge_return_query": ["provider"],
    "get_entity_node_return_query": ["provider"],
    "get_entity_edge_from_record": ["record", "provider"],
    "get_entity_node_from_record": ["record", "provider"],
}


class GraphitiCompatibilityError(RuntimeError):
    """Raised when the installed graphiti-core no longer matches the re-host's pin."""


def assert_graphiti_compatible() -> None:
    """Fail loudly unless installed graphiti-core matches the validated layout.

    Called once when the re-hosted fact search is first engaged (not at import, so a
    workspace that never uses traced retrieval is unaffected)."""
    try:
        found = version("graphiti-core")
    except PackageNotFoundError as exc:  # pragma: no cover - install is always present
        raise GraphitiCompatibilityError(
            "graphiti-core is not installed; the re-hosted fact-search trace requires it."
        ) from exc

    if found != PINNED_GRAPHITI_VERSION:
        raise GraphitiCompatibilityError(
            f"Retrieval stage-trace re-host is pinned to graphiti-core=="
            f"{PINNED_GRAPHITI_VERSION}, but {found} is installed. The re-host replicates "
            f"graphiti's internal edge_search orchestration (candidate legs, BFS expansion, "
            f"rerank order, 2*limit fanout); re-validate it against the new source and its "
            f"parity test, then bump PINNED_GRAPHITI_VERSION in graphiti_compat.py."
        )

    _assert_signatures()


def _assert_signatures() -> None:
    from graphiti_core.search import search_utils as su

    for name, expected_head in _EXPECTED_SIGNATURES.items():
        fn = getattr(su, name, None)
        if fn is None:
            raise GraphitiCompatibilityError(
                f"graphiti-core {PINNED_GRAPHITI_VERSION}: search_utils.{name} is missing — "
                f"the re-host depends on it. Re-validate graphiti_fact_search."
            )
        params = list(inspect.signature(fn).parameters)
        if params[: len(expected_head)] != expected_head:
            raise GraphitiCompatibilityError(
                f"graphiti-core {PINNED_GRAPHITI_VERSION}: search_utils.{name} signature changed "
                f"(expected leading {expected_head}, got {params}). Re-validate the re-host "
                f"in graphiti_fact_search before trusting its traces."
            )


__all__ = [
    "GraphitiCompatibilityError",
    "PINNED_GRAPHITI_VERSION",
    "assert_graphiti_compatible",
]
