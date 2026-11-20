"""The device app's problems reach the core's log store (device_problems.py, the logging plan's phase 8): each as a line
of the ``device`` stream, under its chat message's story, with no secret and no person's words, and once only."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.logging_foundation import story
from hirocli.runtime import device_problems
from hirocli.runtime.request_handler import RequestHandler, RequestRefused
from hirocli.runtime.request_methods import register_request_methods
from hirocli.services import log_store

DEVICE = "dev-7f3a"
MESSAGE = str(uuid.uuid4())


@pytest.fixture
def store(tmp_path: Path):
    device_problems._seen.clear()
    log_store.start(tmp_path)
    yield tmp_path
    log_store.stop()


def ctx() -> SimpleNamespace:
    return SimpleNamespace(msg=SimpleNamespace(routing=SimpleNamespace(sender_id=DEVICE)))


def problem(**over) -> dict:
    return {"id": str(uuid.uuid4()), "at": "2026-11-20T10:15:03.120Z", "level": "ERROR", "area": "MessageSendNotifier",
            "message": "Failed to send message (unexpected)", **over}


def lines(folder: Path) -> list[dict]:
    return [json.loads(t) for f in sorted(folder.glob("device-*.jsonl")) for t in f.read_text("utf-8").splitlines()]


def report(*items: dict) -> dict:
    return asyncio.run(device_problems.handle_logs_report({"lines": list(items)}, ctx()))


def test_a_problem_is_a_line_under_its_messages_story(store):
    answer = report(problem(story=MESSAGE, error_type="StateError", error_message="Bad state", stack="#0 main"))
    assert answer == {"kept": 1}
    [found] = lines(store)
    assert found["TraceId"] == story.id_for(MESSAGE) == MESSAGE.replace("-", "")
    assert found["SeverityText"] == "ERROR" and found["SeverityNumber"] == 17
    assert found["InstrumentationScope"] == "device.MessageSendNotifier"
    assert found["Resource"] == {"service.name": "device"}
    assert found["Timestamp"] == "2026-11-20T10:15:03.120000Z"
    attributes = found["Attributes"]
    assert attributes["exception.type"] == "StateError" and attributes["message_id"] == MESSAGE
    assert attributes["device_id"] == DEVICE
    from hiro_commons.logging_foundation import line
    assert line.parse(json.dumps(found)).fields["device_id"] == DEVICE  # what the log tools read


def test_secrets_and_a_persons_words_never_reach_the_line(store):
    report(problem(level="WARNING", fields={"token": "abc", "auth_token": "x", "text": "hello Hiro", "url": "ws://g",
                                            "count": 2}))
    [found] = lines(store)
    fields = {k: v for k, v in found["Attributes"].items() if k not in ("log.record.uid", "device_id")}
    assert fields == {"token": "[hidden]", "auth_token": "[hidden]", "text": "[hidden]", "url": "ws://g", "count": 2}
    assert "TraceId" not in found


def test_a_batch_sent_again_is_kept_once(store):
    same = problem()
    assert report(same, problem())["kept"] == 2
    assert report(same)["kept"] == 0
    assert len(lines(store)) == 2


def test_what_isnt_a_problem_is_dropped_and_a_batch_is_capped(store):
    assert report({"message": "no time"}, "text", problem(at="not a time"))["kept"] == 0
    with pytest.raises(RequestRefused):
        report(*[problem() for _ in range(21)])


def test_the_phones_own_request_reaches_the_store(store):
    """The frame as the phone builds it (device_apps' GatewayRequestClient), through the core's request handler."""
    sent = problem(level="WARNING", area="GatewayClient", story=MESSAGE,
                   message="Send attempted while not connected — message dropped")
    frame = {"version": "0.1", "message_type": "request", "request_id": "req_1_1",
             "routing": {"id": "req_1_1", "channel": "devices", "direction": "inbound", "sender_id": DEVICE,
                         "metadata": {}},
             "content": [{"content_type": "json", "metadata": {},
                          "body": json.dumps({"method": "logs.report", "params": {"lines": [sent]}})}]}
    handler = RequestHandler(SimpleNamespace(workspace_path=store))  # type: ignore[arg-type]
    register_request_methods(handler)

    async def emit(_: object) -> None:
        return None

    answer = asyncio.run(handler.handle(UnifiedMessage.model_validate(frame), emit_outbound=emit))
    assert answer is not None and json.loads(answer.content[0].body)["status"] == "ok"
    [found] = lines(store)
    assert found["TraceId"] == story.id_for(MESSAGE)
    assert found["Attributes"]["log.record.uid"] == sent["id"]
    assert found["Body"] == "Send attempted while not connected — message dropped"
