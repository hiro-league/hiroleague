"""GraphStore port — the thin interface retrieval / ingest code uses.

Five ops are enough for the L3 prototype: upsert a node, upsert an edge, look up
nodes by their exact normalized name (the deterministic-first resolution step),
pull substring candidates (input to ``rapidfuzz`` ranking + LLM disambiguation),
and traverse one hop from a node. ``get_node`` and ``close`` are housekeeping.

Why a Protocol, not a base class: keeps the engine swappable. The doc-locked
fallback if LadybugDB ever stalls is DuckDB + DuckPGQ — both implementations live
behind this same port so retrieval code never changes.

Keep this file engine-agnostic. No Cypher, no Ladybug imports, no SQL.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Value objects — what the rest of the system passes across the port.
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Canonical lookup key for an entity mention — language-agnostic.

    Pipeline (Unicode-standard "match-side fold"):

    1. **NFKD decompose** — compatibility decomposition splits each character into
       its base + combining marks, and normalizes compatibility forms (full-width
       digits, ligatures, etc.).
    2. **Strip combining marks** (Unicode general category ``Mn``) — folds
       accents/diacritics generically: French ``é/è/ê → e``, Spanish ``ñ → n``,
       Arabic alef variants ``أ/إ/آ → ا``, Vietnamese tones → bare vowels.
       *No language-specific tables.*
    3. **NFC re-compose** — produces a stable canonical string.
    4. **casefold()** — Unicode-aware lowercasing (handles German ``ß → ss``,
       Turkish ``İ → i̇``, etc.), unlike ``str.lower()``.
    5. **Collapse whitespace.**

    This is **search/match-side** normalization, deliberately aggressive for
    recall — people type ``francois`` when they mean ``François``, ``ahmed`` when
    they mean ``أحمد``. The original ``name`` is preserved on the node for
    display + citation; this function only produces the dedup key.

    **Used as the deterministic exact-match key** (Graphiti's deterministic-first
    pattern — research §1.3). Any change here is a re-ingest event because
    existing nodes are keyed on the previous normalization.

    Caveat: aggressive diacritic stripping can conflate distinct words in
    languages where marks are semantic (Vietnamese tones, occasionally Spanish
    ``ño`` vs ``no``). For entity matching in a personal KG this is the right
    trade — revisit if a corpus's primary language can't tolerate folding.
    """
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(name))
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    nfc = unicodedata.normalize("NFC", stripped)
    return _WHITESPACE_RE.sub(" ", nfc.strip().casefold())


@dataclass(frozen=True, slots=True)
class GraphNode:
    """An entity node — a Person / Place / Event / Organization / Object / generic Entity.

    ``chunk_ids`` and ``document_ids`` are the **inline provenance** that joins the
    graph back to the Qdrant evidence chunks that asserted this entity (F5 in the
    plan). No separate join table — the lists ARE the join.
    """

    id: str
    name: str
    type: str
    normalized_name: str
    aliases: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""  # ISO-8601 UTC; set by the adapter when omitted


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """A typed relation between two nodes.

    ``rel_type`` is SCREAMING_SNAKE_CASE (Graphiti convention) — predicate label like
    ``PARTICIPANT``, ``LOCATED_IN``, ``SPOUSE``. Edges carry their own provenance so
    fact-level citations work even when nodes were created from a different chunk.
    """

    id: str
    source_id: str
    target_id: str
    rel_type: str
    chunk_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


@runtime_checkable
class GraphStore(Protocol):
    """Thin port for the entity/relationship graph.

    Implementations must be safe to call from sync code; the adapter is responsible
    for any thread/concurrency policy of the underlying engine. **Do not add LLM
    or embedding concerns here** — those live in the ingest layer (extractor,
    resolver). This interface is purely structural.
    """

    def upsert_node(self, node: GraphNode) -> None:
        """Insert or update a node by ``id``. Idempotent. Provenance lists are MERGED
        (union, deduped) with any existing values so re-ingest of the same source
        does not erase prior chunk_id links."""

    def upsert_edge(self, edge: GraphEdge) -> None:
        """Insert or update an edge by ``id``. Idempotent. Provenance MERGED like nodes."""

    def find_by_name_exact(
        self, normalized_name: str, *, type: str | None = None
    ) -> list[GraphNode]:
        """Deterministic exact-match lookup — the **first step** of resolution.

        Returns 0, 1, or >1 nodes. The resolver treats:
        - exactly 1 → link to that node (no LLM call).
        - 0 → fall through to fuzzy → LLM-if-still-ambiguous.
        - >1 → ambiguous, escalate to LLM disambiguation with context.
        """

    def find_candidates_by_name(
        self, name: str, *, type: str | None = None, limit: int = 20
    ) -> list[GraphNode]:
        """Wider candidate set for the fuzzy / rapidfuzz step (Phase 2).

        Substring/prefix match over normalized names. Caller is expected to
        re-rank with rapidfuzz and apply the entropy gate. NOT a final answer."""

    def neighbors(
        self,
        node_id: str,
        *,
        k: int = 1,
        rel_types: list[str] | None = None,
    ) -> list[GraphNode]:
        """k-hop neighborhood of ``node_id``. The graph's job at retrieval time
        (see plan Example D): resolve query entity → neighbors(k=1) → collect
        their chunk_ids → focus Qdrant hybrid+rerank on those chunks."""

    def edges(self, node_id: str, *, direction: str = "both") -> list[GraphEdge]:
        """Edges incident to ``node_id``. ``direction`` ∈ {``out``, ``in``, ``both``}."""

    def get_node(self, node_id: str) -> GraphNode | None:
        """Fetch a node by id, or ``None`` if absent."""

    def get_edge(self, edge_id: str) -> GraphEdge | None:
        """Fetch an edge by id, or ``None`` if absent.

        Used by ingest to tell *created* from *provenance-merged* when emitting
        live viz events (new edge → "pop", merged edge → "pulse")."""

    def snapshot(
        self, *, node_limit: int | None = None, edge_limit: int | None = None
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Whole-graph read for visualization (the admin Graph tab's load path).

        Returns ``(nodes, edges)``. Bounded by the optional limits — a safety cap
        so a runaway graph can't produce an unbounded payload. The graph here is
        tiny by design, so an unfiltered read is fine; the limits exist to keep
        the contract honest at scale. See docs/knowledge-graph-viz-design.md."""

    def close(self) -> None:
        """Release the engine handle. Safe to call multiple times."""


__all__ = ["GraphEdge", "GraphNode", "GraphStore", "normalize_name"]
