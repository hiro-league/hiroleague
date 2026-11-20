"""The core's log store and the questions that answer across every part (the logging plan, phase 5): an app's batch is
kept once, whatever is sent twice; the log tools read every stream; "what went wrong" names each app's problems, and
one story id returns its lines from every part."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from hirocli.services import log_store
from hirocli.tools import logs

_NUMBERS = {"DEBUG": 5, "INFO": 9, "WARNING": 13, "ERROR": 17, "CRITICAL": 21}


def _line(body: str, *, level: str = "INFO", scope: str = "AREA", service: str = "core", ago: float = 0.0,
          story: str | None = None, **attributes) -> dict:
    at = datetime.now(timezone.utc) - timedelta(seconds=ago)
    line = {"Timestamp": at.isoformat().replace("+00:00", "Z"), "SeverityText": level,
            "SeverityNumber": _NUMBERS[level], "Body": body, "InstrumentationScope": scope}
    if story:
        line["TraceId"], line["SpanId"] = story, "a" * 16
    if attributes:
        line["Attributes"] = attributes
    line["Resource"] = {"service.name": service}
    return line


def _own_file(folder: Path, name: str, *lines: dict) -> None:
    day = logs._today()
    path = folder / f"{name}-{day.isoformat()}.jsonl"
    folder.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in lines))


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


@pytest.fixture
def store(log_dir):
    s = log_store.LogStore(log_dir)
    yield s
    s.close()


def _places(*lines: dict, day: str = "2026-11-20", start: int = 0) -> list[list]:
    out, at = [], start
    for x in lines:
        at += 100
        out.append([f"{day}:{at}", json.dumps(x)])
    return out


# --- the store -------------------------------------------------------------------------------------------------------


def test_an_apps_batch_sent_twice_is_kept_once(store, log_dir):
    batch = _places(_line("one", service="home"), _line("two", service="home"))
    assert store.receive("app-home", batch) == "2026-11-20:200"
    more = batch + _places(_line("three", service="home"), start=200)  # the answer was lost: sent again, and more
    assert store.receive("app-home", more) == "2026-11-20:300"
    rows = logs.LogTailTool().execute(source="home").rows
    assert [r["message"] for r in rows] == ["one", "two", "three"]
    assert {r["source"] for r in rows} == {"app-home"}


def test_the_last_place_survives_a_restart_of_the_core(store, log_dir):
    store.receive("app-net", _places(_line("one", service="net")))
    store.close()
    again = log_store.LogStore(log_dir)
    assert again.last_received("app-net") == "2026-11-20:100"
    assert again.receive("app-net", _places(_line("one", service="net"))) == "2026-11-20:100"  # nothing new
    again.close()


def test_a_replaced_file_starts_its_places_again(store):
    store.receive("app-home", _places(_line("one"), _line("two")))
    assert store.receive("app-home", _places(_line("fresh")), restart=True) == "2026-11-20:100"


def test_a_later_day_is_after_every_place_of_an_earlier_one(store):
    store.receive("app-home", _places(_line("late on monday"), start=99_000, day="2026-11-16"))
    assert store.receive("app-home", _places(_line("tuesday"), day="2026-11-17")) == "2026-11-17:100"


def test_write_keeps_lines_hides_secrets_and_names_the_source(store, log_dir):
    kept = store.write("device", [_line("the phone failed", level="ERROR", api_token="abc", device_id="d1"),
                                  {"not": "a line"}, "not json"])
    assert kept == 1
    (raw,) = (log_dir / f"device-{logs._today().isoformat()}.jsonl").read_text(encoding="utf-8").splitlines()
    line = json.loads(raw)
    assert line["Attributes"] == {"api_token": "[hidden]", "device_id": "d1"}
    store.write("device", [{k: v for k, v in _line("no resource").items() if k != "Resource"}])
    rows = logs.LogTailTool().execute(source="device").rows
    assert [r["source"] for r in rows] == ["device", "device"]


@pytest.mark.parametrize("name", ["server", "cli", "gateway", "channel-whatsapp", "App-Home", "a b", ""])
def test_the_cores_own_streams_and_odd_names_are_refused(store, name):
    with pytest.raises(ValueError):
        store.write(name, [_line("x")])


def test_the_admin_page_still_reads_only_the_cores_own_streams(store, log_dir):
    _own_file(log_dir, "server", _line("the core"))
    store.write("app-home", [_line("an app", service="home")])
    assert [r["message"] for r in logs.LogTailTool().execute(source="core").rows] == ["the core"]
    assert sorted(r["message"] for r in logs.LogTailTool().execute(source="all").rows) == ["an app", "the core"]


# --- one question across every part ----------------------------------------------------------------------------------


def test_what_went_wrong_names_the_problems_of_every_app(store, log_dir):
    _own_file(log_dir, "server", _line("a core warning", level="WARNING", scope="AI.ASK", ago=60),
              _line("routine", level="INFO", ago=50), _line("an old error", level="ERROR", ago=2 * 3600))
    store.write("app-home", [_line("HA lost; retrying in 5 s", level="WARNING", scope="homehiro.ha", service="home", ago=40),
                             _line("HA lost; retrying in 10 s", level="WARNING", scope="homehiro.ha", service="home",
                                   ago=30)])
    store.write("app-net", [_line("AdGuard check failed", level="ERROR", scope="nethiro.status", service="net", ago=20,
                                  story="b" * 32, **{"exception.stacktrace": "Traceback ...\nOSError: down"})])
    result = logs.LogProblemsTool().execute(since="1h")
    assert result.total == 4
    assert result.by_source == {"app-home": 2, "server": 1, "app-net": 1}
    first = result.groups[0]  # errors first
    assert (first["source"], first["level"], first["area"], first["messages"], first["story_ids"]) == \
        ("app-net", "ERROR", "nethiro.status", ["AdGuard check failed"], ["b" * 32])
    home = next(g for g in result.groups if g["source"] == "app-home")
    # The same problem with another number is one kind; the latest message is shown
    assert (home["count"], home["kinds"], home["messages"]) == (2, 1, ["HA lost; retrying in 10 s"])
    assert home["last"].startswith(("Today, ", "Yesterday, "))
    assert result.rows[-1]["fields"]["exception"].endswith("OSError: down")
    assert result.span.startswith(("Today, ", "Yesterday, ")) and " to " in result.span
    assert logs.LogProblemsTool().execute(since="1h", level="ERROR").by_source == {"app-net": 1}
    assert logs.LogProblemsTool().execute(since="1h", source="apps").by_source == {"app-home": 2, "app-net": 1}


def test_one_story_returns_its_lines_from_every_part_in_order(store, log_dir):
    sid = "c" * 32
    store.write("app-home", [_line("Ask now", service="home", story=sid, ago=3),
                             _line("camera.check took 2100 ms", service="home", story=sid, ago=1, step="camera.check",
                                   elapsed_ms=2100, outcome="ok")])
    _own_file(log_dir, "server", _line("⬇️ Extension request — home · ai.ask", scope="EXTENSIONS", story=sid, ago=2),
              _line("another story", story="d" * 32, ago=2))
    result = logs.LogStoryTool().execute(story_id=sid)
    assert [r["message"] for r in result.rows] == ["Ask now", "⬇️ Extension request — home · ai.ask",
                                                   "camera.check took 2100 ms"]
    assert result.sources == ["app-home", "server"]
    assert result.steps == [{"step": "camera.check", "source": "app-home", "elapsed_ms": 2100, "outcome": "ok",
                             "when": result.rows[-1]["when"], "step_id": "a" * 16}]
    assert 1500 < result.took_ms < 2500 and result.problems == 0
    # A traceparent names the same story; so does the search's filter
    assert len(logs.LogStoryTool().execute(story_id=f"00-{sid}-{'e' * 16}-01").rows) == 3
    assert len(logs.LogSearchTool().execute(story_id=sid).rows) == 3


def test_a_chat_messages_id_names_its_story(store):
    msg_id = "2ec39cc8-dcb7-4571-8b19-a6a563a4846e"
    store.write("app-home", [_line("from the message", story="2ec39cc8dcb745718b19a6a563a4846e")])
    assert [r["message"] for r in logs.LogStoryTool().execute(story_id=msg_id).rows] == ["from the message"]


def test_a_span_reads_as_words_or_an_iso_time():
    now = time.time()
    assert logs.moment("90m", now=now) == now - 5400
    assert logs.moment("2d", now=now) == now - 172800
    assert logs.moment(None) is None
    assert logs.moment("2026-11-20T13:15:00+00:00") == datetime(2026, 11, 20, 13, 15, tzinfo=timezone.utc).timestamp()
    with pytest.raises(ValueError):
        logs.moment("yesterday-ish")
