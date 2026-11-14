"""Logs → LLM requests (llm/recorder.py, llm/requests_api.py): every question sent to an LLM is kept, as sent and as
answered, with its labelled parts and pictures, each model asked, and what the app did with the answer.

Shared-code plan, step 1: HomeHiro's and NetHiro's tests each had this file; it is tested once, here."""

import asyncio
import io
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from hiro_extension_kit import errors
from hiro_extension_kit.db import engine
from hiro_extension_kit.llm import recorder, requests_api
from hiro_extension_kit.llm.models import LlmRequest

RULES = "Answer only with JSON."  # Phase 9b: a fixed rule part (was Ask a camera's, now HomeHiro's)

_app = FastAPI()
_app.include_router(requests_api.router)
errors.install(_app)
client = TestClient(_app)


def picture(w: int = 1280, h: int = 720) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), "gray").save(out, "JPEG")
    return out.getvalue()


def rows() -> list[LlmRequest]:
    with Session(engine) as session:
        return list(session.exec(select(LlmRequest)).all())


@pytest.fixture(autouse=True)
def _prune_each_time(monkeypatch):
    monkeypatch.setattr(recorder, "_pruned_at", None)


def ask(provider="gemini", fail: Exception | None = None, reply='{"light": "off"}', prompt="Is the lamp on?",
        jpeg: bytes | None = None, detail="medium") -> None:
    t = recorder.trying(provider, "gemini-3.8-flash", prompt, [jpeg] if jpeg else [], {"type": "object"}, detail, "low")
    if fail:
        t.failed(fail, 900)
    else:
        t.answered(reply, 1000, 20, 1200, 0.001)


def test_a_question_is_kept_with_its_parts_pictures_and_what_was_done():
    async def run():
        async with recorder.recording("Ask a camera", "Boys room light", "/streams", "cam2"):
            recorder.describe([("The question", "/streams", "Is the lamp on?"), ("TestApp (always)", None, RULES)],
                              ["The camera now"])
            recorder.asking("Camera questions")
            ask(prompt=f"Is the lamp on?\n\n{RULES}", jpeg=picture())
            recorder.outcome("Same as before: nothing recorded.")

    asyncio.run(run())
    [r] = rows()
    assert (r.source, r.task, r.camera, r.status, r.profile) == ("Ask a camera", "Boys room light", "cam2", "ok", "Camera questions")
    assert [p["label"] for p in r.parts] == ["The question", "TestApp (always)"]
    assert r.pictures == [{"label": "The camera now", "width": 1280, "height": 720, "size": r.pictures[0]["size"]}]
    assert r.reply == '{"light": "off"}' and r.outcome == "Same as before: nothing recorded."
    assert (r.tokens_in, r.tokens_out, r.cost, r.warning) == (1000, 20, 0.001, None)

    listed = client.get("/api/logs/llm").json()
    assert [x["id"] for x in listed["requests"]] == [r.id] and listed["disk"] > 0
    whole = client.get(f"/api/logs/llm/{r.id}").json()
    assert whole["prompt"].endswith(RULES) and whole["tries"][0]["outcome"] == "answered"
    got = client.get(f"/api/logs/llm/{r.id}/pictures/0")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/logs/llm/{r.id}/pictures/1").status_code == 404


def test_a_fallback_a_failure_and_a_profile_passed_over_are_all_shown():
    async def run():
        async with recorder.recording("Ask a camera", "Door"):
            recorder.passed_over("Local: not a local model")
            ask(fail=RuntimeError("too slow: no answer in 60 s"))
            ask()
        with pytest.raises(ValueError):
            async with recorder.recording("Ask now", "Door"):
                ask(reply="I can't help with that.")
                raise ValueError("The model's reply was not JSON")

    asyncio.run(run())
    fell, failed = sorted(rows(), key=lambda r: r.source)
    assert fell.status == "fell back"
    assert [(t["outcome"], t["ok"]) for t in fell.tries] == [
        ("passed over", False), ("too slow: no answer in 60 s", False), ("answered", True)]
    assert failed.status == "failed" and failed.error == "The model's reply was not JSON"
    assert failed.reply == "I can't help with that."  # kept as it came, to see why
    assert client.get("/api/logs/llm", params={"problems": True}).json()["requests"][0]["status"] in ("failed", "fell back")


def test_nothing_is_kept_when_no_model_was_asked_and_a_question_without_a_label_is_other():
    async def run():
        async with recorder.recording("Ask a camera", "Door"):
            recorder.passed_over("every profile reached its limit")
        t = recorder.trying("openai", "gpt-6-luna", "Hello", [], {}, None, "low")
        t.answered('{"text": "hi"}', 5, 2, 300)
        await recorder.done(t)

    asyncio.run(run())
    [r] = rows()
    assert (r.source, r.task, r.parts) == ("Other", "Asked without a label", [{"label": "The words", "link": None, "text": "Hello"}])


def test_words_added_on_the_way_get_a_part_of_their_own_and_unlabelled_words_are_one_part():
    req = recorder.Request("Try it", "x", parts=[{"label": "Try it", "link": None, "text": "Q"}])
    assert recorder._parts(req, "Q\n\nBe brief.")[-1]["text"] == "Be brief."
    assert recorder._parts(req, "Something else") == [{"label": "The words", "link": None, "text": "Something else"}]


def test_openais_low_detail_is_flagged_on_a_big_picture():
    asyncio.run(_one(lambda: ask(provider="openai", jpeg=picture(1712, 862), detail="medium")))
    [r] = rows()
    assert r.warning and "1712 × 862" in r.warning and "512" in r.warning


async def _one(fn) -> None:
    async with recorder.recording("Ask now", "x"):
        fn()


def test_old_requests_and_older_pictures_go():
    asyncio.run(_one(lambda: ask(jpeg=picture())))
    [r] = rows()
    with Session(engine) as session:
        recorder._prune(session, r.at + timedelta(days=recorder.PICTURE_DAYS, minutes=1))
        kept = session.get(LlmRequest, r.id)
        assert kept is not None and not kept.pictures_kept
    assert client.get(f"/api/logs/llm/{r.id}/pictures/0").status_code == 404
    with Session(engine) as session:
        recorder._pruned_at = None
        recorder._prune(session, r.at + timedelta(days=recorder.KEEP_DAYS, minutes=1))
    assert rows() == []


def test_the_list_finds_words_and_picks_what_asked():
    async def run():
        async with recorder.recording("Ask now", "Door", "/streams", "cam3"):
            ask(prompt="Is the front door open?")
        async with recorder.recording("Try it", "Profile"):
            ask(prompt="How many people?")

    asyncio.run(run())
    listed = client.get("/api/logs/llm", params={"camera": "cam3"}).json()
    assert [r["task"] for r in listed["requests"]] == ["Door"] and listed["cameras"] == ["cam3"]
    assert [r["task"] for r in client.get("/api/logs/llm", params={"q": "front door"}).json()["requests"]] == ["Door"]
    assert [r["task"] for r in client.get("/api/logs/llm", params={"source": "Try it"}).json()["requests"]] == ["Profile"]
    assert client.get("/api/logs/llm/nope").status_code == 404
