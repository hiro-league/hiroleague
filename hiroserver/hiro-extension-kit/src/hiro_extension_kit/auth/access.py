"""What a person may do in the app: its features and the actions in each (`Extension.features`, the app's extension.py).

The app declares them to HiroLeague when it connects (hiroleague.py, `ExtensionInfo.features`). The owner grants them
per role in HiroLeague's admin (People → Roles); the app keeps a copy of each role's permissions (`Role.rights`, read
with the family list, family.py) and checks them on every route (guard.py) with the SDK's one check
(`hiro_channel_sdk.access`). A permission is a key "<feature>.<action>"; a feature with a "see" action isn't there
without it. People and roles themselves are not a feature: only owners see them, so nobody can give themselves more.

Permissions phase 5: a person holds one or several roles (`Held`: each role with its keys here), and their
permissions add up. An action declared personal is granted for everyone's things (the plain key) or for the person's
own ("<feature>.<action>:own"): `reach` says how far a person's roles go, `can` answers for one record, given whose it
is. Owner has every permission except a feature not for the owner.

The pages read a level per feature (`levels`): "use" when the roles reach any action beyond seeing it (their own
things included), so a page shows its buttons; the routes check the exact action, and whose the record is.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from hiro_channel_sdk.access import OWN, SEE, ExtensionRight, Reach
from hiro_channel_sdk.access import reach as sdk_reach
from sqlmodel import Session, col, select

from ..extension import ext
from .models import AppUser, Role

Access = Literal["no", "see", "use"]
OWNER = "owner"  # the core's built-in role id
Held = Mapping[str, Sequence[str]]  # every role a person holds, each with its keys in the app
_RANK: dict[str, int] = {"no": 0, "own": 1, "all": 2}


def see(what: str) -> ExtensionRight:
    """A feature's "see" action, as every app words it."""
    return ExtensionRight(id=SEE, name="See", says=f"Open {what}, change nothing")


def right(rid: str, name: str, says: str) -> ExtensionRight:
    return ExtensionRight(id=rid, name=name, says=says)


def held(session: Session, role_ids: Iterable[str]) -> dict[str, list[str]]:
    """The roles a person holds, each with its keys here, in the order given. A role the app's copy doesn't have yet
    is left out."""
    ids = list(role_ids)
    if not ids:
        return {}
    rows = {r.id: list(r.rights) for r in session.exec(select(Role).where(col(Role.id).in_(ids)))}
    return {i: rows[i] for i in ids if i in rows}


def of_user(session: Session, user: AppUser | None) -> dict[str, list[str]]:
    """A user's roles with their keys: none while they wait, or when the owner chose No access."""
    if user is None or user.denied:
        return {}
    return held(session, user.role_ids)


def is_owner(roles: Held) -> bool:
    return OWNER in roles


def has_see(feature: str) -> bool:
    return any(r.id == SEE for r in ext().by_id[feature].rights)


def reach(roles: Held, feature: str, action: str) -> Reach:
    """How far a person's roles reach for one action: "all", "own" or "no". Asking to see a feature that has no "see"
    action (Settings): its widest action is enough to read it."""
    by_id = ext().by_id
    if action == SEE and not has_see(feature):
        return max((sdk_reach(roles, feature, r.id, by_id) for r in by_id[feature].rights), key=_RANK.__getitem__,
                   default="no")
    return sdk_reach(roles, feature, action, by_id)


def can(roles: Held, feature: str, action: str, *, asker: str | None = None, owners: Iterable[str] | None = None) -> bool:
    """Whether a person may use one action. A grant for their own things answers yes only for a record that is theirs:
    `asker` is the person asking, `owners` the people the record belongs to. Without them, only a grant for everyone's
    counts."""
    got = reach(roles, feature, action)
    if got == "all":
        return True
    return got == "own" and asker is not None and owners is not None and asker in set(owners)


def rights_of(roles: Held) -> list[str]:
    """The keys a person's roles add up to, in declaration order: the plain key where they reach everyone's, the key
    ending ":own" where they reach their own things only (the owner's: everything for the owner)."""
    by_id = ext().by_id
    out: list[str] = []
    for f in ext().features:
        for r in f.rights:
            got = sdk_reach(roles, f.id, r.id, by_id)
            if got != "no":
                out.append(f"{f.id}.{r.id}" + (OWN if got == "own" else ""))
    return out


def level(roles: Held, feature: str) -> Access:
    """A feature's level for the pages: "use" with any action beyond seeing it, "see" with only that, else "no"."""
    f = ext().by_id[feature]
    if any(r.id != SEE and reach(roles, feature, r.id) != "no" for r in f.rights):
        return "use"
    return "see" if has_see(feature) and reach(roles, feature, SEE) != "no" else "no"


def levels(roles: Held) -> dict[str, Access]:
    """Every feature's level, for the frontend (menus, pages, buttons)."""
    return {f.id: level(roles, f.id) for f in ext().features}


@dataclass(frozen=True)
class PersonRights:
    """A person with their rights in the app: the one shape for a signed-in caller (the route check keeps it on
    `request.state.rights`) and for the person an ask is for (asked_for.py). No roles: no rights at all (waiting, No
    access, someone the app doesn't know)."""

    person_id: str
    roles: Mapping[str, Sequence[str]] = field(default_factory=dict)

    @property
    def owner(self) -> bool:
        return is_owner(self.roles)

    def reach(self, feature: str, action: str = SEE) -> Reach:
        return reach(self.roles, feature, action)

    def can(self, feature: str, action: str = SEE, *, owners: Iterable[str] | None = None) -> bool:
        """Whether this person may use one action of one of the app's features (see it, by default); for their own
        things only, on a record whose `owners` include them."""
        return can(self.roles, feature, action, asker=self.person_id, owners=owners)
