"""The Logs page's backend (logfiles.py, logs_api.py): the files read as they grow and rotate, crash
reports, the routes, downloads limited to the log files, and the notice open pages get."""

import asyncio
import logging
import os
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hiro_extension_kit import logfiles, logs_api
from hiro_extension_kit import errors, events


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(logfiles, "FOLDER", tmp_path)
    logfiles.forget()
    yield tmp_path
    logfiles.forget()


def stamp(minutes_ago: float) -> str:
    return (datetime.now().astimezone() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S%z")


def write(path, *lines: str, mode: str = "w") -> None:
    with path.open(mode, encoding="utf-8", newline="\n") as f:
        f.write("".join(line + "\n" for line in lines))


@pytest.fixture
def client(folder):
    app = FastAPI()
    app.include_router(logs_api.router)
    errors.install(app)
    return TestClient(app)


def test_an_entry_keeps_the_lines_after_it_as_its_traceback(folder):
    write(folder / "testapp-errors.log",
          f"{stamp(5)} ERROR testapp.ha: HA connect hook: KeyError: 'area_id'",
          "Traceback (most recent call last):",
          '  File "sync.py", line 190, in _sync',
          "KeyError: 'area_id'",
          f"{stamp(1)} WARNING testapp.frigate: Frigate: /api/events was slow: 8.1 s (limit 15 s)")
    found, unreadable = logfiles.entries(["testapp"], True, datetime.now().astimezone() - timedelta(hours=1))
    assert unreadable == [] and [e.logger for e in found] == ["testapp.frigate", "testapp.ha"]  # newest first
    assert found[1].detail == ["Traceback (most recent call last):", '  File "sync.py", line 190, in _sync', "KeyError: 'area_id'"]


def test_a_growing_file_is_read_on_from_where_it_was(folder):
    path = folder / "testapp.log"
    write(path, f"{stamp(3)} INFO testapp.sync: HA sync: 80 devices", f"{stamp(2)} ERROR testapp.x: boom")
    first, _ = logfiles.read(path, "testapp")
    write(path, "Traceback (most recent call last):", "ValueError: boom", mode="a")
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"{stamp(1)} INFO testapp.y: half a line still being written")  # no newline yet: not read
    again, _ = logfiles.read(path, "testapp")
    assert len(again) == 2 and again[1].detail == ["Traceback (most recent call last):", "ValueError: boom"]
    with path.open("a", encoding="utf-8") as f:
        f.write("\n")
    assert logfiles.read(path, "testapp")[0][2].message == "half a line still being written"


def test_a_rotated_file_is_read_again_and_older_copies_only_when_the_span_needs_them(folder):
    write(folder / "testapp.log", f"{stamp(10)} INFO a: new one")
    write(folder / "testapp.log.1", f"{stamp(200)} INFO a: older", f"{stamp(20)} INFO a: newest of the old")
    hour = datetime.now().astimezone() - timedelta(hours=1)
    assert [e.message for e in logfiles.entries(["testapp"], False, hour)[0]] == ["new one", "newest of the old"]
    os.replace(folder / "testapp.log", folder / "testapp.log.1")  # rotated, as RotatingFileHandler does
    write(folder / "testapp.log", f"{stamp(1)} INFO a: after the rotation, a longer line than the one before it")
    assert [e.message for e in logfiles.read(folder / "testapp.log", "testapp")[0]] == \
        ["after the rotation, a longer line than the one before it"]
    assert [e.message for e in logfiles.read(folder / "testapp.log.1", "testapp")[0]] == ["new one"]


def test_a_crash_report_is_one_entry_at_the_files_time(folder):
    write(folder / "crash.log", "Fatal Python error: Segmentation fault", "", "Current thread 0x00007f (most recent call first):",
          '  File "replay.py", line 88 in align')
    (crash,), _ = logfiles.read(folder / "crash.log", "crash")
    assert crash.level == "CRITICAL" and crash.message == "Fatal Python error: Segmentation fault"
    assert crash.detail[-1] == '  File "replay.py", line 88 in align'


