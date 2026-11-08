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
    async def secret() -> dict:
        return {"ok": True, "error": None, "data": "family"}

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
    me = client.get("/api/auth/me").json()["data"]
    assert me == {"signed_in": False, "person": None, "anyone_signs_in": True}


def test_signing_in_opens_the_api_and_signing_out_closes_it(client: TestClient) -> None:
    wrong = client.post("/api/auth/sign-in", json={"sign_in": "michel", "password": "wrong horse"})
    assert wrong.status_code == 401 and wrong.json()["error"] == "Wrong name or password."

    ok = client.post("/api/auth/sign-in", json={"sign_in": "Michel", "password": "correct horse"})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"]
    assert "hiro_admin_18083=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Secure" not in cookie  # plain http on this machine
    assert client.get("/api/secret").json()["data"] == "family"
    assert client.get("/api/auth/me").json()["data"]["person"]["name"] == "Michel"

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
