"""Graph group-ID policy — the single, firm namespace for the one Kuzu store.

See ``docs/graph-group-policy-design.md``. Three verticals share one Graphiti + Kuzu
store, partitioned by ``group_id``. Every legal ``group_id`` is **minted here** against a
**closed grammar**; no other module constructs ``group_id`` strings, and reads/writes must
name a **non-empty, known** partition. This makes cross-vertical leaks *structurally*
impossible: a write can't land in a catch-all, and a read can't fall through to "all
groups".

Namespaces (disjoint leading tokens — every group belongs to exactly one vertical)::

    mem_{user}_{character}   conversation memory   (per user × character)
    kb_{space}               document knowledge    (one named space "main" today)
    eval_{set}               eval corpora          (per eval set)

graphiti-core validates ``group_id`` against ``[A-Za-z0-9_-]+`` (colons et al. rejected),
so the separator is ``_`` and free-form parts (character_id, eval set) are slugged to that
alphabet. The trailing-separator convention (``mem_{user}_``) makes each prefix an
unambiguous boundary — ``mem_42_`` matches ``mem_42_aria`` but not ``mem_420_x``.
"""

from __future__ import annotations

import re

# graphiti's allowed alphabet + our separator (docs §4).
_GROUP_SEP = "_"
_DISALLOWED_GROUP_CHARS = re.compile(r"[^0-9A-Za-z_-]+")
_VALID_GROUP_ID = re.compile(r"^[A-Za-z0-9_-]+$")

# Namespace leading tokens — a CLOSED set. Adding a vertical = adding a token here.
NS_MEMORY = "mem"
NS_KNOWLEDGE = "kb"
NS_EVAL = "eval"

MEMORY_PREFIX = f"{NS_MEMORY}{_GROUP_SEP}"  # "mem_"
KNOWLEDGE_PREFIX = f"{NS_KNOWLEDGE}{_GROUP_SEP}"  # "kb_"
EVAL_PREFIX = f"{NS_EVAL}{_GROUP_SEP}"  # "eval_"
_KNOWN_PREFIXES = (MEMORY_PREFIX, KNOWLEDGE_PREFIX, EVAL_PREFIX)

# Knowledge is one NAMED space today (not graphiti's empty default — that was the leak,
# docs §2). The grammar already admits more spaces (Phase B) without a catch-all.
KNOWLEDGE_DEFAULT_SPACE = "main"
KNOWLEDGE_GROUP_ID = f"{NS_KNOWLEDGE}{_GROUP_SEP}{KNOWLEDGE_DEFAULT_SPACE}"  # "kb_main"


class GroupPolicyError(ValueError):
    """A ``group_id`` violated the firm partition policy (empty / unknown namespace / bad
    chars). Raised at the write boundary and when re-minting untrusted client scopes."""


def slug_group_part(value: str) -> str:
    """Coerce a free-form ``group_id`` component to graphiti's alphabet (``[A-Za-z0-9_-]``)."""
    return _DISALLOWED_GROUP_CHARS.sub("-", str(value))


def memory_group_id(user_id: int, character_id: str) -> str:
    """Conversation-memory partition for one ``(user, character)`` (decision D1).

    The trailing-separator convention (``mem_{user}_{character}``) makes the per-user prefix
    ``mem_{user}_`` an unambiguous boundary, so cross-character enumeration can't bleed
    between users. ``user_id`` is an int (never needs slugging); ``character_id`` is slugged."""
    return f"{NS_MEMORY}{_GROUP_SEP}{user_id}{_GROUP_SEP}{slug_group_part(character_id)}"


def memory_user_prefix(user_id: int) -> str:
    """``mem_{user}_`` — enumerate a user's per-character memory groups (no cross-user bleed)."""
    return f"{NS_MEMORY}{_GROUP_SEP}{user_id}{_GROUP_SEP}"


def knowledge_group_id(space: str = KNOWLEDGE_DEFAULT_SPACE) -> str:
    """Document-knowledge partition. One named space (``kb_main``) today; the grammar admits
    more (Phase B multi-space) without reintroducing graphiti's empty catch-all."""
    return f"{NS_KNOWLEDGE}{_GROUP_SEP}{slug_group_part(space)}"


def eval_group_id(set_id: str) -> str:
    """Eval-corpus partition, isolated per eval set so eval never pollutes knowledge."""
    return f"{NS_EVAL}{_GROUP_SEP}{slug_group_part(set_id)}"


