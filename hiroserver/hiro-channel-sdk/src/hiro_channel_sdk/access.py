"""What a role may do in an extension (Phase 9a): features, their rights, and the one check every extension makes.

An extension declares its features when it connects (``ExtensionInfo.features``): each feature lists its rights,
the things a person can do in it ("see", "build", "delete", ...). The core keeps, per role, the rights it grants in
each extension and hands an extension its own part with ``people.list`` (each role's ``rights``); ``people.changed``
says when to read again. The extension enforces them with :func:`allowed`, so every extension checks rights the
same way and none keeps its own copy of the rules.

Rights are keys ``"<feature>.<right>"``. A feature that has a ``see`` right is not there at all without it, so
granting any other right of that feature grants ``see`` too (:func:`normalize`). The owner role has every right
except the features marked ``not_for_owner`` (HomeHiro's My room, the kids' page).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, Field

OWNER_ROLE = "owner"  # the core's built-in role id
SEE = "see"  # the right that shows a feature at all


class ExtensionRight(BaseModel):
    """One thing a person can do in a feature."""

    id: str
    name: str
    says: str = ""  # one line on what it allows, shown next to the checkbox


class ExtensionFeature(BaseModel):
    """A part of an extension that a role may be given, with the rights in it."""

    id: str
    name: str
    rights: list[ExtensionRight] = Field(default_factory=list)
    not_for_owner: bool = False  # a page made for others (My room): the owner doesn't get it


def right_key(feature: str, right: str) -> str:
    return f"{feature}.{right}"


def declared_keys(features: Iterable[ExtensionFeature]) -> list[str]:
    """Every right key the features declare, in order."""
    return [right_key(f.id, r.id) for f in features for r in f.rights]


def owner_rights(features: Iterable[ExtensionFeature]) -> set[str]:
    """What the owner has: everything, except the features not made for the owner."""
    return {right_key(f.id, r.id) for f in features if not f.not_for_owner for r in f.rights}


def normalize(features: Iterable[ExtensionFeature], granted: Iterable[str]) -> list[str]:
    """The granted keys kept to the declared ones, with ``see`` added wherever another right of a feature that has
    one is granted. Returned in declaration order, so two equal grants compare equal."""
    features = list(features)
    keep = set(granted) & set(declared_keys(features))
    for f in features:
        ids = {r.id for r in f.rights}
        if SEE in ids and any(k.startswith(f"{f.id}.") for k in keep):
            keep.add(right_key(f.id, SEE))
    return [k for k in declared_keys(features) if k in keep]


def allowed(role_id: str | None, granted: Iterable[str], feature: str, right: str,
            features: Mapping[str, ExtensionFeature]) -> bool:
    """Whether a role may use one right. No role (waiting, refused) may do nothing; the owner has everything but
    what isn't for the owner; anyone else has what was granted."""
    f = features.get(feature)
    if f is None or role_id is None:
        return False
    if role_id == OWNER_ROLE:
        return not f.not_for_owner
    return right_key(feature, right) in set(granted)
