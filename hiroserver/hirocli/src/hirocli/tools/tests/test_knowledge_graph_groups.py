"""Group selector helpers for the admin Graph tab (knowledge / conversation-memory / eval).

Classification follows the firm group-ID policy (docs/graph-group-policy-design.md): the
named ``kb_*`` partition is "Knowledge", ``mem_{user}_{character}`` is conversation memory,
``eval_*`` is an eval corpus — no reliance on graphiti's empty default group.
"""

from pathlib import Path

import pytest

from hirocli.tools.knowledge_graph import _label_graph_group, graph_groups_payload


def test_label_graph_group_classifies_by_namespace() -> None:
    assert _label_graph_group("kb_main") == {
        "id": "kb_main",
        "label": "Knowledge",
        "kind": "knowledge",
    }
    mem = _label_graph_group("mem_42_aria")
    assert mem["kind"] == "memory" and mem["id"] == "mem_42_aria"
    assert "aria" in mem["label"] and "42" in mem["label"]
    ev = _label_graph_group("eval_adam")
    assert ev["kind"] == "eval" and ev["id"] == "eval_adam"
    other = _label_graph_group("weird")
    assert other == {"id": "weird", "label": "weird", "kind": "other"}


@pytest.mark.asyncio
async def test_graph_groups_payload_orders_knowledge_first(monkeypatch) -> None:
    async def fake_read(_db_path):
        # read_graph_group_ids returns (distinct_groups, knowledge_default_group_id=kb_main).
        return ["mem_7_bob", "kb_main", "eval_adam", "mem_42_aria"], "kb_main"

    monkeypatch.setattr("hirocli.tools.knowledge_graph.read_graph_group_ids", fake_read)
    payload = await graph_groups_payload(Path("/tmp/ws"))

    assert payload["default_group_id"] == "kb_main"
    kinds = [g["kind"] for g in payload["groups"]]
    assert kinds[0] == "knowledge"  # knowledge partition is always offered first
    assert kinds.count("memory") == 2
    assert "eval" in kinds  # eval corpora surface in the selector
    # Order: knowledge, then memory, then eval, then other.
    assert kinds == ["knowledge", "memory", "memory", "eval"]
    mem_labels = [g["label"] for g in payload["groups"] if g["kind"] == "memory"]
    assert mem_labels == sorted(mem_labels, key=str.lower)  # memory groups alphabetical
