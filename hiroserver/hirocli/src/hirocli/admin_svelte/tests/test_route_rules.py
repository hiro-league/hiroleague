"""Permissions phase 2: every admin route has a rule, and a person reaches only what their roles' core permissions name.

The contract: a route with no rule fails here (at run time it answers the owner only); a rule names only declared core
features, and each of its routes' methods needs an action one of them declares.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from hiro_commons.rules import rule_for

import hirocli.admin_svelte.routes as routes_pkg
from hirocli.admin_svelte.route_rules import ADMIN_RULES, BY_ID, needed, refusal, require_rule, rule_allows
from hirocli.admin_svelte.routes import auth as auth_routes
from hirocli.admin_svelte.routes.auth import RequireSignIn
from hirocli.domain.access import CORE_SOURCE, AdminAccess, admin_access, set_rights
from hirocli.domain.admin_sign_in import give_sign_in
from hirocli.domain.people import add_person


def _every_admin_route() -> list[tuple[str, str]]:
    """Every (method, path) of every router in admin_svelte/routes, mounted under /api as api.py does, whether the
    feature ledger mounts it today or not."""
    app = FastAPI()
    api = APIRouter(prefix="/api")
    for info in pkgutil.iter_modules(routes_pkg.__path__):
        module = importlib.import_module(f"{routes_pkg.__name__}.{info.name}")
        for value in vars(module).values():
            if isinstance(value, APIRouter):
                api.include_router(value)
    app.include_router(api)
    out = {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods if m != "HEAD"}
    return sorted(out, key=lambda x: (x[1], x[0]))


EVERY_ROUTE = _every_admin_route()


def test_the_real_router_checks_every_route() -> None:
    """api.py's router, as the admin mounts it, runs the rule on every route: the sign-in middleware refuses no one
    by their roles, so this dependency is the only gate."""
    from hirocli.admin_svelte.api import api_router

    unchecked = [r.path for r in api_router.routes
                 if isinstance(r, APIRoute) and not any(d.dependency is require_rule for d in r.dependencies)]
    assert [r for r in api_router.routes if isinstance(r, APIRoute)] and unchecked == []


def test_every_route_is_found() -> None:
    paths = {p for _, p in EVERY_ROUTE}
    assert len(EVERY_ROUTE) > 150
    assert "/api/memory/list" in paths and "/api/graph-runs/{run_id}" in paths and "/api/gateways" in paths


@pytest.mark.parametrize(("method", "path"), EVERY_ROUTE)
def test_every_route_has_a_rule(method: str, path: str) -> None:
    rule = rule_for(ADMIN_RULES, method, path)
    assert rule is not None, f"{method} {path} has no rule in admin_svelte/route_rules.py"
    for f in rule.features:
        assert f in BY_ID, f"{method} {path}: {f} is no core feature"
    if rule.who == "features":
        actions = {needed(rule, f, method) in {r.id for r in BY_ID[f].rights} for f in rule.features}
        assert True in actions, f"{method} {path}: none of {rule.features} declares what it needs"


def test_the_admins_pages_name_the_cores_features() -> None:
    """The admin's frontend names the core's features by hand (lib/shell/core-access.ts): the same ids, in order."""
    import re

    ts = Path(__file__).parents[6] / "admin_frontend" / "src" / "lib" / "shell" / "core-access.ts"
    listed = re.search(r"CORE_FEATURES = \[(.*?)\] as const", ts.read_text(encoding="utf-8"), re.S)
    assert listed is not None
    assert re.findall(r"'([^']+)'", listed.group(1)) == list(BY_ID)


def _access(*keys: str) -> AdminAccess:
    return AdminAccess(owner=False, keys=list(keys), levels={}, roles={"adult": list(keys)})


def _allows(access: AdminAccess, method: str, path: str) -> bool:
    return rule_allows(access, rule_for(ADMIN_RULES, method, path), method)


def test_logs_see_reaches_the_logs_and_nothing_else() -> None:
    """The phase's done-when: an Adult given Logs: See reaches Logs and nothing else."""
    adult = _access("logs.see")
    reached = {(m, p) for m, p in EVERY_ROUTE if _allows(adult, m, p)}
    assert ("GET", "/api/logs/stories") in reached and ("POST", "/api/logs/tail") in reached
    shell = {("GET", "/api/config"), ("GET", "/api/runtime/status"), ("GET", "/api/events/status")}
    signing_in = {(m, p) for m, p in reached if p.startswith("/api/auth/") or p == "/api/apps"}
    elsewhere = reached - shell - signing_in - {(m, p) for m, p in reached if p.startswith("/api/logs/")}
    # the devices' names the Logs filters show
    assert elsewhere == {("GET", "/api/devices")}
    assert not _allows(adult, "POST", "/api/workspaces/open-folder")  # any folder on the server's screen: the owner's
    assert not _allows(adult, "POST", "/api/logs/clear")  # logs has no change: the owner's
    assert not _allows(adult, "POST", "/api/graph-runs/tail") and not _allows(adult, "GET", "/api/ai/usage")
    assert not _allows(adult, "GET", "/api/people") and not _allows(adult, "PUT", "/api/roles/{role_id}/rights/{source}")


