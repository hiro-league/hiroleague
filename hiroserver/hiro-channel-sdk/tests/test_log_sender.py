"""An app's log sender (the logging plan, phase 5): it sends its own file's lines at INFO and up, with their places,
starts after the place the core kept, waits while the link is down, and starts a replaced file again."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from hiro_channel_sdk import log_sender
from hiro_channel_sdk.extension import ExtensionRequestError
from hiro_channel_sdk.log_sender import LogSender


class FakeClient:
    """A link whose core keeps lines as the core's store does: after the last place it kept."""

    def __init__(self) -> None:
        self.connected = True
        self.kept: list[str] = []
        self.batches: list[dict[str, Any]] = []
        self.last: str | None = None
        self.down = False

    async def request(self, method: str, params: dict[str, Any], timeout: float = 0) -> dict[str, Any]:
        assert method == "logs.send"
        if self.down:
            raise ExtensionRequestError("not_connected", "not connected to the core")
        self.batches.append(params)
        if params.get("restart"):
            self.last = None
        for place, line in params["lines"]:
            if self.last is None or log_sender.parse_place(place) > log_sender.parse_place(self.last):
                self.kept.append(json.loads(line)["Body"])
                self.last = place
        return {"last": self.last}


def _today() -> date:
    return datetime.now().astimezone().date()


def _append(folder: Path, *bodies: tuple[str, int], day: date | None = None) -> Path:
    path = folder / f"homehiro-{(day or _today()).isoformat()}.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for body, number in bodies:
            fh.write(json.dumps({"Timestamp": "2026-11-20T10:00:00Z", "SeverityNumber": number, "Body": body}) + "\n")
    return path


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def folder(tmp_path):
    return tmp_path


def test_it_sends_info_and_up_with_each_lines_place(folder):
    path = _append(folder, ("starting", 9), ("details", 5), ("HA lost", 13))
    client = FakeClient()
    sender = LogSender(client, folder, "homehiro")
    assert _run(sender.send_new()) == 2
    assert client.kept == ["starting", "HA lost"]
    (batch,) = client.batches
    assert batch["lines"][-1][0] == f"{_today().isoformat()}:{path.stat().st_size}"
    assert _run(sender.send_new()) == 0  # nothing new
    assert json.loads((folder / "sent.json").read_text())["place"] == batch["lines"][-1][0]


def test_lines_logged_while_the_core_was_away_go_when_it_is_back(folder):
    client = FakeClient()
    sender = LogSender(client, folder, "homehiro")
    _append(folder, ("before", 9))
    _run(sender.send_new())
    client.down = True
    _append(folder, ("while away 1", 13), ("while away 2", 17))
    with pytest.raises(ExtensionRequestError):
        _run(sender.send_new())
    client.down = False
    restarted = LogSender(client, folder, "homehiro")  # the app restarted too: the place comes from sent.json
    _run(restarted.send_new())
    assert client.kept == ["before", "while away 1", "while away 2"]


def test_a_long_backlog_goes_in_batches_and_yesterdays_file_first(folder, monkeypatch):
    monkeypatch.setattr(log_sender, "BATCH_LINES", 2)
    yesterday = date.fromordinal(_today().toordinal() - 1)
    _append(folder, ("y1", 9), ("y2", 9), ("y3", 9), day=yesterday)
    _append(folder, ("t1", 9))
    client = FakeClient()
    sender = LogSender(client, folder, "homehiro")
    sender.sent = (yesterday, 0)
    while _run(sender.send_new()):
        pass
    assert client.kept == ["y1", "y2", "y3", "t1"]
    assert [len(b["lines"]) for b in client.batches] == [2, 2]


def test_a_line_being_written_waits_for_the_next_look(folder):
    path = _append(folder, ("whole", 9))
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"SeverityNumber": 9, "Body": "half')
    client = FakeClient()
    _run(LogSender(client, folder, "homehiro").send_new())
    assert client.kept == ["whole"]


def test_a_replaced_file_is_sent_from_its_start_and_says_so(folder):
    path = _append(folder, ("old 1", 9), ("old 2", 9), ("old 3", 9))
    client = FakeClient()
    sender = LogSender(client, folder, "homehiro")
    _run(sender.send_new())
    path.unlink()
    _append(folder, ("new", 9))
    _run(sender.send_new())
    assert client.batches[-1].get("restart") is True
    assert client.kept[-1] == "new"


def test_a_failure_is_said_once_and_its_end_too(folder, caplog):
    client = FakeClient()
    sender = LogSender(client, folder, "homehiro")
    sender._failed("timeout: no answer")
    sender._failed("timeout: no answer")
    sender._failed("not_connected: closed")  # the link says that itself
    assert [r.message for r in caplog.records].count(
        "This app's log lines couldn't be sent to the core; they wait in its file") == 1
    _append(folder, ("back", 9))
    _run(sender.send_new())
    assert sender.failing is None
