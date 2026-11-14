"""Asking HiroLeague's AI (llm/profiles.py) and the core's AI profiles for the pickers (llm/core_ai.py, GET /api/ai),
against a fake core (conftest `fake_ai`): what is sent, the answer as `Asked`, each of the core's refusals as the error
callers handle, the requests log kept from the answer, and the last list of profiles kept while the core is down.

Shared-code plan, step 1: HomeHiro's and NetHiro's tests each had this file; it is tested once, here. Which uses an
app declares stays in the app's tests."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hiro_channel_sdk import ExtensionRequestError
from sqlmodel import Session, select

from hiro_extension_kit import errors
from hiro_extension_kit.db import engine
from hiro_extension_kit.errors import Busy, Unavailable
from hiro_extension_kit.llm import LLMError, ai_api, core_ai, profiles, recorder
from hiro_extension_kit.llm.models import LlmRequest

_app = FastAPI()
_app.include_router(ai_api.router)
errors.install(_app)
client = TestClient(_app)
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


def run(coro):
    return asyncio.run(coro)


async def labelled(coro_fn):
    async with recorder.recording("Ask a camera", "Front door", "/streams", "cam1"):
        recorder.describe([("Question", None, "Who is there?")], ["The camera now", "Everyone's reference pictures"])
        return await coro_fn()


# --- asking ---


def test_an_answer_comes_back_as_asked_with_what_was_sent(fake_ai):
    a = run(labelled(lambda: profiles.ask(None, "ask", "Who is there?", [b"\xff\xd8one", b"\xff\xd8two"], SCHEMA, "high", True)))
    assert a == profiles.Asked('{"answer": "yes"}', 120, 100, 20, 1400, 0.0012, "google", "gemini-3.8-flash", "camera",
                               "Camera questions", False, [], None)
    (method, params), = fake_ai.asked
    assert method == "ai.ask"
    assert params == {"use": "ask", "prompt": "Who is there?", "schema": SCHEMA, "detail": "high", "local_only": True, "wait": True,
                      "pictures": [base64.b64encode(b"\xff\xd8one").decode(), base64.b64encode(b"\xff\xd8two").decode()],
                      "picture_labels": ["The camera now", "Everyone's reference pictures"],
                      "label": "cam1"}  # Phase 7b: the core's AI usage files it under the camera


def test_a_copys_own_profile_and_sound_and_an_apps_line_go_along(fake_ai):
    run(profiles.ask("camera-codex", "wakeword", "Said it?", [], SCHEMA, sound=b"RIFFxx", timeout=40, line="studyhiro"))
    (_m, params), = fake_ai.asked
    assert (params["profile"], params["wait"], params["timeout"]) == ("camera-codex", False, 40)
    assert params["sound"] == {"b64": base64.b64encode(b"RIFFxx").decode(), "mime": "audio/wav"}
    assert "pictures" not in params
    assert "label" not in params  # asked without a label ("Other"): none for AI usage either
    assert fake_ai.timeouts == [40 + profiles.SLACK]


def test_a_profile_from_before_the_import_is_asked_by_its_new_id(fake_ai):
    run(core_ai.read())  # the core lists hh-wake1: an app's old profile "wake1", imported
    run(profiles.ask("wake1", "wakeword", "Said it?", [], SCHEMA))
    assert fake_ai.asked[-1][1]["profile"] == "hh-wake1"
    assert profiles.exists("wake1") and profiles.exists("camera") and not profiles.exists("gone")


def test_every_profile_exists_while_no_list_was_ever_read():
    assert profiles.exists("anything")  # the core decides when asked


@pytest.mark.parametrize(("code", "error", "status", "says"), [
    ("budget", profiles.LimitReached, 429, "Not asked: Camera questions: its $1 for today is used"),
    ("busy", Busy, 409, "Camera questions: its $1 for today is used"),
    ("no_profile", Unavailable, 503, "No AI profile for Sorting sites: set one in HiroLeague's admin (Catalog → Uses)."),
    ("failed", LLMError, 502, "Camera questions: its $1 for today is used"),
    ("invalid", LLMError, 400, "HiroLeague refused the question: Camera questions: its $1 for today is used"),
    ("internal_error", LLMError, 502, "HiroLeague failed (internal_error): Camera questions: its $1 for today is used"),
])
def test_the_cores_refusals_are_the_errors_callers_handle(fake_ai, code, error, status, says):
    fake_ai.answers["ai.ask"] = ExtensionRequestError(code, "Camera questions: its $1 for today is used")
    with pytest.raises(error) as info:
        run(profiles.ask(None, "sites", "Who?", [], SCHEMA))
    assert type(info.value) is error and info.value.status == status and str(info.value) == says


def test_not_connected_asks_nothing_and_a_drop_or_a_timeout_says_so(fake_ai):
    fake_ai.connected = False
    with pytest.raises(Unavailable, match="isn't connected to HiroLeague"):
        run(profiles.ask(None, "ask", "Who?", [], SCHEMA))
    assert fake_ai.asked == []
    fake_ai.connected = True
    fake_ai.answers["ai.ask"] = ExtensionRequestError("not_connected", "connection closed")
    with pytest.raises(Unavailable, match="isn't connected to HiroLeague"):
        run(profiles.ask(None, "ask", "Who?", [], SCHEMA))
    fake_ai.answers["ai.ask"] = ExtensionRequestError("timeout", "no answer")
    with pytest.raises(LLMError, match="HiroLeague didn't answer in 315 s"):
        run(profiles.ask(None, "ask", "Who?", [], SCHEMA))


def test_an_answer_without_text_is_an_llm_error(fake_ai):
    fake_ai.answers["ai.ask"] = {"profile_id": "camera"}
    with pytest.raises(LLMError, match="no text"):
        run(profiles.ask(None, "ask", "Who?", [], SCHEMA))


# --- the requests log, from the answer ---


def test_the_requests_log_keeps_each_try_the_core_made_and_the_profiles_passed_over(fake_ai):
    fake_ai.answers["ai.ask"] = {
        "text": '{"answer": "no"}', "profile_id": "camera-codex", "profile_name": "Camera on Codex", "provider": "codex",
        "model": "gpt-6.1-sol", "plan": True, "ms": 9000, "tokens": 500, "tokens_in": 0, "tokens_out": 0, "cost": None,
        "estimate": 0.003, "notes": ["Local vision: not reachable"],
        "tries": [{"profile_id": "camera", "provider": "google", "model": "gemini-3.8-flash", "status": "failed",
                   "error": "503 overloaded", "ms": 800},
                  {"profile_id": "local", "provider": "lm_studio", "model": "qwen", "status": "skipped", "error": "not reachable", "ms": 0},
                  {"profile_id": "camera-codex", "provider": "codex", "model": "gpt-6.1-sol", "status": "ok", "ms": 9000}]}
    run(core_ai.read())
    run(labelled(lambda: profiles.ask(None, "ask", "Who is there?", [b"\xff\xd8x"], SCHEMA)))
    with Session(engine) as s:
        row = s.exec(select(LlmRequest)).one()
    assert (row.source, row.status, row.provider, row.model, row.profile, row.reply) == (
        "Ask a camera", "fell back", "codex", "gpt-6.1-sol", "Camera on Codex", '{"answer": "no"}')
    assert [(t["profile"], t["provider"], t["ok"], t["outcome"]) for t in row.tries] == [
        ("Local vision: not reachable", None, False, "passed over"),
        ("Camera questions", "google", False, "503 overloaded"),
        ("Camera on Codex", "codex", True, "answered")]


def test_a_question_asked_outside_any_label_is_kept_as_other_and_a_failure_is_kept_too(fake_ai):
    run(profiles.ask(None, "sites", "Sort these", [], SCHEMA))
    fake_ai.answers["ai.ask"] = ExtensionRequestError("failed", "every profile failed: Gemini 503")
    with pytest.raises(LLMError):
        run(profiles.ask(None, "sites", "Sort these", [], SCHEMA))
    with Session(engine) as s:
        rows = s.exec(select(LlmRequest).order_by(LlmRequest.at)).all()  # pyright: ignore[reportArgumentType]
    assert [(r.source, r.status) for r in rows] == [("Other", "ok"), ("Other", "failed")]
    assert rows[1].error == "every profile failed: Gemini 503" and rows[1].provider == "HiroLeague"


def test_a_question_the_core_never_asked_is_not_kept(fake_ai):
    fake_ai.answers["ai.ask"] = ExtensionRequestError("budget", "every profile is over its budget")
    with pytest.raises(profiles.LimitReached):
        run(labelled(lambda: profiles.ask(None, "ask", "Who?", [], SCHEMA)))
    with Session(engine) as s:
        assert s.exec(select(LlmRequest)).all() == []


# --- the core's profiles, for the pickers ---


def test_the_pickers_list_the_cores_profiles_with_each_use(fake_ai):
    r = client.get("/api/ai")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["reachable"] and d["error"] is None and d["core"] == "HiroLeague 0.2.0"
    cam = d["profiles"][0]
    assert {k: cam[k] for k in ("id", "name", "kind", "provider", "model", "model_id", "sent_to", "max_cost_day", "at_once",
                                "fallback_id", "chain", "spent_today", "asks_today", "this_hour")} == {
        "id": "camera", "name": "Camera questions", "kind": "api", "provider": "Google", "model": "Gemini 3.8 Flash",
        "model_id": "google:gemini-3.8-flash", "sent_to": "Google", "max_cost_day": 1.0, "at_once": 2,
        "fallback_id": "camera-codex", "chain": ["camera", "camera-codex"], "spent_today": 0.34, "asks_today": 41, "this_hour": 3}
    assert d["profiles"][2]["model"] == "gemini-3.5-flash-lite"  # no label: the model as the core names it
    uses = {u["id"]: u for u in d["uses"]}
    assert list(uses) == ["sites"]
    assert (uses["sites"]["profile_id"], uses["sites"]["chain"], uses["sites"]["needs"]) == (None, [], ["json"])


def test_the_list_is_read_again_only_when_old(fake_ai):
    client.get("/api/ai")
    client.get("/api/ai")
    assert [m for m, _p in fake_ai.asked] == ["ai.profiles"]
    core_ai._known.fetched_at = datetime.now(UTC) - core_ai.FRESH - timedelta(seconds=1)
    client.get("/api/ai")
    assert [m for m, _p in fake_ai.asked] == ["ai.profiles", "ai.profiles"]


def test_while_the_core_is_down_the_last_list_stays_with_when_it_was_read(fake_ai):
    first = client.get("/api/ai").json()
    fake_ai.connected = False
    core_ai._known = core_ai.Known()  # as after a restart: read back from the database
    d = client.get("/api/ai").json()
    assert not d["reachable"] and d["error"] == core_ai._no_core() and d["core"] is None
    assert d["fetched_at"] == first["fetched_at"] and [p["id"] for p in d["profiles"]] == ["camera", "camera-codex", "hh-wake1"]
    fake_ai.connected = True
    fake_ai.answers["ai.profiles"] = ExtensionRequestError("internal_error", "the preferences can't be read")
    d = client.get("/api/ai").json()
    assert not d["reachable"] and "the preferences can't be read" in d["error"] and len(d["profiles"]) == 3


def test_never_read_and_the_core_down_is_an_empty_list_that_says_why(fake_ai):
    fake_ai.connected = False
    d = client.get("/api/ai").json()
    assert (d["reachable"], d["fetched_at"], d["profiles"], d["error"]) == (False, None, [], core_ai._no_core())
    assert [u["profile_id"] for u in d["uses"]] == [None]


def test_the_cores_list_is_read_loosely():
    profiles_, uses = core_ai.parse({"profiles": {"a": {"id": "a", "name": "A", "kind": "local", "model": "ollama:llava",
                                                         "provider": "Ollama", "fallback_id": "b"}, "x": {"label": "no id"}},
                                     "uses": [{"use": "home:ask", "profile_id": "a"}, {"use": "write"}]})
    assert [(p.id, p.name, p.kind, p.sent_to, p.chain, p.model) for p in profiles_] == [
        ("a", "A", "local", "Ollama, in the house", ["a", "b"], "llava")]
    assert uses == {"ask": "a", "write": None}
    assert core_ai.parse("nonsense") == ([], {})
