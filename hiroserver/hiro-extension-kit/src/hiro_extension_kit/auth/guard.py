"""The check every API request passes first: who is asking (api.py `caller`), and whether their role has the right
the route needs (the app's rules, `Extension.rules`: rules.py says what each kind means; access.py the rights per
role, set in HiroLeague).

The owner has everything, and so does everyone with sign-in off (AUTH=off, a dev copy).
"""

from fastapi import Request

from .. import identity
from ..db import run_db
from ..errors import NotAllowed
from ..extension import ext
from .models import AppUser, Role
from .access import OWNER, SEE, can
from .api import caller, seen
from .identity import Caller
from .rules import Rule


def _matches(rule: Rule, method: str, path: str) -> bool:
    if rule.methods and method not in rule.methods:
        return False
    return path == rule.path or path.startswith(rule.path + "/")


def rule_for(method: str, path: str) -> Rule | None:
    """The rule for a route (its path as declared, e.g. /api/service-status/alerts/{alert_id}), or None."""
    method = "GET" if method == "HEAD" else method
    return next((r for r in ext().rules if _matches(r, method, path)), None)


def needed(rule: Rule, feature: str, method: str) -> str:
    """The right a route needs in one of its features (the rule's own, else by method)."""
    if rule.right:
        return rule.right
    if method in ("GET", "HEAD"):
        return SEE
    ids = [r.id for r in ext().by_id[feature].rights]
    if method == "DELETE" and "delete" in ids:
        return "delete"
    return next((r for r in ids if r != SEE), SEE)


def allowed(rule: Rule, method: str, role_id: str | None, rights: list[str]) -> bool:
    """Whether a role may call a route with this rule (for rules that name features): the right in any of them."""
    return any(can(role_id, rights, f, needed(rule, f, method)) for f in rule.features)


def _refusal(rule: Rule, method: str) -> str:
    by_id = ext().by_id
    wanted = []
    for f in rule.features:
        right = needed(rule, f, method)
        name = next((r.name for r in by_id[f].rights if r.id == right), right)
        wanted.append(by_id[f].name if right == SEE else f"{by_id[f].name}: {name}")
    if all(needed(rule, f, method) == SEE for f in rule.features):
        return f"Your role doesn't include {' or '.join(wanted)}."
    return f"Your role doesn't have the right for this ({' or '.join(wanted)}); ask the owner to give it in HiroLeague."


def _user_and_role(session, c: Caller) -> tuple[AppUser | None, Role | None]:
    # a signed-in person may reach a page before /api/me made their row: make it now
    u = session.get(AppUser, c.user_id) or seen(session, c)
    return u, (session.get(Role, u.role_id) if u and u.role_id and not u.denied else None)


async def guard(request: Request) -> None:
    """A dependency of every route (the app's app.py). Keeps the caller on request.state.caller for the route."""
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
    if c.way == "dev":
        return
    user, role = await run_db(_user_and_role, c)
    if user is None or role is None:
        raise NotAllowed(f"You can't use {identity.app().title} yet: the owner hasn't given you a role.")
    if role.id == OWNER or (rule is not None and rule.who == "signed_in"):
        return
    if rule is None or rule.who == "owner":
        raise NotAllowed("Only an owner can do this.")
    if not allowed(rule, method, role.id, role.rights):
        raise NotAllowed(_refusal(rule, method))
