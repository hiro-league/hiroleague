"""Every error turns into its HTTP answer in one place (errors.py), whatever route raised it; a caught error is logged
once, the expected ones in one line."""

import asyncio
import logging
import sqlite3

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from hiro_extension_kit import errors


class SystemError_(errors.OutsideError):
    """An outside system's error, as an app's client for it defines one."""


class Refused(SystemError_):
    status = 400


def test_each_error_has_its_status():
    router = APIRouter()
    raised = {"invalid": errors.Invalid("a rule"), "missing": errors.NotFound("no such thing"),
              "refused": Refused("config/x: bad name"), "outside": SystemError_("Cannot reach it"),
              "unknown": SystemError_("address unknown", 503), "busy": errors.Busy("running"),
              "conflict": errors.Conflict("changed"), "away": errors.Unavailable("not set up"),
              "who": errors.NotSignedIn("sign in"), "no": errors.NotAllowed("not for you")}

    @router.get("/{what}")
    def fail(what: str):
        raise raised[what]

    app = FastAPI()
    app.include_router(router)
    errors.install(app)
    client = TestClient(app)
    got = {what: (r.status_code, r.json()["detail"]) for what in raised if (r := client.get(f"/{what}"))}
    assert got == {"invalid": (400, "a rule"), "missing": (404, "no such thing"), "refused": (400, "config/x: bad name"),
                   "outside": (502, "Cannot reach it"), "unknown": (503, "address unknown"), "busy": (409, "running"),
                   "conflict": (409, "changed"), "away": (503, "not set up"), "who": (401, "sign in"),
                   "no": (403, "not for you")}


def test_failed_logs_an_expected_error_in_one_line_and_anything_else_with_its_traceback(caplog):
    log = logging.getLogger("testapp.test")
    with caplog.at_level(logging.WARNING, "testapp.test"):
        errors.failed(log, "Sync", SystemError_("Cannot reach Home Assistant"))
        try:
            {}["area"]
        except KeyError as exc:
            errors.failed(log, "Sync", exc)
    expected, unexpected = caplog.records
    assert (expected.levelname, expected.getMessage(), expected.exc_info) == ("WARNING", "Sync: Cannot reach Home Assistant", None)
    assert unexpected.levelname == "ERROR" and unexpected.getMessage() == "Sync: KeyError: 'area'"
    assert unexpected.exc_info and unexpected.exc_info[0] is KeyError


def test_a_locked_database_is_expected():
    locked = OperationalError("UPDATE x", {}, sqlite3.OperationalError("database is locked"))
    other = OperationalError("SELECT x", {}, sqlite3.OperationalError("no such table: x"))
    assert errors.expected(locked) and not errors.expected(other)


def test_guarded_callbacks_log_and_never_raise(caplog):
    log = logging.getLogger("testapp.test")

    @errors.guarded(log, "MQTT message")
    def on_message(payload: bytes) -> str:
        return payload.decode()["x"]  # a bug

    @errors.guarded(log, "WhatsApp paired")
    async def on_paired() -> None:
        raise SystemError_("away")

    with caplog.at_level(logging.WARNING, "testapp.test"):
        assert on_message(b"{}") is None
        assert asyncio.run(on_paired()) is None
    bug, expected = caplog.records
    assert bug.levelname == "ERROR" and bug.getMessage().startswith("MQTT message: TypeError")
    assert expected.levelname == "WARNING" and expected.getMessage() == "WhatsApp paired: away"


def test_translate_turns_an_unreadable_answer_into_the_systems_error():
    with pytest.raises(SystemError_, match=r"Gemini: an answer the app can't read \(KeyError: 'candidates'\)") as info:
        with errors.translate(SystemError_, "Gemini: an answer the app can't read"):
            _ = {}["candidates"]
    assert isinstance(info.value.__cause__, KeyError) and info.value.status == 502


def test_unexpected_errors_are_a_500_that_names_the_request_and_a_busy_database_a_503(caplog):
    router = APIRouter()

    @router.get("/bug")
    def bug():
        return {}["x"]

    @router.get("/locked")
    def locked():
        raise OperationalError("UPDATE x", {}, sqlite3.OperationalError("database is locked"))

    app = FastAPI()
    app.include_router(router)
    errors.install(app)
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.WARNING, "testapp.errors"):
        r = client.get("/bug")
        assert r.status_code == 500 and r.json()["detail"] == (
            "TestApp hit an unexpected error (KeyError). The details are in testapp-errors.log.")
        r = client.get("/locked")
        assert r.status_code == 503 and "database is busy" in r.json()["detail"]
    assert "GET /bug failed: KeyError" in caplog.text and "GET /locked: the database is busy" in caplog.text


def test_a_failing_reaction_to_a_failure_does_not_end_the_retries(caplog):
    """HAGateway.failed() runs its disconnect hooks; one raising used to end run()'s retries for good."""
    from hiro_channel_sdk.workers import Worker

    class Flaky(Worker):
        name = "flaky"
        retry_first = retry_most = 0.01
        runs = 0

        async def run(self) -> None:
            self.runs += 1
            raise SystemError_("away")

        def failed(self, exc: Exception, retry_in: float) -> None:
            raise RuntimeError("a hook broke")

    async def main() -> Flaky:
        w = Flaky()
        w.start()
        await asyncio.sleep(0.2)
        await w.stop()
        return w

    with caplog.at_level(logging.ERROR, "hiro.workers"):
        w = asyncio.run(main())
    assert w.runs >= 3 and w.problem == "away"
    assert "flaky: reacting to its failure: RuntimeError: a hook broke" in caplog.text
