"""Every page request is a story (stories.py, put on the app by errors.install): it continues the page's traceparent or
starts one, gives the id back, keeps it in a crashed route's line, and stamps it on the LLM request it records
(llm/recorder.py) and on the line of each outside call (calls.py)."""

import asyncio
import logging

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from hiro_commons.logging_foundation import story
from sqlmodel import Session, select

from hiro_extension_kit import calls, errors, identity
from hiro_extension_kit.db import engine
from hiro_extension_kit.llm import recorder
from hiro_extension_kit.llm.models import LlmRequest

STORY = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = f"00-{STORY}-00f067aa0ba902b7-01"

router = APIRouter()
seen: list[str | None] = []


@router.get("/where")
async def where() -> dict:
    seen.append(story.current_id())
    return {}


@router.get("/crash")
def crash() -> dict:
    raise KeyError("contract-story-crash")


@router.get("/ask")
async def asks() -> dict:
    async with recorder.recording("Ask now", "Is the lamp on?"):
        recorder.trying("gemini", "gemini-3.8-flash", "Is the lamp on?", [], {}, None, None).answered("no", 1, 1, 5)
    return {}


app = FastAPI()
app.include_router(router)
errors.install(app)
client = TestClient(app, raise_server_exceptions=False)


def test_a_request_continues_the_pages_story_and_names_it_in_its_answer():
    seen.clear()
    r = client.get("/where", headers={"traceparent": PARENT})
    assert seen == [STORY]
    assert r.headers["traceparent"].split("-")[1] == STORY


def test_a_request_with_no_story_starts_one():
    seen.clear()
    first, second = client.get("/where"), client.get("/where")
    ids = [first.headers["traceparent"].split("-")[1], second.headers["traceparent"].split("-")[1]]
    assert seen == ids and ids[0] != ids[1] and len(ids[0]) == 32


def test_a_crashed_route_logs_with_the_requests_story():
    from hiro_commons.logging_foundation import line

    built: list[dict] = []

    class Builds(logging.Handler):  # builds each line as it is logged, in the caller's thread, as the foundation does
        def emit(self, record: logging.LogRecord) -> None:
            built.append(line.build(record, "test"))

    errors_log = identity.logger("errors")
    handler = Builds()
    errors_log.addHandler(handler)
    try:
        r = client.get("/crash", headers={"traceparent": PARENT})
    finally:
        errors_log.removeHandler(handler)
    assert r.status_code == 500
    # Starlette's crash handler runs outside every middleware: it steps back into the request's story for its ids.
    crashed = [b for b in built if "contract-story-crash" in b["Body"]]
    assert crashed and crashed[0].get("TraceId") == STORY


def test_the_llm_request_keeps_the_story_that_asked():
    client.get("/ask", headers={"traceparent": PARENT})
    with Session(engine) as session:
        row = session.exec(select(LlmRequest).where(LlmRequest.story_id == STORY)).first()
    assert row is not None and row.task == "Is the lamp on?"


def test_an_outside_calls_line_has_its_time_and_the_story(caplog):
    log = identity.logger("test")
    with caplog.at_level(logging.DEBUG, log.name), story.begin("round", parent=PARENT):
        calls.done(log, "HA: get_states", calls.start(), timeout=10)
    rec = next(r for r in caplog.records if r.name == log.name)
    assert rec.call == "HA: get_states" and isinstance(rec.elapsed_ms, int)


def test_a_story_is_kept_across_a_thread():
    async def main() -> str | None:
        with story.begin("page", parent=PARENT):
            return await asyncio.to_thread(story.current_id)

    assert asyncio.run(main()) == STORY
