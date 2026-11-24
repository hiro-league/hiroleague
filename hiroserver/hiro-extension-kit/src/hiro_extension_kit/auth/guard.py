"""The check every API request passes first: who is asking (api.py `caller`), and whether their roles hold the
permission the route needs, for whose record (the app's rules, `Extension.rules`, on `hiro_commons.rules`, which says
what each kind of rule means; access.py the permissions; whose.py whose a record is).

A person's roles add up. A grant for everyone's passes; a grant for their own things passes only through the rule's
`whose`, settled here before the handler runs. The owner has everything, and so does everyone with sign-in off
(AUTH=off, a dev copy). The route gets the caller (`request.state.caller`), their rights (`request.state.rights`) and
the reach (`request.state.reach`, which a list route takes through `whose.listed`).
"""

from collections.abc import Iterable
from typing import Any

from fastapi import Request
from fastapi.routing import APIRoute
from hiro_channel_sdk.access import SEE, Reach
from hiro_commons.rules import Rule
from hiro_commons.rules import rule_for as _rule_for
from sqlmodel import Session

from .. import identity
from ..db import run_db
from ..errors import NotAllowed
from ..extension import ext
from . import whose
from .access import Held, PersonRights, of_user, reach
from .api import caller, not_linked, seen
from .identity import Caller
from .models import AppUser

_RANK: dict[str, int] = {"no": 0, "own": 1, "all": 2}

# The kit's own routes that every app mounts, with the kit's rule, before the app's own rules: an app needn't list them.
KIT_RULES: tuple[Rule, ...] = (
    Rule("/api/apps", "signed_in"),  # the app switcher's list (hiroleague_api.py): everyone with a role
    Rule("/api/page-problems", "signed_in", methods=("POST",)),  # a page's problems, into the log (page_problems.py)
)


def rule_for(method: str, path: str) -> Rule | None:
    """The rule for a route (its path as declared, e.g. /api/service-status/alerts/{alert_id}), or None."""
    return _rule_for((*KIT_RULES, *ext().rules), method, path)


def needed(rule: Rule, feature: str, method: str) -> str:
    """The action a route needs in one of its features (the rule's own, else by method)."""
    if rule.action:
        return rule.action
    if method in ("GET", "HEAD"):
        return SEE
    ids = [r.id for r in ext().by_id[feature].rights]
    if method == "DELETE" and "delete" in ids:
        return "delete"
    return next((r for r in ids if r != SEE), SEE)


def needs_whose(rule: Rule) -> bool:
    """Whether a rule may need a personal action (one granted for the person's own things or everyone's), so it must
    say whose the record is."""
    if rule.who != "features":
        return False
    by_id = ext().by_id
    methods = rule.methods or ("GET", "POST", "PUT", "PATCH", "DELETE")
    for f in rule.features:
        personal = {r.id for r in by_id[f].rights if r.personal}
        if any(needed(rule, f, m) in personal for m in methods):
            return True
    return False


def rules_without_whose(rules: Iterable[Rule]) -> list[str]:
    """The paths of rules under a personal action that don't say whose the record is (the contract's check)."""
    return sorted(r.path for r in rules if needs_whose(r) and r.whose is None)


def unknown_lookups(rules: Iterable[Rule]) -> list[str]:
    """Rules naming a lookup nobody registered (auth.whose.register), as "<path>: <lookup>" (the contract's check)."""
    return sorted(f"{r.path}: {r.whose.lookup}" for r in rules
                  if r.whose is not None and r.whose.kind == "lookup" and whose.lookup(r.whose.lookup) is None)


def lists_without_reach(routes: Iterable[Any]) -> list[str]:
    """Routes whose rule is LIST but whose handler doesn't take the reach (whose.listed), as "<METHOD> <path>" (the
    contract's check)."""

    def takes_it(dependant: Any) -> bool:
        return any(d.call is whose.listed or takes_it(d) for d in dependant.dependencies)

    return sorted(f"{m} {route.path}" for route in routes if isinstance(route, APIRoute) for m in route.methods
                  if (rule := rule_for(m, route.path)) is not None and rule.whose is not None
                  and rule.whose.kind == "list" and not takes_it(route.dependant))


def reach_of(rule: Rule, method: str, roles: Held) -> Reach:
    """How far a person's roles reach a route with this rule (for rules that name features): the widest of its
    features."""
    return max((reach(roles, f, needed(rule, f, method)) for f in rule.features), key=_RANK.__getitem__, default="no")


def allowed(rule: Rule, method: str, roles: Held) -> bool:
    """Whether a person's roles reach a route with this rule for everyone's records (a grant for their own things
    reaches only through the rule's whose, which needs the request: `guard`)."""
    return reach_of(rule, method, roles) == "all"


def _refusal(rule: Rule, method: str) -> str:
    by_id = ext().by_id
    wanted = []
    for f in rule.features:
        action = needed(rule, f, method)
        name = next((r.name for r in by_id[f].rights if r.id == action), action)
        wanted.append(by_id[f].name if action == SEE else f"{by_id[f].name}: {name}")
    if all(needed(rule, f, method) == SEE for f in rule.features):
        return f"Your roles don't include {' or '.join(wanted)}."
    return f"Your roles don't have the right for this ({' or '.join(wanted)}); ask the owner to give it in HiroLeague."


def _rights_of(session: Session, c: Caller) -> PersonRights:
    # a signed-in person may reach a page before /api/me made their row: make it now
    user = session.get(AppUser, c.user_id) or seen(session, c)
    return PersonRights(c.user_id, of_user(session, user))


def _owners(session: Session, name: str, record_id: str) -> list[str]:
    found = whose.lookup(name)
    return [str(p) for p in found(session, record_id)] if found else []


async def _theirs(request: Request, rule: Rule, person_id: str) -> bool:
    """Whether the record a request names is the asker's, by the rule's whose (a list: always; the handler filters)."""
    w = rule.whose
    if w is None:
        return False
    if w.kind == "list":
        return True
    value = request.path_params.get(w.param) or request.query_params.get(w.param) or ""
    if w.kind == "param":
        return value == person_id
    return bool(value) and person_id in await run_db(_owners, w.lookup, value)


async def guard(request: Request) -> None:
    """A dependency of every route (the app's app.py). Keeps the caller, their rights and the reach on request.state
    for the route."""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    if not path.startswith("/api/"):
        return  # the UI's files: the app asks /api/me before it shows anything
    method = request.method
    rule = rule_for(method, path)
    if rule is not None and rule.who == "public":
        return
    c: Caller = await caller(request)
    request.state.caller = c
    request.state.reach = "all"
    if c.way == "dev":
        return
    if not c.user_id:  # the app's other way in names someone not linked to a core person (HomeHiro: HA's add-on)
        raise NotAllowed(f"You can't use {identity.app().title} yet: {not_linked(c.name)}")
    rights: PersonRights = await run_db(_rights_of, c)
    request.state.rights = rights
    if not rights.roles:
        raise NotAllowed(f"You can't use {identity.app().title} yet: the owner hasn't given you a role.")
    if rights.owner or (rule is not None and rule.who == "signed_in"):
        return
    if rule is None or rule.who == "owner":
        raise NotAllowed("Only an owner can do this.")
    got = reach_of(rule, method, rights.roles)
    if got == "own" and await _theirs(request, rule, c.user_id):
        request.state.reach = "own"
        return
    if got != "all":
        raise NotAllowed(_refusal(rule, method))
