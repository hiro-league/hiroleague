"""Phase 8: one sign-in for HiroLeague and its extensions' sites.

A role that doesn't open HiroLeague's settings signs in for the apps only; an extension's site gets
signed-in browsers back with a one-time code it redeems over its connection (auth.code); an offered
sign-in (Home Assistant's login) is started and finished by the extension that offers it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from hiro_channel_sdk.constants import METHOD_SIGN_IN_FINISH, METHOD_SIGN_IN_START
from hiro_channel_sdk.extension import ExtensionRequestError

from hirocli.admin_svelte.routes import auth as auth_routes
from hirocli.admin_svelte.routes.auth import RequireSignIn, auth_router
from hirocli.domain.admin_sign_in import give_sign_in
from hirocli.domain.people import PeopleError, add_person, list_roles, set_role_admin
from hirocli.runtime import sign_in_for_extensions as sign_in
from hirocli.runtime.request_handler import RequestRefused

HOME_INFO = {
    "name": "home",
    "offers": {
        "can_do": [{"kind": "sign_in", "id": "home_assistant", "label": "Home Assistant"}],
        "shows": [{"kind": "site", "title": "Home", "icon": "house", "url": "http://homehiro.local/x", "roles": []}],
    },
}


class FakeExtensions:
    """The running server's ExtensionManager, as far as the sign-in routes use it."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, dict[str, Any]]] = []
        self.finish_answer: dict[str, Any] | Exception = {}

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {"ext-home": {"name": "home", "info": HOME_INFO}}

    async def request(self, extension_id: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.asked.append((extension_id, method, dict(params or {})))
        if method == METHOD_SIGN_IN_START:
            return {"url": f"http://ha.local/auth/authorize?state={params['state']}"}
        if method == METHOD_SIGN_IN_FINISH:
            if isinstance(self.finish_answer, Exception):
                raise self.finish_answer
            return self.finish_answer
        raise AssertionError(method)


def _app(workspace: Path, extensions: FakeExtensions) -> FastAPI:
    app = FastAPI()
    app.state.ctx = SimpleNamespace(
        workspace_path=workspace, config=SimpleNamespace(admin_port=18083), extension_manager=extensions
    )
    app.add_middleware(RequireSignIn, ctx=app.state.ctx)
    api = APIRouter(prefix="/api")
    api.include_router(auth_router)

    @api.get("/secret")
    async def secret() -> dict:
        return {"ok": True, "error": None, "data": "settings"}

    app.include_router(api)
    return app


@pytest.fixture
def family(tmp_path: Path) -> dict[str, Any]:
    auth_routes._failures.clear()
    sign_in.CODES.__init__()
    michel = add_person(tmp_path, name="Michel", role_id="owner")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    mark = add_person(tmp_path, name="Mark", role_id="kid")
    give_sign_in(tmp_path, mark.person_id, sign_in="mark", password="kid password")
    extensions = FakeExtensions()
    client = TestClient(_app(tmp_path, extensions), follow_redirects=False)
    return {"path": tmp_path, "michel": michel, "mark": mark, "ext": extensions, "client": client}


def _sign_in(client: TestClient, name: str, password: str) -> None:
    assert client.post("/api/auth/sign-in", json={"sign_in": name, "password": password}).status_code == 200


def test_only_the_owner_opens_the_settings_by_default(family: dict[str, Any]) -> None:
    roles = {r.role_id: r.admin for r in list_roles(family["path"])}
    assert roles == {"owner": True, "adult": False, "kid": False}
    with pytest.raises(PeopleError):
        set_role_admin(family["path"], "owner", False)


def test_a_kid_signs_in_for_the_apps_only(family: dict[str, Any]) -> None:
    client = family["client"]
    _sign_in(client, "mark", "kid password")
    refused = client.get("/api/secret")
    assert refused.status_code == 403 and refused.json()["error"] == "Your role doesn't open HiroLeague's settings."
    me = client.get("/api/auth/me").json()["data"]
    assert me["can_open_settings"] is False and me["role_name"] == "Kid"
    apps = client.get("/api/apps").json()["data"]["apps"]
    assert apps == [{"extension": "home", "title": "Home", "icon": "house", "url": "http://homehiro.local", "online": True}]

    set_role_admin(family["path"], "kid", True)
    assert client.get("/api/secret").json()["data"] == "settings"


def test_the_sign_in_page_lists_the_offered_sign_ins(family: dict[str, Any]) -> None:
    me = family["client"].get("/api/auth/me").json()["data"]
    assert me["sign_in_offers"] == [{"id": "home_assistant", "label": "Home Assistant", "extension": "home"}]


def test_a_signed_out_browser_goes_to_the_sign_in_page(family: dict[str, Any]) -> None:
    r = family["client"].get("/api/auth/for/home", params={"next": "/people"})
    assert r.status_code == 303 and r.headers["location"] == "/sign-in?for=home&next=%2Fpeople"


def test_a_signed_in_browser_goes_back_with_a_code_the_extension_redeems_once(family: dict[str, Any]) -> None:
    client = family["client"]
    _sign_in(client, "mark", "kid password")
    r = client.get("/api/auth/for/home", params={"next": "/myroom?x=1"})
    back = urlsplit(r.headers["location"])
    assert r.status_code == 303 and f"{back.scheme}://{back.netloc}{back.path}" == "http://homehiro.local/api/auth/hiro"
    query = parse_qs(back.query)
    assert query["next"] == ["/myroom?x=1"]
    code = query["code"][0]

    other = SimpleNamespace(
        msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-other")),
        server_ctx=SimpleNamespace(workspace_path=family["path"], extension_manager=None),
    )
    with pytest.raises(RequestRefused):  # only the extension it was made for
        _run(sign_in.handle_auth_code({"code": code}, other))

    ctx = SimpleNamespace(
        msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-home")),
        server_ctx=SimpleNamespace(workspace_path=family["path"], extension_manager=None),
    )
    who = _run(sign_in.handle_auth_code({"code": code}, ctx))
    assert who == {"person_id": family["mark"].person_id, "name": "Mark", "role_id": "kid", "role_name": "Kid"}
    with pytest.raises(RequestRefused):  # one use
        _run(sign_in.handle_auth_code({"code": code}, ctx))


def test_a_next_off_the_site_goes_to_its_start(family: dict[str, Any]) -> None:
    client = family["client"]
    _sign_in(client, "michel", "correct horse")
    r = client.get("/api/auth/for/home", params={"next": "//evil.example/x"})
    assert parse_qs(urlsplit(r.headers["location"]).query)["next"] == ["/"]


def test_signing_in_with_home_assistant_through_the_extension(family: dict[str, Any]) -> None:
    client, ext = family["client"], family["ext"]
    start = client.get("/api/auth/with/home_assistant", params={"for": "home", "next": "/people"})
    assert start.status_code == 303 and start.headers["location"].startswith("http://ha.local/auth/authorize")
    _, method, params = ext.asked[-1]
    assert method == METHOD_SIGN_IN_START
    assert params["client_id"] == "http://testserver/" and params["redirect_uri"] == "http://testserver/api/auth/with/callback"

    ext.finish_answer = {"person_id": family["mark"].person_id}
    done = client.get("/api/auth/with/callback", params={"code": "ha-code", "state": params["state"]})
    assert done.status_code == 303 and done.headers["location"] == "/api/auth/for/home?next=%2Fpeople"
    assert ext.asked[-1][1] == METHOD_SIGN_IN_FINISH and ext.asked[-1][2]["code"] == "ha-code"
    assert client.get("/api/auth/me").json()["data"]["person"]["name"] == "Mark"

    again = client.get("/api/auth/with/callback", params={"code": "ha-code", "state": params["state"]})
    assert "signin_error" in again.headers["location"]  # a state works once


def test_an_unlinked_home_assistant_user_is_told_why(family: dict[str, Any]) -> None:
    client, ext = family["client"], family["ext"]
    client.get("/api/auth/with/home_assistant", params={"next": "/"})
    state = ext.asked[-1][2]["state"]
    ext.finish_answer = ExtensionRequestError("not_linked", "Your Home Assistant user isn't linked to anyone.")
    r = client.get("/api/auth/with/callback", params={"code": "c", "state": state})
    assert parse_qs(urlsplit(r.headers["location"]).query)["signin_error"] == [
        "Your Home Assistant user isn't linked to anyone."
    ]
    assert client.get("/api/auth/me").json()["data"]["signed_in"] is False


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)
