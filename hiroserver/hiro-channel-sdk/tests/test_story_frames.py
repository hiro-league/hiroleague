"""The logging plan's one id across the apps, in the SDK: a frame carries the current story (extension.py), the side
that answers continues it, and a worker's round is a story of its own, as is each task it spawns (workers.py)."""

import asyncio
import json
from pathlib import Path
from typing import Any

from hiro_commons.logging_foundation import story

from hiro_channel_sdk.constants import ASKED_BY
from hiro_channel_sdk.extension import (
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    build_event,
    build_request,
)
from hiro_channel_sdk.workers import Worker

PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
STORY = "4bf92f3577b34da6a3ce929d0e0e4736"


def _story_of(traceparent: str | None) -> str | None:
    return traceparent.split("-")[1] if traceparent else None


def test_a_request_and_an_event_carry_the_current_story():
    with story.begin("page", parent=PARENT):
        request = build_request("ai.ask", {"use": "ask"}, sender_id="home", direction="inbound")
        event = build_event("thing.happened", {}, sender_id="home", direction="inbound")
    assert _story_of(request.routing.metadata["traceparent"]) == STORY
    assert _story_of(event.routing.metadata["traceparent"]) == STORY
    # it survives the wire as the other side reads it
    again = type(request).model_validate_json(request.model_dump_json())
    assert _story_of(again.routing.metadata["traceparent"]) == STORY


def test_outside_a_story_a_frame_carries_none():
    assert "traceparent" not in build_request("core.info", sender_id="home", direction="inbound").routing.metadata


class _Socket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, raw: str) -> None:
        self.sent.append(raw)


def test_the_answer_to_the_cores_request_continues_its_story(tmp_path: Path):
    seen: list[str | None] = []

    async def handler(params: dict[str, Any]) -> dict[str, Any]:
        seen.append(story.current_id())
        return {}

    client = ExtensionClient("ws://127.0.0.1:1", ExtensionInfo(name="net"), ExtensionCredentials(tmp_path))
    client.register_request("net.usage", handler)
    with story.begin("core", parent=PARENT):  # the core passing on home's ask
        msg = build_request("net.usage", {ASKED_BY: "home"}, sender_id="core", direction="outbound")
    ws = _Socket()
    asyncio.run(client._answer(ws, msg))
    assert seen == [STORY]
    assert json.loads(json.loads(ws.sent[0])["content"][0]["body"])["status"] == "ok"


def test_each_round_is_a_story_and_each_task_it_spawns_another():
    rounds: list[str | None] = []
    spawned: list[str | None] = []

    async def check() -> None:
        spawned.append(story.current_id())

    async def main() -> None:
        w = Worker()
        w.start()

        def tick() -> None:
            rounds.append(story.current_id())
            if len(rounds) == 1:
                w.spawn(check(), "check")

        w.every(0.02, tick, "tick")
        await asyncio.sleep(0.1)
        await w.stop()

    asyncio.run(main())
    assert len(rounds) >= 2 and None not in rounds and len(set(rounds)) == len(rounds)  # a new story each round
    assert len(spawned) == 1 and spawned[0] not in (None, rounds[0])  # the check: a story of its own


def test_a_task_spawned_inside_a_story_stays_in_it():
    seen: list[str | None] = []

    async def work() -> None:
        seen.append(story.current_id())

    async def main() -> None:
        w = Worker()
        w.start()
        with story.begin("page", parent=PARENT):
            task = w.spawn(work(), "work")
        await task
        await w.stop()

    asyncio.run(main())
    assert seen == [STORY]