def test_their_own_things_open_no_admin_route() -> None:
    kid = _access("conversations.see:own", "memories.see:own", "assistant.talk")
    assert not any(_allows(kid, m, p) for m, p in EVERY_ROUTE if not p.startswith("/api/auth/") and p != "/api/apps")
    everyone = _access("conversations.see")
    assert _allows(everyone, "GET", "/api/chat-channels/{channel_id}/messages")
    assert not _allows(everyone, "POST", "/api/chat-channels/{channel_id}/messages/send")  # the owner's until phase 3


def test_a_change_needs_the_change_and_the_owner_has_everything() -> None:
    assert _allows(_access("ai.profiles.see"), "GET", "/api/ai/profiles")
    assert not _allows(_access("ai.profiles.see"), "POST", "/api/ai/try")
    assert _allows(_access("ai.profiles.change"), "POST", "/api/ai/try")
    assert not _allows(_access("ai.profiles.change"), "POST", "/api/providers")  # keys are ai.providers'
    owner = AdminAccess(owner=True, keys=[], levels={}, roles={"owner": []})
    assert all(_allows(owner, m, p) for m, p in EVERY_ROUTE)
    assert not rule_allows(_access("logs.see"), None, "GET")  # a route with no rule: the owner only


def test_a_refusal_names_the_permission() -> None:
    rule = rule_for(ADMIN_RULES, "POST", "/api/graph-runs/tail")
    assert refusal(rule, "POST") == "Your roles don't include Graph runs; ask the owner to give it on People → Roles."
    assert refusal(rule_for(ADMIN_RULES, "POST", "/api/ai/try"), "POST").startswith("Your roles don't include Profiles: Change")
    assert refusal(None, "GET") == "Only an owner can do this."


# Through the sign-in middleware and the dependency, as admin/run.py and api.py wire them


class _Ctx:
    def __init__(self, workspace: Path) -> None:
        self.workspace_path = str(workspace)
        self.config = type("Cfg", (), {"admin_port": 18083})()
        self.extension_manager = None


def _app(workspace: Path) -> FastAPI:
    app = FastAPI()
    app.state.ctx = _Ctx(workspace)
    app.add_middleware(RequireSignIn, ctx=app.state.ctx)
    api = APIRouter(prefix="/api", dependencies=[Depends(require_rule)])
    api.include_router(auth_routes.auth_router)

    @api.get("/logs/stories")
    async def stories() -> str:
        return "stories"

    @api.get("/graph-runs/{run_id}")
    async def run(run_id: str) -> str:
        return run_id

    @api.get("/unruled")
    async def unruled() -> str:
        return "owner"

    app.include_router(api)
    return app


def test_an_adult_given_logs_see_through_the_admin(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    auth_routes._failures.clear()
    joe = add_person(tmp_path, name="Joe", role_id="adult")
    give_sign_in(tmp_path, joe.person_id, sign_in="joe", password="adult password")
    set_rights(tmp_path, "adult", CORE_SOURCE, ["logs.see"])
    assert admin_access(tmp_path, ["adult"]).opens_admin
    client = TestClient(_app(tmp_path))
    assert client.post("/api/auth/sign-in", json={"sign_in": "joe", "password": "adult password"}).status_code == 200
    assert client.get("/api/logs/stories").json() == "stories"
    with caplog.at_level(logging.WARNING, logger="ADMIN.RULES"):
        refused = client.get("/api/graph-runs/r1")
    assert any(r.levelno == logging.WARNING and "Admin route refused" in r.getMessage() and "Joe" in r.getMessage()
               for r in caplog.records)
    assert refused.status_code == 403 and refused.json()["detail"].startswith("Your roles don't include Graph runs")
    assert client.get("/api/unruled").status_code == 403
    me = client.get("/api/auth/me").json()
    assert me["can_open_settings"] and me["levels"]["logs"] == "see" and me["levels"]["logs.runs"] == "no"
