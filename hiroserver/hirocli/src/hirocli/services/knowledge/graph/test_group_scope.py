"""Tests for the firm graph group-ID policy (docs/graph-group-policy-design.md).

The policy is what makes cross-vertical leaks structurally impossible: groups are minted
against a closed grammar (mem_/kb_/eval_), the empty catch-all is banned, and reads/writes
must name a known partition. These tests pin the grammar + the guard.
"""

from __future__ import annotations

import pytest

from hirocli.services.knowledge.graph.group_scope import (
    EVAL_PREFIX,
    KNOWLEDGE_GROUP_ID,
    KNOWLEDGE_PREFIX,
    MEMORY_PREFIX,
    GroupPolicyError,
    character_from_group,
    classify_group,
    eval_knowledge_group_id,
    eval_memory_group_id,
    group_label,
    is_eval_group_id,
    is_knowledge_group_id,
    is_kuzu_only_chunk_group_id,
    is_memory_group_id,
    knowledge_group_id,
    memory_group_id,
    memory_user_prefix,
    slug_group_part,
    validate_group_id,
)


def test_knowledge_group_is_named_not_empty() -> None:
    # The whole point: knowledge has a NAMED partition, never graphiti's empty default ""
    # (which is falsy → leaked into all-groups reads).
    assert KNOWLEDGE_GROUP_ID == "kb_main"
    assert knowledge_group_id() == "kb_main"
    assert knowledge_group_id("research") == "kb_research"


def test_memory_group_grammar_and_slug() -> None:
    assert memory_group_id(42, "aria") == "mem_42_aria"
    # free-form character is slugged to graphiti's alphabet ([A-Za-z0-9_-]).
    assert memory_group_id(1, "hiro:bot") == "mem_1_hiro-bot"
    # trailing-separator prefix can't bleed across users (mem_42_ ≠ mem_420_…).
    assert memory_group_id(420, "x").startswith(memory_user_prefix(420))
    assert not memory_group_id(420, "x").startswith(memory_user_prefix(42))


def test_eval_group_grammar() -> None:
    # One `eval_` roof, two per-track sub-namespaces (docs/eval-corpus-tracks-design.md §4).
    assert eval_memory_group_id("adam") == "eval_mem_adam"
    assert eval_knowledge_group_id("adam") == "eval_kb_adam"
    # Both live under the shared eval prefix (so all eval wipes by one prefix) ...
    assert eval_memory_group_id("set:1").startswith(EVAL_PREFIX)
    assert eval_knowledge_group_id("set:1").startswith(EVAL_PREFIX)
    # ... yet are disjoint from real mem_/kb_ (an eval_mem_ group never matches the mem_ prefix).
    assert not eval_memory_group_id("adam").startswith(MEMORY_PREFIX)
    assert not eval_knowledge_group_id("adam").startswith(KNOWLEDGE_PREFIX)


def test_kuzu_only_chunk_groups_cover_memory_and_eval_memory() -> None:
    # Chunk TEXT lives only in Kuzu for both real memory AND eval-memory — the graph
    # chunk-detail resolver must read EpisodicNode.content for both, never Qdrant.
    assert is_kuzu_only_chunk_group_id(memory_group_id(1, "hiro"))
    assert is_kuzu_only_chunk_group_id(eval_memory_group_id("beam128k_13"))
    # Knowledge (kb_) and eval-knowledge (eval_kb_) keep their text in Qdrant → NOT Kuzu-only.
    assert not is_kuzu_only_chunk_group_id(knowledge_group_id())
    assert not is_kuzu_only_chunk_group_id(eval_knowledge_group_id("adam"))
    assert not is_kuzu_only_chunk_group_id("")


def test_prefixes_are_disjoint() -> None:
    # Every namespace token is distinct → a group belongs to exactly one vertical.
    assert len({MEMORY_PREFIX, KNOWLEDGE_PREFIX, EVAL_PREFIX}) == 3


@pytest.mark.parametrize(
    "group_id,kind",
    [
        ("kb_main", "knowledge"),
        ("kb_research", "knowledge"),
        ("mem_42_aria", "memory"),
        ("eval_mem_adam", "eval"),
        ("eval_kb_adam", "eval"),
        ("legacy", "other"),
        ("", "other"),
    ],
)
def test_classify_group(group_id: str, kind: str) -> None:
    assert classify_group(group_id) == kind


@pytest.mark.parametrize(
    "group_id,label",
    [
        ("kb_main", "Knowledge"),
        ("kb_research", "Knowledge · research"),
        ("mem_42_aria", "Memory · aria (user 42)"),
        ("eval_mem_adam", "Eval · Memory · adam"),
        ("eval_kb_adam", "Eval · Knowledge · adam"),
        ("legacy", "legacy"),  # unknown/legacy → raw id (still selectable/removable)
        ("mem:1:hiro", "mem:1:hiro"),  # legacy colon id → raw (not a valid namespace)
    ],
)
def test_group_label_logical_names(group_id: str, label: str) -> None:
    assert group_label(group_id) == label


def test_membership_helpers() -> None:
    assert is_knowledge_group_id("kb_main") and not is_knowledge_group_id("mem_1_x")
    assert is_memory_group_id("mem_1_x") and not is_memory_group_id("kb_main")
    assert is_eval_group_id("eval_x") and not is_eval_group_id("kb_main")
    # the empty catch-all is no vertical's group.
    assert not is_knowledge_group_id("") and not is_memory_group_id("")


def test_character_from_group() -> None:
    assert character_from_group("mem_42_aria") == "aria"
    assert character_from_group("kb_main") == ""  # not a memory group


def test_validate_accepts_each_namespace() -> None:
    for gid in ("kb_main", "mem_42_aria", "eval_mem_adam", "eval_kb_adam"):
        assert validate_group_id(gid) == gid


@pytest.mark.parametrize("bad", ["", None])
def test_validate_rejects_empty_catch_all(bad) -> None:
    # Banning the empty string here is what makes the old leak impossible.
    with pytest.raises(GroupPolicyError):
        validate_group_id(bad)


def test_validate_rejects_unknown_namespace() -> None:
    # A non-namespaced group (the old "knowledge"/"default"/"grp") is rejected at the
    # write boundary so nothing lands outside the closed grammar.
    for bad in ("knowledge", "default", "grp", "kbmain"):
        with pytest.raises(GroupPolicyError):
            validate_group_id(bad)


def test_validate_rejects_bad_alphabet() -> None:
    # graphiti only accepts [A-Za-z0-9_-]; a colon must be rejected, not silently passed.
    with pytest.raises(GroupPolicyError):
        validate_group_id("mem_1_hiro:bot")


def test_slug_group_part() -> None:
    assert slug_group_part("hiro:bot") == "hiro-bot"
    assert slug_group_part("a b/c") == "a-b-c"
