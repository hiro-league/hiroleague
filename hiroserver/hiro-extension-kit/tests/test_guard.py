"""The check every API request passes (auth/guard.py): the rule a route gets, and roles get what they are given, no
more. Against the kit's test app (conftest.py `TEST_EXTENSION`, shaped like NetHiro's) and a fake core.

Shared-code plan, step 1: HomeHiro's, NetHiro's and TrainHiro's tests each had the generic half of this. What stays in
an app is its own rules (which right each of its routes needs); that every route of the app has a rule is the contract's
(contract.py `test_every_route_has_a_rule`).
"""

import asyncio

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from hiro_extension_kit import errors, family, testing
from hiro_extension_kit.auth import api, sessions
from hiro_extension_kit.auth.guard import KIT_RULES, allowed, guard, rule_for
from hiro_extension_kit.db import engine
from hiro_extension_kit.testing import join_family

ADULT = ["status.see", "logs.see"]  # System health to look at, and the logs
KID: list[str] = []


def test_the_kits_own_routes_come_before_the_apps_rules():
    """The app switcher's list (/api/apps) is everyone's with a role, whatever the app's rules say."""
    assert rule_for("GET", "/api/apps") is KIT_RULES[0]
    assert KIT_RULES[0].who == "signed_in"


def test_a_head_is_a_get_and_a_route_without_a_rule_has_none():
    assert rule_for("HEAD", "/api/logs") is rule_for("GET", "/api/logs")
    assert rule_for("GET", "/api/nowhere") is None
    assert rule_for("GET", "/api/logsx") is None  # a prefix is a whole path part, not any start


@pytest.mark.parametrize(("method", "path", "adult", "kid"), [
    ("GET", "/api/service-status", True, False),
    ("PUT", "/api/service-status/items/{item_id}", False, False),  # the feature's main right: Change checks
    ("GET", "/api/logs", True, False),
    ("GET", "/api/settings", False, False),
    ("PUT", "/api/ai/uses/{use}", False, False),
    ("GET", "/api/ai", True, False),  # read with either feature
])
def test_roles_reach_what_they_are_given(method, path, adult, kid):
    rule = rule_for(method, path)
    assert rule is not None and rule.who == "features"
    assert allowed(rule, method, "adult", ADULT) is adult
    assert allowed(rule, method, "kid", KID) is kid


def test_a_change_needs_its_own_right():
    """A route needs one right, not a whole "use": the feature's See plus that right is enough, and the feature's
    other rights aren't."""
    rule = rule_for("PUT", "/api/service-status/alerts/{alert_id}")
    assert rule is not None and rule.who == "features"
    assert allowed(rule, "PUT", "adult", ["status.see", "status.alerts"])
    assert not allowed(rule, "PUT", "adult", ["status.see", "status.checks", "status.network", "status.diagnose"])


def test_a_feature_without_see_is_read_with_any_of_its_rights():
    rule = rule_for("GET", "/api/settings")
    assert rule is not None
    assert allowed(rule, "GET", "adult", ["settings.change"]) and not allowed(rule, "GET", "adult", [])


def test_users_and_roles_are_the_owners():
    for method, path in [("GET", "/api/users"), ("PUT", "/api/users/{user_id}"), ("GET", "/api/roles")]:
        rule = rule_for(method, path)
        assert rule is not None and rule.who == "owner", path


# ---- through an app


def _pages() -> APIRouter:
    """A few of an app's own routes, each under one of the test app's rules."""
    r = APIRouter()

    @r.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @r.get("/api/status")
    def status() -> dict[str, bool]:
        return {"ok": True}

    @r.get("/api/settings")
    def settings() -> dict[str, bool]:
        return {"ok": True}

    @r.get("/api/apps")
    def apps() -> dict[str, bool]:
        return {"ok": True}

    return r


@pytest.fixture
def client(fake_core, monkeypatch):
    testing.auth(monkeypatch, True)
    app = FastAPI(dependencies=[Depends(guard)])
    app.include_router(api.router)
    app.include_router(_pages())
    errors.install(app)
    with TestClient(app) as c:
        yield c


def as_(person: dict) -> dict[str, str]:
    """A browser signed in as this core person (its session cookie, as /api/auth/hiro would set it)."""
    from sqlmodel import Session

    from hiro_extension_kit.auth.identity import Caller

    with Session(engine) as s:
        api.seen(s, Caller(person["person_id"], person["name"], "web", "Windows PC"))
        token = sessions.start(s, person["person_id"], "Windows PC")
    return {"Cookie": f"{sessions.COOKIE}={token}"}


def test_the_app_refuses_what_a_role_does_not_have(client, fake_core):
    assert client.get("/api/health").status_code == 200  # open to everyone
    assert client.get("/api/status").status_code == 401  # nobody known

    owner = as_(join_family(fake_core, "Owner", "owner"))
    adult_person = join_family(fake_core, "Adult", "adult")
    adult, kid = as_(adult_person), as_(join_family(fake_core, "Kid", "kid"))
    next(r for r in fake_core.roles if r["role_id"] == "adult")["rights"] = ADULT
    asyncio.run(family.sync())

    assert client.get("/api/status", headers=owner).status_code == 200
    assert client.get("/api/settings", headers=owner).status_code == 200
    assert client.get("/api/status", headers=adult).status_code == 200
    r = client.get("/api/settings", headers=adult)
    assert r.status_code == 403 and "Settings" in r.json()["detail"]
    assert client.get("/api/status", headers=kid).status_code == 403
    assert client.get("/api/apps", headers=kid).status_code == 200  # the kit's rule: anyone with a role

    client.put(f"/api/users/{adult_person['person_id']}", headers=owner, json={"denied": True})
    assert client.get("/api/status", headers=adult).status_code == 403  # No access applies at once


def test_someone_without_a_role_is_told_so(client, fake_core):
    """In the family list but with a role the app doesn't know yet (or none): refused, by name of the app."""
    stranger = as_(join_family(fake_core, "Guest", "adult"))
    from sqlmodel import Session, select

    from hiro_extension_kit.auth.models import AppUser

    with Session(engine) as s:
        for u in s.exec(select(AppUser)):
            u.role_id = None
            s.add(u)
        s.commit()
    r = client.get("/api/status", headers=stranger)
    assert r.status_code == 403 and r.json()["detail"] == "You can't use TestApp yet: the owner hasn't given you a role."


def test_a_changed_role_applies_at_once(client, fake_core):
    kid = as_(join_family(fake_core, "Kid", "kid"))
    assert client.get("/api/status", headers=kid).status_code == 403
    # the owner grants it in HiroLeague; the core says the family list changed and the app reads it again
    next(r for r in fake_core.roles if r["role_id"] == "kid")["rights"] = ["status.see"]
    asyncio.run(family.sync())
    assert client.get("/api/status", headers=kid).status_code == 200
