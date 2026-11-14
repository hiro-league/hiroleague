"""Settings → HiroLeague (hiroleague_api.py): the core's address, pairing and the test call, without a core.

The connection itself (pairing, signing in, both test calls over a real socket) is tested in HiroLeague's
repo (hirocli runtime/tests/test_extension_manager.py), against the same SDK client every app uses.

Shared-code plan, step 1: HomeHiro's, NetHiro's and TrainHiro's tests each had this file; it is tested once, here. What an
app declares to the core stays in its tests.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from hiro_extension_kit import errors, hiroleague_api, settings
from hiro_extension_kit.db import engine
from hiro_extension_kit.errors import Invalid
from hiro_extension_kit.hiroleague import URL_KEY, check_url, link

_app = FastAPI()
_app.include_router(hiroleague_api.router)
errors.install(_app)
client = TestClient(_app)


@pytest.fixture(autouse=True)
def _no_address():
    link.client.set_url("")
    yield
    link.client.set_url("")


def test_check_url_takes_only_websocket_addresses():
    assert check_url("  ws://127.0.0.1:18082 ") == "ws://127.0.0.1:18082"
    assert check_url("") == ""
    with pytest.raises(Invalid):
        check_url("http://127.0.0.1:18082")


def test_status_before_anything_is_set():
    r = client.get("/api/hiroleague")
    assert r.status_code == 200
    assert r.json()["url"] == ""


def test_saving_the_address_keeps_it_in_the_database():
    r = client.put("/api/hiroleague", json={"url": "ws://127.0.0.1:18082"})
    assert r.status_code == 200 and r.json()["url"] == "ws://127.0.0.1:18082"
    with Session(engine) as s:
        assert settings.get(s, URL_KEY) == "ws://127.0.0.1:18082"
    assert client.put("/api/hiroleague", json={"url": "http://nope"}).status_code == 400


def test_pairing_needs_an_address_and_a_code():
    assert client.post("/api/hiroleague/pair", json={"code": "123456"}).status_code == 400  # no address yet
    client.put("/api/hiroleague", json={"url": "ws://127.0.0.1:18082"})
    assert client.post("/api/hiroleague/pair", json={"code": "  "}).status_code == 400


def test_the_test_call_says_when_the_core_isnt_connected():
    r = client.post("/api/hiroleague/test")
    assert r.status_code == 400
    assert "didn't answer" in r.json()["detail"]
