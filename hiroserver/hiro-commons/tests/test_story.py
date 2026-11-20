"""A story: one id for everything one starting event caused, its steps timed, carried from process to process."""

import asyncio
import json
import logging

import pytest

from hiro_commons import log as core_log
from hiro_commons import logging_foundation as foundation
from hiro_commons.log import Logger
from hiro_commons.logging_foundation import daily, story

MESSAGE_ID = "6f1c2a3b-4d5e-4f60-8a71-92b3c4d5e6f7"  # as a device makes it


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.delenv(foundation.LEVELS_SETTING, raising=False)
    yield tmp_path
    foundation.close()


def lines(folder, name="testapp"):
    foundation.flush()
    found = []
    for _day, path in daily.files(folder, name):
        found += [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
    return found


def test_a_message_id_gives_the_same_story_id_everywhere():
    assert story.id_for(MESSAGE_ID) == MESSAGE_ID.replace("-", "")
    assert story.id_for(MESSAGE_ID.upper()) == MESSAGE_ID.replace("-", "")
    other = story.id_for("wa:3EB0C431D0A1")  # not a uuid: a hash, as long as a W3C trace id
    assert len(other) == 32 and other == story.id_for("wa:3EB0C431D0A1")
    assert story.id_for("0" * 32) != "0" * 32  # all zeros is never a valid id


def test_every_line_inside_a_step_carries_its_ids_and_its_end_says_how_long(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    log = logging.getLogger("testapp.chat")
    log.info("before")
    with story.begin("gateway.relay", story_id=story.id_for(MESSAGE_ID), area="testapp.chat") as first:
        log.info("inside")
        with story.step("ai.ask", area="testapp.ai", model="m1") as inner:
            inner.set(tokens=12)
            log.info("deeper")
    got = {g["Body"].split(" took ")[0]: g for g in lines(folder)}
    assert "TraceId" not in got["before"]
    sid = MESSAGE_ID.replace("-", "")
    assert got["inside"]["TraceId"] == sid and got["inside"]["SpanId"] == first.step_id
    assert got["deeper"]["SpanId"] == inner.step_id and inner.story_id == sid
    end = got["ai.ask"]
    assert end["InstrumentationScope"] == "testapp.ai" and end["SpanId"] == inner.step_id
    a = end["Attributes"]
    assert a["step"] == "ai.ask" and a["outcome"] == "ok" and a["elapsed_ms"] >= 0
    assert a["parent_step"] == first.step_id and a["model"] == "m1" and a["tokens"] == 12
    assert "parent_step" not in got["gateway.relay"]["Attributes"]


def test_a_failed_step_says_so_at_warning_and_the_error_goes_on(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    with pytest.raises(TimeoutError), story.step("ha.call", area="testapp.ha"):
        raise TimeoutError("no answer")
    (end,) = lines(folder)
    assert end["SeverityText"] == "WARNING" and end["Body"].startswith("ha.call failed after")
    assert end["Attributes"]["outcome"] == "error" and end["Attributes"]["error"] == "no answer"
    assert end["Attributes"]["error.type"] == "TimeoutError"


def test_a_step_without_its_own_line_keeps_the_ids_only(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    with story.step("ai.call", line=False) as s:
        logging.getLogger("testapp.ai").info("AI call done", extra={"elapsed_ms": 812})
    (got,) = lines(folder)
    assert got["Body"] == "AI call done" and got["SpanId"] == s.step_id


def test_a_step_below_its_areas_level_writes_no_end_line(folder):
    foundation.setup(folder, name="testapp", service="test", console=False, levels={"testapp.worker": "INFO"})
    with story.step("worker.round", area="testapp.worker", level=logging.DEBUG):
        logging.getLogger("testapp.worker").warning("a problem in the round")
    (got,) = lines(folder)
    assert got["Body"] == "a problem in the round" and "TraceId" in got


def test_begin_with_nothing_given_is_a_new_story_even_inside_another():
    with story.begin("chat.message", story_id=MESSAGE_ID, line=False) as outer:
        with story.begin("worker.round", line=False) as inner:
            assert inner.story_id != outer.story_id
        with story.step("ai.ask", line=False) as child:
            assert child.story_id == outer.story_id
    assert story.current() is None


def test_the_story_is_carried_to_another_process_and_continued_there():
    metadata: dict = {}
    with story.begin("devices.receive", story_id=MESSAGE_ID, line=False) as here:
        story.inject(metadata)
        assert metadata["traceparent"] == f"00-{here.story_id}-{here.step_id}-01" == story.carry()
    with story.begin("server.receive", parent=metadata, story_id="ignored when one is carried", line=False) as there:
        assert there.story_id == here.story_id and there._parent_id == int(here.step_id, 16)
    with story.begin("server.receive", parent={"traceparent": "rubbish"}, story_id=MESSAGE_ID, line=False) as fallback:
        assert fallback.story_id == here.story_id and fallback._parent_id is None
    assert story.inject({}) == {}  # outside a story nothing is carried


def test_asyncio_tasks_and_threads_keep_the_story():
    async def go():
        with story.begin("chat.message", story_id=MESSAGE_ID, line=False) as s:
            in_task = await asyncio.create_task(asyncio.sleep(0, story.current()))
            in_thread = await asyncio.to_thread(story.current)
            return s, in_task, in_thread

    s, in_task, in_thread = asyncio.run(go())
    assert in_task == in_thread == (s.story_id, s.step_id)


def test_a_cancelled_step_says_cancelled_not_failed(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)

    async def go():
        async def work():
            with story.step("agent.run", area="testapp.agent"):
                await asyncio.sleep(10)

        task = asyncio.create_task(work())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    (end,) = lines(folder)
    assert end["Attributes"]["outcome"] == "cancelled" and end["SeverityText"] == "INFO"


def test_in_the_core_a_steps_end_follows_the_cores_level_per_area(tmp_path, monkeypatch):
    monkeypatch.delenv(foundation.LEVELS_SETTING, raising=False)
    saved = (Logger._level, dict(core_log._MODULE_OVERRIDES))
    try:
        Logger.set_module_levels({"COMM": "WARNING"})
        Logger.start(tmp_path, name="server", service="core", console=False)
        with story.begin("gateway.relay", story_id=MESSAGE_ID, area="GATEWAY"):
            Logger.get("COMM").warning("routed", device_id="d1")
            with story.step("comm.send", area="COMM"):
                pass
        got = {g["Body"].split(" took ")[0]: g for g in lines(tmp_path, "server")}
        assert set(got) == {"routed", "gateway.relay"}  # COMM is at WARNING: no INFO end line there
        assert got["routed"]["TraceId"] == MESSAGE_ID.replace("-", "")  # the core's structlog lines carry the ids
        assert got["routed"]["Attributes"] == {"device_id": "d1"}
    finally:
        Logger.close()
        Logger._level = saved[0]
        core_log._MODULE_OVERRIDES.clear()
        core_log._MODULE_OVERRIDES.update(saved[1])
