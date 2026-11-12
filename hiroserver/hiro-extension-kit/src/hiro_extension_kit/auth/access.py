"""What a role may do in the app: its features and the rights in each (`Extension.features`, the app's extension.py).

The app declares them to HiroLeague when it connects (hiroleague.py, `ExtensionInfo.features`). The owner grants them
per role in HiroLeague's admin (People → Roles); the app keeps a copy of each role's rights (`Role.rights`, read with
the family list, family.py) and checks them on every route (guard.py) with the SDK's one check
(`hiro_channel_sdk.access.allowed`). Rights are keys "<feature>.<right>"; a feature with a "see" right isn't there
without it. Owner has every right. Users and roles themselves are not a feature: only owners see them, so nobody can
give themselves more.

The pages read a level per feature (`levels`): "use" when a role has any right beyond seeing it, so a page shows its
buttons; the routes check the exact right and say which one is missing.
"""

from collections.abc import Iterable
from typing import Literal

from hiro_channel_sdk.access import SEE, ExtensionRight, allowed, owner_rights

from ..extension import ext

Access = Literal["no", "see", "use"]
OWNER = "owner"  # the core's built-in role id


def see(what: str) -> ExtensionRight:
    """A feature's "see" right, as every app words it."""
    return ExtensionRight(id=SEE, name="See", says=f"Open {what}, change nothing")


def right(rid: str, name: str, says: str) -> ExtensionRight:
    return ExtensionRight(id=rid, name=name, says=says)


def has_see(feature: str) -> bool:
    return any(r.id == SEE for r in ext().by_id[feature].rights)


def can(role_id: str | None, rights: Iterable[str], feature: str, right: str) -> bool:
    """Whether a role may use one right. Asking to see a feature that has no "see" right (Settings): any of its rights
    is enough to read it."""
    rights = list(rights)
    by_id = ext().by_id
    if right == SEE and not has_see(feature):
        return any(allowed(role_id, rights, feature, r.id, by_id) for r in by_id[feature].rights)
    return allowed(role_id, rights, feature, right, by_id)


def rights_of(role_id: str | None, rights: Iterable[str]) -> list[str]:
    """A role's rights as granted (the owner's: all of them), in declaration order."""
    features = ext().features
    have = owner_rights(list(features)) if role_id == OWNER else set(rights) if role_id else set()
    return [f"{f.id}.{r.id}" for f in features for r in f.rights if f"{f.id}.{r.id}" in have]


def level(role_id: str | None, rights: Iterable[str], feature: str) -> Access:
    """A feature's level for the pages: "use" with any right beyond seeing it, "see" with only that, else "no"."""
    by_id = ext().by_id
    f = by_id[feature]
    rights = list(rights)
    if any(r.id != SEE and allowed(role_id, rights, feature, r.id, by_id) for r in f.rights):
        return "use"
    return "see" if has_see(feature) and allowed(role_id, rights, feature, SEE, by_id) else "no"


def levels(role_id: str | None, rights: Iterable[str]) -> dict[str, Access]:
    """Every feature's level, for the frontend (menus, pages, buttons)."""
    rights = list(rights)
    return {f.id: level(role_id, rights, f.id) for f in ext().features}
