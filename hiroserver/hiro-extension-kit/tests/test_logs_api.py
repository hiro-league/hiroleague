"""The Logs page's backend (logfiles.py, logs_api.py): the daily files read as they grow, a day's file read only
when the span reaches it, crash reports, the routes, downloads limited to the log files, and the notice open pages
get."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hiro_extension_kit import errors, events, logfiles, logs_api


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(logfiles, "FOLDER", tmp_path)
    logfiles.forget()
    yield tmp_path
    logfiles.forget()


NUMBER = {"DEBUG": 5, "INFO": 9, "WARNING": 13, "ERROR": 17, "CRITICAL": 21}


def entry(minutes_ago: float, level: str, scope: str, body: str, **attributes) -> str:
    at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    got = {"Timestamp": at.isoformat().replace("+00:00", "Z"), "SeverityText": level, "SeverityNumber": NUMBER[level],
           "Body": body, "InstrumentationScope": scope, "Resource": {"service.name": "test"}}
    if attributes:
        got["Attributes"] = attributes
    return json.dumps(got)


def day_file(folder, days_ago: int = 0):
    return folder / f"testapp-{(datetime.now().astimezone() - timedelta(days=days_ago)).date().isoformat()}.jsonl"


def write(path, *lines: str, mode: str = "w") -> None:
    with path.open(mode, encoding="utf-8", newline="\n") as f:
        f.write("".join(line + "\n" for line in lines))


@pytest.fixture
def client(folder):
    app = FastAPI()
    app.include_router(logs_api.router)
    errors.install(app)
    return TestClient(app)


def test_an_entry_keeps_its_fields_and_traceback(folder):
    trace = "Traceback (most recent call last):\n  File \"sync.py\", line 190, in _sync\nKeyError: 'area_id'"
    write(day_file(folder),
          entry(5, "ERROR", "testapp.ha", "HA connect hook: KeyError: 'area_id'", **{
              "exception.type": "KeyError", "exception.message": "'area_id'", "exception.stacktrace": trace}),
          entry(1, "WARNING", "testapp.frigate", "Frigate: /api/events was slow", elapsed_ms=8100))
    found, unreadable = logfiles.entries(["testapp"], True, datetime.now().astimezone() - timedelta(hours=1))
    assert unreadable == [] and [e.logger for e in found] == ["testapp.frigate", "testapp.ha"]  # newest first
    assert found[1].detail == trace.splitlines() and found[1].fields == {}
    assert found[0].fields == {"elapsed_ms": 8100}


def test_a_growing_file_is_read_on_from_where_it_was(folder):
    path = day_file(folder)
    write(path, entry(3, "INFO", "testapp.sync", "HA sync: 80 devices"), entry(2, "ERROR", "testapp.x", "boom"))
    first, _ = logfiles.read(path, "testapp")
    assert len(first) == 2
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(entry(1, "INFO", "testapp.y", "half a line still being written"))  # no newline yet: not read
    assert len(logfiles.read(path, "testapp")[0]) == 2
    with path.open("a", encoding="utf-8") as f:
        f.write("\n")
    assert logfiles.read(path, "testapp")[0][2].message == "half a line still being written"


def test_an_older_days_file_is_read_only_when_the_span_reaches_it(folder):
    write(day_file(folder), entry(10, "INFO", "a", "today"))
    write(day_file(folder, 1), entry(60 * 24, "INFO", "a", "yesterday"))
    write(day_file(folder, 3), "not json at all, and never opened for a span of a day")
    week = datetime.now().astimezone() - timedelta(days=7)
    day = datetime.now().astimezone() - timedelta(hours=26)
    assert [e.message for e in logfiles.entries(["testapp"], False, week)[0]] == ["today", "yesterday"]
    logfiles.forget()
    assert [e.message for e in logfiles.entries(["testapp"], False, day)[0]] == ["today", "yesterday"]
    assert day_file(folder, 3) not in logfiles._cache


def test_a_crash_report_is_one_entry_at_the_files_time(folder):
    write(folder / "crash.log", "Fatal Python error: Segmentation fault", "", "Current thread 0x00007f (most recent call first):",
          '  File "replay.py", line 88 in align')
    (crash,), _ = logfiles.read(folder / "crash.log", "crash")
    assert crash.level == "CRITICAL" and crash.message == "Fatal Python error: Segmentation fault"
    assert crash.detail[-1] == '  File "replay.py", line 88 in align'


def test_the_lines_route_filters_the_span_the_view_and_the_source(client, folder):
    write(day_file(folder), entry(90, "WARNING", "testapp.ha", "HA connection lost"), entry(5, "ERROR", "testapp.x", "boom"),
          entry(4, "INFO", "testapp.sync", "HA sync", devices=80))
    write(folder / "whatsapp-2026-01-01.jsonl", entry(2, "WARNING", "whatsmeow.Client", "Got 503"))  # not the app's
    write(folder / "crash.log", "Fatal Python error: Segmentation fault")
    r = client.get("/api/logs", params={"span": "1h"}).json()
    assert [(line["source"], line["message"]) for line in r["lines"]] == [("crash", "Fatal Python error: Segmentation fault"), ("testapp", "boom")]
    assert r["lines"][1]["id"] == f"{day_file(folder).name}:2" and r["more"] is False and r["unreadable"] == []
    r = client.get("/api/logs", params={"span": "1h", "view": "all", "source": "testapp"}).json()
    assert [(line["message"], line["fields"]) for line in r["lines"]] == [("HA sync", {"devices": "80"}), ("boom", {})]
    r = client.get("/api/logs", params={"span": "24h", "limit": 1}).json()
    assert len(r["lines"]) == 1 and r["more"] is True


def test_the_summary_counts_the_last_24_hours(client, folder):
    write(day_file(folder, 2), entry(60 * 50, "ERROR", "a", "too old"))
    write(day_file(folder), entry(30, "WARNING", "a", "slow"), entry(3, "ERROR", "a", "boom"), entry(2, "INFO", "a", "fine"))
    r = client.get("/api/logs/summary").json()
    hours = r.pop("hours")
    assert r == {
        "errors": 1, "warnings": 1,
        "newest": {**client.get("/api/logs", params={"span": "1h"}).json()["lines"][0]},
    }
    # per hour, oldest first: both are in the last hour
    assert len(hours) == 24 and hours[-1] == {"errors": 1, "warnings": 1} and not any(h["errors"] or h["warnings"] for h in hours[:-1])


def test_only_the_log_files_can_be_downloaded(client, folder):
    write(day_file(folder), entry(1, "INFO", "a", "hello"))
    write(day_file(folder, 2), entry(60 * 48, "INFO", "a", "older"))
    (folder.parent / "testapp.db").write_text("secret")
    r = client.get(f"/api/logs/files/{day_file(folder).name}")
    assert r.status_code == 200 and "hello" in r.text and "attachment" in r.headers["content-disposition"]
    assert client.get(f"/api/logs/files/{day_file(folder, 2).name}").status_code == 200
    for name in ("testapp.db", "..%2Ftestapp.db", "testapp-2020-01-01.jsonl", "whatsapp-console.log.2"):
        assert client.get(f"/api/logs/files/{name}").status_code == 404
    got = client.get("/api/logs/files").json()
    assert got["keep_days"] == 30
    assert [(f["name"], f["day"]) for f in got["files"]] == [
        (day_file(folder).name, datetime.now().astimezone().date().isoformat()),
        (day_file(folder, 2).name, (datetime.now().astimezone() - timedelta(days=2)).date().isoformat()),
        ("crash.log", None),
    ]
    assert got["files"][-1]["size"] == 0


def test_a_file_that_cant_be_read_is_said_and_logged_once(folder, monkeypatch, caplog):
    path = day_file(folder)
    write(path, entry(1, "ERROR", "a", "boom"))
    real_open = type(path).open

    def locked(self, *args, **kwargs):
        if self.name == path.name:
            raise PermissionError("in use")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "open", locked)
    with caplog.at_level(logging.WARNING, "testapp.logs"):
        for _ in range(3):
            found, unreadable = logfiles.entries(["testapp"], True, datetime.now().astimezone() - timedelta(hours=1))
    assert found == [] and unreadable == [f"{path.name} can't be read (PermissionError: in use)"]
    assert len([r for r in caplog.records if f"Logs: reading {path.name}" in r.getMessage()]) == 1


def test_open_pages_hear_when_a_line_is_written(monkeypatch):
    told: list[str] = []
    monkeypatch.setattr(events, "_loop", None)  # bus.publish delivers at once
    unsubscribe = events.bus.subscribe("logs", lambda kind, _data: told.append(kind))

    async def main():
        notifier = logs_api.LogNotifier()
        monkeypatch.setattr(logs_api, "NOTIFY_EVERY", 0.05)
        notifier.start()
        await asyncio.sleep(0.12)
        assert told == []  # nothing written: nothing said
        logging.getLogger("testapp.test").warning("a line")
        await asyncio.sleep(0.12)
        await notifier.stop()

    try:
        asyncio.run(main())
    finally:
        unsubscribe()
    assert told == ["logs"]