def test_the_lines_route_filters_the_span_the_view_and_the_source(client, folder):
    write(folder / "testapp-errors.log", f"{stamp(90)} WARNING testapp.ha: HA connection lost", f"{stamp(5)} ERROR testapp.x: boom")
    write(folder / "testapp.log", f"{stamp(4)} INFO testapp.sync: HA sync", f"{stamp(5)} ERROR testapp.x: boom")
    write(folder / "whatsapp-errors.log", f"{stamp(2)} WARNING whatsmeow.Client: Got 503 stream error")  # the old worker's: not read
    write(folder / "crash.log", "Fatal Python error: Segmentation fault")
    r = client.get("/api/logs", params={"span": "1h"}).json()
    assert [(line["source"], line["message"]) for line in r["lines"]] == [("crash", "Fatal Python error: Segmentation fault"), ("testapp", "boom")]
    assert r["lines"][1]["id"] == "testapp-errors.log:2" and r["more"] is False and r["unreadable"] == []
    r = client.get("/api/logs", params={"span": "1h", "view": "all", "source": "testapp"}).json()
    assert [line["message"] for line in r["lines"]] == ["HA sync", "boom"]
    r = client.get("/api/logs", params={"span": "24h", "limit": 1}).json()
    assert len(r["lines"]) == 1 and r["more"] is True


def test_the_summary_counts_the_last_24_hours(client, folder):
    write(folder / "testapp-errors.log", f"{stamp(60 * 30)} ERROR a: too old", f"{stamp(30)} WARNING a: slow", f"{stamp(3)} ERROR a: boom")
    r = client.get("/api/logs/summary").json()
    hours = r.pop("hours")
    assert r == {
        "errors": 1, "warnings": 1,
        "newest": {**client.get("/api/logs", params={"span": "1h"}).json()["lines"][0]},
    }
    # per hour, oldest first: both are in the last hour
    assert len(hours) == 24 and hours[-1] == {"errors": 1, "warnings": 1} and not any(h["errors"] or h["warnings"] for h in hours[:-1])


def test_only_the_log_files_can_be_downloaded(client, folder):
    write(folder / "testapp.log", f"{stamp(1)} INFO a: hello")
    write(folder / "testapp.log.2", f"{stamp(100)} INFO a: older")
    (folder.parent / "testapp.db").write_text("secret")
    r = client.get("/api/logs/files/testapp.log")
    assert r.status_code == 200 and "hello" in r.text and "attachment" in r.headers["content-disposition"]
    assert client.get("/api/logs/files/testapp.log.2").status_code == 200
    for name in ("testapp.db", "..%2Ftestapp.db", "testapp.log.9", "whatsapp-console.log.2"):
        assert client.get(f"/api/logs/files/{name}").status_code == 404
    files = {f["name"]: f for f in client.get("/api/logs/files").json()}
    assert files["testapp.log"]["kept"] == 1 and files["testapp.log"]["keep"] == 5 and files["crash.log"]["size"] == 0


def test_a_file_that_cant_be_read_is_said_and_logged_once(folder, monkeypatch, caplog):
    path = folder / "testapp-errors.log"
    write(path, f"{stamp(1)} ERROR a: boom")
    real_open = type(path).open

    def locked(self, *args, **kwargs):
        if self.name == "testapp-errors.log":
            raise PermissionError("in use")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "open", locked)
    with caplog.at_level(logging.WARNING, "testapp.logs"):
        for _ in range(3):
            found, unreadable = logfiles.entries(["testapp"], True, datetime.now().astimezone() - timedelta(hours=1))
    assert found == [] and unreadable == ["testapp-errors.log can't be read (PermissionError: in use)"]
    assert len([r for r in caplog.records if "Logs: reading testapp-errors.log" in r.getMessage()]) == 1


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
