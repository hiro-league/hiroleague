"""Phase 6: the admin asks for its own sign-in before any /api route but /api/auth/*."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from hirocli.admin_svelte.routes import auth as auth_routes
from hirocli.admin_svelte.routes.auth import RequireSignIn, auth_router
from hirocli.domain.admin_sign_in import give_sign_in
from hirocli.domain.people import add_person


def _app(workspace: Path) -> FastAPI:
    app = FastAPI()
    app.state.ctx = SimpleNamespace(workspace_path=workspace, config=SimpleNamespace(admin_port=18083))
    app.add_middleware(RequireSignIn, ctx=app.state.ctx)
    api = APIRouter(prefix="/api")
    api.include_router(auth_router)

    @api.get("/secret")
    async def secret() -> str:
        return "family"

    app.include_router(api)

    @app.get("/")
    async def page() -> dict:
        return {"page": "the admin's static files"}

    return app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    auth_routes._failures.clear()
    michel = add_person(tmp_path, name="Michel", role_id="owner")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    return TestClient(_app(tmp_path))


def test_api_needs_a_sign_in_but_the_page_and_auth_dont(client: TestClient) -> None:
    assert client.get("/api/secret").status_code == 401
    assert client.get("/").status_code == 200
    me = client.get("/api/auth/me").json()
    assert me == {
        "signed_in": False,
        "person": None,
        "role_name": None,
        "owner": False,
        "core_keys": [],
        "levels": {},
        "can_open_settings": False,
        "anyone_signs_in": True,
        "sign_in_offers": [],
        "place": None,  # the tests name no switchboard: as live
    }


def test_signing_in_opens_the_api_and_signing_out_closes_it(client: TestClient) -> None:
    wrong = client.post("/api/auth/sign-in", json={"sign_in": "michel", "password": "wrong horse"})
    assert wrong.status_code == 401 and wrong.json()["detail"] == "Wrong name or password."

    ok = client.post("/api/auth/sign-in", json={"sign_in": "Michel", "password": "correct horse"})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"]
    # Phase 8: Lax, so an extension's site can send the browser here
    assert "hiro_admin_18083=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # plain http on this machine
    assert client.get("/api/secret").json() == "family"
    assert client.get("/api/auth/me").json()["person"]["name"] == "Michel"

    client.post("/api/auth/sign-out")
    assert client.get("/api/secret").status_code == 401


def test_the_cookie_is_secure_behind_https(client: TestClient) -> None:
    ok = client.post(
        "/api/auth/sign-in",
        json={"sign_in": "michel", "password": "correct horse"},
        headers={"x-forwarded-proto": "https"},
    )
    assert "Secure" in ok.headers["set-cookie"]


def test_too_many_wrong_passwords_wait(client: TestClient) -> None:
    for _ in range(10):
        client.post("/api/auth/sign-in", json={"sign_in": "michel", "password": "wrong horse"})
    blocked = client.post("/api/auth/sign-in", json={"sign_in": "michel", "password": "correct horse"})
    assert blocked.status_code == 429


# ---- a test environment's quick sign-in (its switchboard): no sign-in screen


def _named_board(tmp_path: Path, monkeypatch, sign_in: dict) -> None:
    import json

    from hiro_commons import switchboard

    path = tmp_path / "switchboard.json"
    path.write_text(json.dumps({"place": "env2", "preset": "Safe", "modes": {}, "sign_in": sign_in}), encoding="utf-8")
    monkeypatch.setattr(switchboard, "_board", switchboard.read({switchboard.ENV: str(path)}))


def test_with_sign_in_off_in_a_test_environment_everyone_is_the_owner(client: TestClient, tmp_path, monkeypatch) -> None:
    _named_board(tmp_path, monkeypatch, {"mode": "off"})
    me = client.get("/api/auth/me").json()
    assert me["signed_in"] is True and me["person"]["name"] == "Michel" and me["can_open_settings"] is True
    assert client.get("/api/secret").status_code == 200  # no cookie, no sign-in screen


def test_as_a_person_everyone_is_them_with_their_role(client: TestClient, tmp_path, monkeypatch) -> None:
    kid = add_person(tmp_path, name="Mark", role_id="kid")
    _named_board(tmp_path, monkeypatch, {"mode": "as", "person": kid.person_id, "name": "Mark"})
    me = client.get("/api/auth/me").json()
    assert me["person"]["name"] == "Mark" and me["can_open_settings"] is False
    assert client.get("/api/secret").status_code == 403  # a kid's role doesn't open the settings


def test_as_someone_not_in_the_family_list_people_sign_in(client: TestClient, tmp_path, monkeypatch) -> None:
    _named_board(tmp_path, monkeypatch, {"mode": "as", "person": "gone", "name": "Gone"})
    assert client.get("/api/auth/me").json()["signed_in"] is False
    assert client.get("/api/secret").status_code == 401
