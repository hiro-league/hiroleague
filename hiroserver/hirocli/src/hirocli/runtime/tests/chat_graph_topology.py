"""Extract a stable chat-graph topology snapshot for wiring regression tests (P1a)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def chat_topology(compiled: CompiledStateGraph) -> dict[str, Any]:
    """Node registration order, retry policies, and compiled edges for one ``build()`` result."""
    graph = compiled.get_graph()
    builder = compiled.builder
    node_order = [name for name in builder.nodes if name not in ("__start__", "__end__")]
    retry_policies: dict[str, dict[str, int]] = {}
    for name, spec in builder.nodes.items():
        if name in ("__start__", "__end__"):
            continue
        retry = getattr(spec, "retry_policy", None)
        if retry is not None:
            retry_policies[name] = {"max_attempts": retry.max_attempts}
    edges = [
        {
            "source": edge.source,
            "target": edge.target,
            "conditional": bool(getattr(edge, "conditional", False)),
        }
        for edge in sorted(graph.edges, key=lambda e: (e.source, e.target))
    ]
    return {"node_order": node_order, "retry_policies": retry_policies, "edges": edges}


def load_topology_fixture(combo: str) -> dict[str, Any]:
    path = _FIXTURES_DIR / f"chat_graph_topology_{combo}.json"
    return json.loads(path.read_text(encoding="utf-8"))
