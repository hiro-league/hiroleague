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


__all__ = ["GRAPHITI_ENTITY_TYPES"]
