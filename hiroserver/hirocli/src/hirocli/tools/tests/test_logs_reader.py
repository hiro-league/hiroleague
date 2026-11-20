"""The log tools on the daily JSON files: the rows keep the shape the admin Logs page reads, the server's and the
CLI's are told apart by module, scope filters match, and a live tail follows a growing file and a new day."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from hirocli.tools import logs


def _line(body: str, *, scope: str = "COMM", level: str = "INFO", at: datetime | None = None, service: str = "core",
          **attributes) -> str:
    at = at or datetime.now(timezone.utc)
    raw = {"Timestamp": at.isoformat().replace("+00:00", "Z"), "SeverityText": level, "SeverityNumber": 9,
           "Body": body, "InstrumentationScope": scope, "Resource": {"service.name": service}}
    if attributes:
        raw["Attributes"] = attributes
    return json.dumps(raw, ensure_ascii=False)


def _write(path: Path, *lines: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(text + "\n" for text in lines))


def _today_file(folder: Path, name: str, days_back: int = 0) -> Path:
    day = logs._today() - timedelta(days=days_back)
    return folder / f"{name}-{day.isoformat()}.jsonl"


@pytest.fixture
def log_dir(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    with (
        patch.object(logs, "_resolve_log_dir", return_value=folder),
        patch.object(logs, "_resolve_gateway_log_dir", return_value=None),
        patch.object(logs, "_resolve_gateway_instance_path", return_value=None),
    ):
        yield folder


def test_a_row_keeps_the_pages_shape_with_its_scope_fields(log_dir):
    _write(_today_file(log_dir, "server"), _line(
        "📥 Inbound message", device_id="dev-1", msg_id="m-7", method="channels.list", text_preview="hello",
        traffic_class="inbound.message", traffic_subclass="text", payload={"a": 1}))
    (row,) = logs.LogTailTool().execute(source="all").rows
    assert row["source"] == "server" and row["module"] == "COMM" and row["level"] == "INFO"
    assert row["message"] == "📥 Inbound message" and row["is_startup"] is False
    assert (row["scope_device_id"], row["scope_msg_id"], row["scope_method"]) == ("dev-1", "m-7", "channels.list")
    assert (row["scope_text_preview"], row["scope_traffic_class"], row["scope_traffic_subclass"]) == ("hello", "inbound.message", "text")
    assert row["has_msg_id"] is True
    assert row["extra"].endswith('payload={"a": 1}') and ["payload", '{"a": 1}'] in row["fields"]
    assert row["timestamp_display"].endswith(("AM", "PM")) and row["date_display"]
    for key in ("id", "level_html", "module_html", "message_html", "extra_html", "extra_tooltip_html"):
        assert key in row


def test_a_traceback_is_the_exception_field_whole(log_dir):
    tb = 'Traceback (most recent call last):\n  File "x.py", line 3, in f\n    a = b\nKeyError: key=1'
    _write(_today_file(log_dir, "server"), _line("failed", level="ERROR", **{
        "exception.type": "KeyError", "exception.message": "key=1", "exception.stacktrace": tb, "reason": "x y"}))
    (row,) = logs.LogTailTool().execute().rows
    assert row["fields"] == [["reason", "x y"], ["exception", tb]]


def test_the_server_and_the_cli_are_told_apart_by_module(log_dir):
    _write(_today_file(log_dir, "server"), _line("from the server", scope="SERVER"), _line("a CLI tool in the server", scope="CLI.AI"))
    _write(_today_file(log_dir, "cli"), _line("a command", scope="CLI.WORKSPACE"), _line("the command's domain call", scope="WORKSPACE"))
    by_source = {}
    for row in logs.LogTailTool().execute().rows:
        by_source.setdefault(row["source"], []).append(row["message"])
    assert sorted(by_source["server"]) == ["from the server", "the command's domain call"]
    assert sorted(by_source["cli"]) == ["a CLI tool in the server", "a command"]
    assert {r["source"] for r in logs.LogTailTool().execute(source="cli").rows} == {"cli"}


def test_search_filters_by_scope_across_days_and_channels(log_dir):
    now = datetime.now(timezone.utc)
    _write(_today_file(log_dir, "server", 1), _line("yesterday's", msg_id="m-1", at=now - timedelta(days=1)))
    _write(_today_file(log_dir, "server"), _line("today's", msg_id="m-1", at=now), _line("other", msg_id="m-2", at=now))
    _write(_today_file(log_dir, "channel-devices"), _line("plugin hop", scope="CH_TRANSPORT", msg_id="m-1", service="channel-devices", at=now))
    got = logs.LogSearchTool().execute(msg_id="m-1")
    assert [(r["source"], r["message"]) for r in got.rows] == [
        ("server", "yesterday's"), ("server", "today's"), ("channel-devices", "plugin hop")]
    assert logs.channel_names(log_dir) == ["devices"]


def test_a_live_tail_follows_a_growing_file_and_a_new_one(log_dir):
    path = _today_file(log_dir, "server")
    _write(path, _line("first"))
    first = logs.LogTailTool().execute()
    assert [r["message"] for r in first.rows] == ["first"]
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(_line("second") + "\n" + _line("half")[:20])  # a line still being written waits
    second = logs.LogTailTool().execute(after_offsets=json.dumps(first.file_offsets))
    assert [r["message"] for r in second.rows] == ["second"]
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(_line("half")[20:] + "\n")
    _write(_today_file(log_dir, "channel-whatsapp"), _line("a plugin that just started", service="channel-whatsapp"))
    third = logs.LogTailTool().execute(after_offsets=json.dumps(second.file_offsets))
    assert sorted(r["message"] for r in third.rows) == ["a plugin that just started", "half"]


def test_the_last_session_starts_at_the_newest_startup_line(log_dir):
    now = datetime.now(timezone.utc)
    _write(_today_file(log_dir, "server", 1), _line("🚀 Hiro Server starting...", scope="SERVER", at=now - timedelta(days=1)))
    start = now - timedelta(minutes=5)
    _write(_today_file(log_dir, "server"), _line("🚀 Hiro Server starting...", scope="SERVER", at=start), _line("after", at=now))
    ts = logs.find_last_server_session_start_ts(None)
    assert ts == pytest.approx(start.timestamp())
    rows = logs.LogTailTool().execute(min_timestamp=ts).rows
    assert [r["message"] for r in rows] == ["🚀 Hiro Server starting...", "after"] and rows[0]["is_startup"]
