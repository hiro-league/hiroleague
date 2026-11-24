"""What a role may do in an extension (Phase 9a): features, their rights, and the one check every extension makes.

An extension declares its features when it connects (``ExtensionInfo.features``): each feature lists its rights,
the things a person can do in it ("see", "build", "delete", ...). The core keeps, per role, the rights it grants in
each extension and hands an extension its own part with ``people.list`` (each role's ``rights``); ``resource.changed``
for ``people`` says when to read again. The extension enforces them with :func:`allowed`, so every extension checks rights the
same way and none keeps its own copy of the rules.

Rights are keys ``"<feature>.<right>"``. A feature that has a ``see`` right is not there at all without it, so
granting any other right of that feature grants ``see`` too (:func:`normalize`). The owner role has every right
except the features marked ``not_for_owner`` (HomeHiro's My room, the kids' page).

Permissions phase 1: a person holds one or several roles, and their rights add up. A right declared ``personal`` is
about people's things (a person's study, memory, room): it is granted for everyone's (the plain key) or for the
person's own (``"<feature>.<right>:own"``). Every key that existed keeps its meaning. :func:`reach` says how far a
person's roles reach for one right, and :func:`allowed` answers for one record, given whose it is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, Field

OWNER_ROLE = "owner"  # the core's built-in role id
SEE = "see"  # the right that shows a feature at all
OWN = ":own"  # the end of a key that reaches only the person's own things

Reach = Literal["no", "own", "all"]
_RANK: dict[str, int] = {"no": 0, "own": 1, "all": 2}


class ExtensionRight(BaseModel):
    """One thing a person can do in a feature."""

    id: str
    name: str
    says: str = ""  # one line on what it allows, shown next to the checkbox
    # About people's things: granted for the person's own ("<feature>.<right>:own") or everyone's (the plain key).
    personal: bool = False


class ExtensionFeature(BaseModel):
    """A part of an extension that a role may be given, with the rights in it."""

    id: str
    name: str
    rights: list[ExtensionRight] = Field(default_factory=list)
    not_for_owner: bool = False  # a page made for others (My room): the owner doesn't get it


def right_key(feature: str, right: str) -> str:
    return f"{feature}.{right}"


def declared_keys(features: Iterable[ExtensionFeature]) -> list[str]:
    """Every right key the features declare, in order: the plain ones, then each personal right's ``:own`` key after
    its plain one."""
    return [k for f in features for r in f.rights for k in _keys_of(f.id, r)]


def _keys_of(feature: str, r: ExtensionRight) -> tuple[str, ...]:
    key = right_key(feature, r.id)
    return (key, key + OWN) if r.personal else (key,)


def owner_rights(features: Iterable[ExtensionFeature]) -> set[str]:
    """What the owner has: everything, except the features not made for the owner."""
    return {right_key(f.id, r.id) for f in features if not f.not_for_owner for r in f.rights}


def normalize(features: Iterable[ExtensionFeature], granted: Iterable[str]) -> list[str]:
    """The granted keys kept to the declared ones: an ``:own`` key only for a personal right, and dropped when the
    plain key (everyone's) is there too. ``see`` is added wherever another right of a feature that has one is granted,
    reaching at least as far (everyone's, unless ``see`` is personal and every grant is their own). Returned in
    declaration order, so two equal grants compare equal."""
    granted = set(granted)
    out: list[str] = []
    for f in features:
        reaches: dict[str, Reach] = {}
        for r in f.rights:
            key = right_key(f.id, r.id)
            if key in granted:
                reaches[r.id] = "all"
            elif r.personal and key + OWN in granted:
                reaches[r.id] = "own"
        see = next((r for r in f.rights if r.id == SEE), None)
        if see is not None and reaches:
            widest: Reach = "all" if "all" in reaches.values() or not see.personal else "own"
            if _RANK[widest] > _RANK[reaches.get(SEE, "no")]:
                reaches[SEE] = widest
        for r in f.rights:
            key = right_key(f.id, r.id)
            if reaches.get(r.id) == "all":
                out.append(key)
            elif reaches.get(r.id) == "own":
                out.append(key + OWN)
    return out


def reach(roles: Mapping[str, Iterable[str]], feature: str, right: str,
          features: Mapping[str, ExtensionFeature]) -> Reach:
    """How far a person's roles reach for one right: ``roles`` is every role they hold, each with its keys in this
    source. "all" when a role is the owner's (and the feature is for the owner) or holds the plain key; "own" when a
    role holds the ``:own`` key of a personal right; else "no". No role (waiting, refused) reaches nothing."""
    f = features.get(feature)
    if f is None:
        return "no"
    declared = next((r for r in f.rights if r.id == right), None)
    key = right_key(feature, right)
    best: Reach = "no"
    for role_id, keys in roles.items():
        if role_id == OWNER_ROLE:
            if not f.not_for_owner:
                return "all"
            continue
        held = set(keys)
        if key in held:
            return "all"
        if declared is not None and declared.personal and key + OWN in held:
            best = "own"
    return best


def allowed(roles: Mapping[str, Iterable[str]], feature: str, right: str, features: Mapping[str, ExtensionFeature],
            *, asker: str | None = None, owners: Iterable[str] | None = None) -> bool:
    """The one check: whether a person may use one right. Their roles add up (:func:`reach`). A grant for their own
    things answers yes only for a record that is theirs: ``asker`` is the person asking, ``owners`` the people the
    record belongs to, both handed in by the caller. Without them, only a grant for everyone's counts."""
    got = reach(roles, feature, right, features)
    if got == "all":
        return True
    return got == "own" and asker is not None and owners is not None and asker in set(owners)
