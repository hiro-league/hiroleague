"""L3 prototype — entity/relationship graph layer over the workspace knowledge corpus.

This module is the *graph backbone* for L3 content routing
(see ``docs/knowledge-l3-prototype-plan.md`` and ``docs/knowledge-l3-content-routing-design.md``).
It holds **structure only** — entities, relations, and back-links to the Qdrant chunks
that asserted them. Evidence (chunk text + vectors) stays in the existing Qdrant
pipeline; the graph never duplicates it.

Two public surfaces:

* :class:`GraphStore` (Protocol) — the thin port retrieval / ingest code talks to.
  Keeping it minimal (~5 ops) is what makes the underlying engine swappable.
* :class:`LadybugGraphStore` — concrete embedded-graph-DB adapter on LadybugDB
  (Kuzu-lineage, Cypher, native Windows wheels). The sole sanctioned fallback if
  Ladybug ever stalls is DuckDB + DuckPGQ, behind the same port.

The boundary is deliberate: this submodule is **isolated and rip-out-able** if the
L3 thesis test (see plan §5.6) doesn't validate.
"""

from __future__ import annotations

from .store import GraphEdge, GraphNode, GraphStore, normalize_name

__all__ = ["GraphEdge", "GraphNode", "GraphStore", "normalize_name"]
