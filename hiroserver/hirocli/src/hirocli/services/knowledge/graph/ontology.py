"""L3 graph ontology — typed node/edge schemas for extraction.

The prototype uses a **small typed node set** (Person, Place, Event, Organization,
Object) with a generic ``Entity`` fallback for things that don't fit. Relations
are **open-ended** strings (SCREAMING_SNAKE_CASE) — we don't constrain them to a
fixed list yet (matches LightRAG's flexibility; tightening to a typed predicate
set is a Phase-2-plus refinement).

All structured-output schemas live here so they are easy to evolve without
touching extractor logic.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field as PydanticField

# The closed node-type set. Anything else extracted by the LLM falls back to
# the generic ``Entity`` label — never reject, never drop information. Adding a
# type means re-ingesting (existing nodes keep their old label).
NodeType = Literal["Person", "Place", "Event", "Organization", "Object", "Entity"]

ALL_NODE_TYPES: tuple[NodeType, ...] = (
    "Person",
    "Place",
    "Event",
    "Organization",
    "Object",
    "Entity",
)

# Hint list rendered into the extraction prompt so the LLM picks from a known
# vocabulary. Order is hierarchy-of-preference: specific over generic.
NODE_TYPE_GUIDE: dict[str, str] = {
    "Person":       "named individual (family, friend, colleague, etc.)",
    "Place":        "geographic location, building, city, address, landmark",
    "Event":        "specific occurrence in time (trip, meeting, party, appointment)",
    "Organization": "company, team, school, club, agency",
    "Object":       "named physical thing (a specific car, watch, photo, document)",
    "Entity":       "fallback for anything specific that doesn't fit the above",
}


class ExtractedEntity(BaseModel):
    """One typed entity mention from a chunk.

    ``aliases`` are the load-bearing addition: when the chunk gives a kinship or
    possessive form together with the proper name (e.g. ``"my mother Sara"``),
    the extractor emits ``name="Sara", aliases=["my mother","mom"]``. Future
    bare ``"mom"`` mentions then **exact-match the alias** on Sara's node, no
    LLM call needed — turning a fragile coreference into deterministic resolution
    (the explicit fix for the prototype plan's Example B)."""

    name: str = PydanticField(
        ...,
        description=(
            "The entity's canonical name — the proper noun when one is given, "
            "otherwise the most specific available label with possessive qualification "
            "('Maya's sister' not 'sister'). Preserve specificity: 'wool coat' not "
            "'coat'. Never a pronoun (he/she/they) or a generic noun."
        ),
    )
    type: NodeType = PydanticField(
        default="Entity",
        description=(
            "One of: Person, Place, Event, Organization, Object. Use 'Entity' as a "
            "generic fallback ONLY when none of the specific types fit."
        ),
    )
    aliases: list[str] = PydanticField(
        default_factory=list,
        description=(
            "Alternate surface forms that refer to the SAME real-world entity, "
            "extracted ONLY when the chunk pairs a kinship/relational term with the "
            "proper name in the same passage (e.g. 'my mother Sara' → name='Sara', "
            "aliases=['my mother','mom']; 'Maya's cat Whiskers' → name='Whiskers', "
            "aliases=['Maya's cat']). Do NOT invent aliases that aren't in the text; "
            "do NOT include the canonical name itself."
        ),
    )


class ExtractedRelation(BaseModel):
    """A typed predicate between two distinct entities."""

    source_name: str = PydanticField(
        ...,
        description="Name of the source entity — MUST match one of the entities[] above.",
    )
    target_name: str = PydanticField(
        ...,
        description="Name of the target entity — MUST match one of the entities[] above.",
    )
    rel_type: str = PydanticField(
        ...,
        description=(
            "SCREAMING_SNAKE_CASE predicate label, e.g. PARTICIPANT, LIVES_IN, "
            "SPOUSE, WORKS_AT, LOCATED_IN, OWNS, KNOWS, OCCURRED_IN."
        ),
    )
    fact: str = PydanticField(
        default="",
        description=(
            "One-sentence natural-language paraphrase of the asserted fact, preserving "
            "concrete details (dates, numbers, places). Used for citation, not for matching."
        ),
    )


class ChunkExtraction(BaseModel):
    """LLM output schema — a single call per chunk emits entities + relations together.

    This is the LightRAG single-call efficiency pattern (research §2.1). The
    same call extracts both lists, so we pay one model invocation per chunk
    regardless of how many entities/relations land.
    """

    entities: list[ExtractedEntity] = PydanticField(default_factory=list)
    relations: list[ExtractedRelation] = PydanticField(default_factory=list)


class DisambiguationDecision(BaseModel):
    """LLM output schema for the resolver's ambiguity step.

    Called only when the deterministic ladder (exact → fuzzy) returns multiple
    candidates or a short / low-entropy name that the deterministic path can't
    safely match. Output is intentionally tiny: which candidate (or none)."""

    matched_candidate_id: str | None = PydanticField(
        default=None,
        description=(
            "ID of the candidate node this mention refers to. Null when none of the "
            "candidates is the same real-world entity (a new node will be created)."
        ),
    )
    reason: str = PydanticField(
        default="",
        description="Brief justification (one short clause). Logged for debugging only.",
    )


__all__ = [
    "ALL_NODE_TYPES",
    "NODE_TYPE_GUIDE",
    "NodeType",
    "ExtractedEntity",
    "ExtractedRelation",
    "ChunkExtraction",
    "DisambiguationDecision",
]