def character_from_group(group_id: str) -> str:
    """``mem_{user}_{character}`` → ``character`` (empty if not a memory group)."""
    if group_id.startswith(MEMORY_PREFIX):
        parts = group_id.split(_GROUP_SEP, 2)
        if len(parts) == 3:
            return parts[2]
    return ""


def is_memory_group_id(group_id: str) -> bool:
    """``mem_{user}_{character}`` — the conversation-memory partition. Used by callers that
    must route by chunk origin (e.g. memory chunks resolve from Kuzu, not Qdrant)."""
    return bool(group_id) and group_id.startswith(MEMORY_PREFIX)


def is_knowledge_group_id(group_id: str) -> bool:
    """``kb_{space}`` — the document-knowledge partition."""
    return bool(group_id) and group_id.startswith(KNOWLEDGE_PREFIX)


def is_eval_group_id(group_id: str) -> bool:
    """``eval_{set}`` — an eval-corpus partition."""
    return bool(group_id) and group_id.startswith(EVAL_PREFIX)


def classify_group(group_id: str) -> str:
    """Namespace kind for the Graph-tab selector: ``knowledge``/``memory``/``eval``/``other``."""
    if is_knowledge_group_id(group_id):
        return "knowledge"
    if is_memory_group_id(group_id):
        return "memory"
    if is_eval_group_id(group_id):
        return "eval"
    return "other"


def group_label(group_id: str) -> str:
    """The **logical display name** for a group_id, derived from the namespace grammar
    (docs/graph-group-policy-design.md §4) — so UIs show meaning, not raw ids:

    - ``kb_main`` → ``Knowledge``;  ``kb_{space}`` → ``Knowledge · {space}``
    - ``mem_{user}_{character}`` → ``Memory · {character} (user {user})``
    - ``eval_{set}`` → ``Eval · {set}``
    - anything else (legacy / unknown) → the raw id, so it's still selectable/removable.
    """
    if is_knowledge_group_id(group_id):
        space = group_id[len(KNOWLEDGE_PREFIX) :]
        return "Knowledge" if space == KNOWLEDGE_DEFAULT_SPACE else f"Knowledge · {space}"
    if is_memory_group_id(group_id):
        rest = group_id[len(MEMORY_PREFIX) :]
        user = rest.split(_GROUP_SEP, 1)[0]
        character = character_from_group(group_id) or "?"
        return f"Memory · {character} (user {user})" if user else f"Memory · {character}"
    if is_eval_group_id(group_id):
        return f"Eval · {group_id[len(EVAL_PREFIX):]}"
    return group_id


def validate_group_id(group_id: str | None) -> str:
    """Return ``group_id`` if it is a legal, namespaced partition; else raise.

    The single chokepoint that enforces the firm policy (docs §6): every partition is
    non-empty, uses graphiti's alphabet, and belongs to a known namespace
    (``mem_``/``kb_``/``eval_``). Call it at every **write** boundary and at the **API**
    boundary (to re-mint untrusted client-supplied scopes). Banning the empty string here
    is what makes the old catch-all — and cross-vertical leaks — impossible.
    """
    if not group_id:
        raise GroupPolicyError(
            "group_id must be a non-empty namespaced partition (mem_/kb_/eval_)"
        )
    if not _VALID_GROUP_ID.match(group_id):
        raise GroupPolicyError(f'group_id "{group_id}" must contain only [A-Za-z0-9_-]')
    if not group_id.startswith(_KNOWN_PREFIXES):
        raise GroupPolicyError(
            f'group_id "{group_id}" is not in a known namespace (mem_/kb_/eval_)'
        )
    return group_id


__all__ = [
    "GroupPolicyError",
    "KNOWLEDGE_DEFAULT_SPACE",
    "KNOWLEDGE_GROUP_ID",
    "MEMORY_PREFIX",
    "KNOWLEDGE_PREFIX",
    "EVAL_PREFIX",
    "NS_MEMORY",
    "NS_KNOWLEDGE",
    "NS_EVAL",
    "slug_group_part",
    "memory_group_id",
    "memory_user_prefix",
    "knowledge_group_id",
    "eval_group_id",
    "character_from_group",
    "group_label",
    "is_memory_group_id",
    "is_knowledge_group_id",
    "is_eval_group_id",
    "classify_group",
    "validate_group_id",
]
