"""The core's retrieval-agent prompt names every field the engine's search tool sends."""

from __future__ import annotations

from hiro_memory.conversation.agent.accumulator import AccumulatedItem
from hiro_memory.conversation.agent.search_tool import _serialize_item


def test_serialized_field_names_documented_in_retrieval_prompt() -> None:
    """Parity guard (item 12): every metadata field the agent receives must be documented by exact
    name in the retrieval-agent prompt, so renaming one side without the other can't silently
    drift (the root-cause class of the fidelity bugs)."""
    from hirocli.domain.preferences import DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT as PROMPT

    edge = _serialize_item(
        AccumulatedItem(
            kind="edge",
            uuid="e",
            search_id=1,
            goal="",
            payload={
                "kind": "fact", "fact": "f", "name": "PLANS_TO_WATCH", "stated": "2024-01-01",
                "valid_at": "2024-01-01", "invalid_at": "2024-02-01", "chunk_id": "c",
            },
        )
    )
    entity = _serialize_item(
        AccumulatedItem(
            kind="entity", uuid="n", search_id=1, goal="",
            payload={"kind": "entity", "name": "X", "entity_type": "Person", "summary": "s"},
        )
    )
    episode = _serialize_item(
        AccumulatedItem(
            kind="episode", uuid="ep", search_id=1, goal="",
            payload={"kind": "episode", "memory": "t", "valid_at": "2024-01-01"},
        )
    )
    # Structural/plumbing keys aren't part of the documented metadata vocabulary.
    structural = {"kind", "id", "score", "fact", "text", "name", "summary", "source_episode"}
    metadata_keys = (set(edge) | set(entity) | set(episode)) - structural
    # The fidelity fix must actually have added these:
    assert {"relation", "stated", "as_of", "until", "entity_type"} <= metadata_keys
    for key in sorted(metadata_keys):
        assert f"`{key}`" in PROMPT, f"serialized field {key!r} not documented in the retrieval prompt"

