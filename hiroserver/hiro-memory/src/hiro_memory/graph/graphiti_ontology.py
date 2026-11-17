"""Typed entity ontology for Graphiti extraction.

Graphiti has no built-in ontology — without ``entity_types`` it labels everything
``Entity``. Passing these Pydantic models pins a small, personal-KG type
vocabulary (Person / Place / Organization / Event / Object); anything that doesn't
fit still falls back to the base ``Entity`` label.

The models are intentionally **field-less**: the class name IS the label, and
Graphiti only runs the extra per-node attribute-extraction LLM call when a type
defines structured fields. Empty models = typed labels at no extra call cost
(decision: base ontology now, custom attributes deferred —
docs/knowledge-graphiti-pivot-design.md §5.4 / §14).

Edge-type vocabulary pinning (``edge_types`` / ``edge_type_map``) is deferred: for
now Graphiti free-forms ``SCREAMING_SNAKE`` relation names. Revisit if the eval
shows relation-synonym fragmentation (LIVES_IN vs RESIDES_IN).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Person(BaseModel):
    """An individual person — family, friend, colleague, or public figure."""


class Place(BaseModel):
    """A physical location — city, country, building, landmark, or venue."""


class Organization(BaseModel):
    """A company, institution, team, school, or group."""


class Event(BaseModel):
    """A dated happening — trip, meeting, wedding, job change, milestone."""


class Object(BaseModel):
    """A notable thing — product, vehicle, document, or possession."""


# Passed straight to ``Graphiti.add_episode(entity_types=...)``.
GRAPHITI_ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": Person,
    "Place": Place,
    "Organization": Organization,
    "Event": Event,
    "Object": Object,
}


# graphiti's built-in id-0 "Entity" fallback (mirrors ``graphiti_core``'s
# ``_build_entity_types_context`` base entry), trimmed to the gist — kept here so the ingest
# trace can resolve an ``entity_type_id`` to a name + description without importing graphiti.
_BASE_ENTITY_DESCRIPTION = (
    "A specific, identifiable entity that does not fit any of the other listed types."
)


def entity_type_legend() -> list[dict[str, Any]]:
    """``entity_type_id`` → ``{id, name, description}``, in graphiti's ordering.

    Mirrors ``graphiti_core``'s ``_build_entity_types_context``: id 0 is the base ``Entity``
    fallback, then the ontology types in declaration order (id 1…N), descriptions taken from
    each model's docstring. Lets the ingest-trace dialog render the ``extract_entities`` stage's
    numeric ``entity_type_id`` as the actual type name + description (single source of truth)."""
    legend: list[dict[str, Any]] = [
        {"id": 0, "name": "Entity", "description": _BASE_ENTITY_DESCRIPTION}
    ]
    for index, (name, model) in enumerate(GRAPHITI_ENTITY_TYPES.items()):
        legend.append(
            {"id": index + 1, "name": name, "description": (model.__doc__ or "").strip()}
        )
    return legend


__all__ = ["GRAPHITI_ENTITY_TYPES", "entity_type_legend"]
