"""The logging foundation: the line's shape, a level per area, one file a day kept 30 days, the link's structlog lines
in the same file, and nothing that goes wrong escaping it."""

import asyncio
import gc
import json
import logging
import subprocess
import sys
import threading
from datetime import date, timedelta

import pytest

from hiro_commons import logging_foundation as foundation
from hiro_commons.log import Logger
from hiro_commons.logging_foundation import daily, line


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.delenv(foundation.LEVELS_SETTING, raising=False)
    yield tmp_path
    foundation.close()


def lines(folder, name="testapp"):
    foundation.close()  # writes what is queued
    found = []
    for _day, path in daily.files(folder, name):
        found += [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
    return found


def test_a_line_is_one_json_object_with_opentelemetrys_names(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    logging.getLogger("testapp.ha").warning("HA connection lost; retrying in %d s", 5, extra={"elapsed_ms": 5003})
    (got,) = lines(folder)
    assert list(got) == ["Timestamp", "SeverityText", "SeverityNumber", "Body", "InstrumentationScope", "Attributes", "Resource"]
    assert got["Timestamp"].endswith("Z") and got["SeverityText"] == "WARNING" and got["SeverityNumber"] == 13
    assert got["Body"] == "HA connection lost; retrying in 5 s" and got["InstrumentationScope"] == "testapp.ha"
    assert got["Attributes"] == {"elapsed_ms": 5003} and got["Resource"] == {"service.name": "test"}


def test_an_exception_keeps_its_type_message_and_traceback(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    try:
        raise KeyError("area_id")
    except KeyError:
        logging.getLogger("testapp.sync").exception("HA sync failed")
    (got,) = lines(folder)
    a = got["Attributes"]
    assert a["exception.type"] == "KeyError" and a["exception.message"] == "'area_id'"
    assert a["exception.stacktrace"].startswith("Traceback") and "KeyError: 'area_id'" in a["exception.stacktrace"]
    assert line.parse(json.dumps(got)).stacktrace == a["exception.stacktrace"]


def test_a_secret_in_a_field_is_hidden(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    logging.getLogger("testapp.ha").info("Connected", extra={"ha_token": "abc", "tokens": 12, "url": "http://ha"})
    (got,) = lines(folder)
    assert got["Attributes"] == {"ha_token": "[hidden]", "tokens": 12, "url": "http://ha"}


def test_each_area_can_have_its_own_level(folder, monkeypatch):
    monkeypatch.setenv(foundation.LEVELS_SETTING, "testapp.ha=DEBUG, testapp.noisy=WARNING")
    foundation.setup(folder, name="testapp", service="test", console=False)
    logging.getLogger("testapp.ha.live").debug("a frame")
    logging.getLogger("testapp.noisy").info("chatter")
    logging.getLogger("testapp.other").debug("not at INFO")
    logging.getLogger("testapp.other").info("said")
    assert [g["Body"] for g in lines(folder)] == ["a frame", "said"]
    assert logging.getLogger("testapp.ha").level == logging.NOTSET  # close() put the levels back


def test_the_links_structlog_lines_land_in_the_file_with_their_fields(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    link = Logger.get("EXTENSION")
    link.info("✅ Extension connected to the core", extension="test", url="ws://127.0.0.1:18082")
    try:
        raise ConnectionError("refused")
    except ConnectionError:
        link.error("❌ Extension connection failed", error="refused", exc_info=True)
    Logger.get("CH_TRANSPORT").fineinfo("frame sent")  # below INFO: not written
    first, second = lines(folder)
    assert first["InstrumentationScope"] == "EXTENSION" and first["Body"] == "✅ Extension connected to the core"
    assert first["Attributes"] == {"extension": "test", "url": "ws://127.0.0.1:18082"}
    assert second["SeverityText"] == "ERROR" and second["Attributes"]["exception.type"] == "ConnectionError"


def test_a_ledger_rows_area_stays_in_its_own_file(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    handler = Logger.add_file_sink(str(folder / "graph.log"), level="INFO", use_csv=True, csv_columns=["event"],
                                   include_prefix="AGENT.GRAPH.LEDGER.ab")
    try:
        Logger.get("AGENT.GRAPH.LEDGER.ab").info("node_done")
        handler.flush()
        assert "node_done" in (folder / "graph.log").read_text(encoding="utf-8")
        assert lines(folder) == []
    finally:
        Logger.remove_file_sink(handler)
        handler.close()


def test_a_crashed_thread_and_uvicorns_own_lines_reach_the_file(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    uvicorn = logging.getLogger("uvicorn")
    uvicorn.propagate = False  # as uvicorn sets it up when it runs the app
    try:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application")
    finally:
        uvicorn.propagate = True
    t = threading.Thread(target=lambda: 1 / 0, name="sampler")
    t.start()
    t.join()
    bodies = [g["Body"] for g in lines(folder)]
    assert "Exception in ASGI application" in bodies
    assert "Uncaught exception in thread sampler: division by zero" in bodies


def test_setting_up_again_writes_each_line_once(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    foundation.setup(folder, name="testapp", service="test", console=False)
    logging.getLogger("testapp.test").warning("once")
    assert [g["Body"] for g in lines(folder)] == ["once"]


def test_one_file_a_day_and_only_30_days_are_kept(folder):
    today = date(2026, 11, 19)
    for back in (0, 29, 30, 45):
        (folder / daily.file_name("testapp", today - timedelta(days=back))).write_text("", encoding="utf-8")
    (folder / "other-2026-01-01.jsonl").write_text("", encoding="utf-8")  # another part's: not ours to delete
    gone = daily.prune(folder, "testapp", today)
    assert sorted(p.name for p in gone) == ["testapp-2026-10-05.jsonl", "testapp-2026-10-20.jsonl"]
    assert [d for d, _p in daily.files(folder, "testapp")] == [today, today - timedelta(days=29)]
    assert (folder / "other-2026-01-01.jsonl").exists()


def test_a_new_day_opens_its_own_file(folder, monkeypatch):
    handler = daily.DailyFile(folder, "testapp")
    handler.setFormatter(logging.Formatter("%(message)s"))
    days = iter([date(2026, 11, 19), date(2026, 11, 20)])
    monkeypatch.setattr(handler, "_today", lambda: next(days))
    for text in ("late", "early"):
        handler.emit(logging.makeLogRecord({"msg": text}))
    handler.close()
    assert (folder / "testapp-2026-11-19.jsonl").read_text(encoding="utf-8") == "late\n"
    assert (folder / "testapp-2026-11-20.jsonl").read_text(encoding="utf-8") == "early\n"


def test_a_half_written_or_foreign_line_is_not_a_line():
    assert line.parse('{"Timestamp": "2026-11-19T21:15:03Z", "Body": "x"') is None
    assert line.parse("2026-11-19 21:15:03+0300 INFO homehiro.ha: old text line") is None
    got = line.parse('{"Timestamp":"2026-11-19T21:15:03.000001Z","SeverityText":"INFO","SeverityNumber":9,"Body":"x",'
                     '"InstrumentationScope":"a","Resource":{"service.name":"home"}}')
    assert got is not None and got.service == "home" and got.at.tzinfo is not None


# --- the safety nets ---------------------------------------------------------------------------------------------


def test_the_self_test_finds_every_net_in_the_file(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    results = foundation.self_test(startup=foundation.watch_loop)
    assert results == {net: True for net in foundation.selftest.NETS}


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning",
                            "ignore::pytest.PytestUnhandledThreadExceptionWarning")  # with the nets off, pytest's own catch them
def test_the_self_test_says_which_net_is_missing(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    foundation.close()  # the nets are gone, but the self-test still needs a file to read: set up a bare one
    foundation._state.file = daily.DailyFile(folder, "testapp")
    try:
        got = foundation.self_test()
    finally:
        foundation._state.file.close()
        foundation._state.file = None
    assert not got["uncaught"] and not got["native_crash"]


def test_a_failed_task_is_logged_with_its_name_and_traceback(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)

    async def fails():
        raise ValueError("lost")

    async def main():
        foundation.watch_loop()
        asyncio.get_running_loop().create_task(fails(), name="sync-round")
        await asyncio.sleep(0.01)

    asyncio.run(main())
    gc.collect()
    (got,) = [g for g in lines(folder) if g["InstrumentationScope"] == "asyncio"]
    assert got["Body"] == "Task exception was never retrieved"
    assert got["Attributes"]["task"] == "sync-round" and "ValueError: lost" in got["Attributes"]["exception.stacktrace"]


def test_a_childs_output_goes_to_its_own_daily_file(folder):
    foundation.setup(folder, name="testapp", service="test", console=False)
    with foundation.child_log("plugin") as out:
        subprocess.run([sys.executable, "-c", "import sys; print('hello'); sys.exit('dying words')"], stdout=out, stderr=out)
    (path,) = folder.glob("testapp-plugin-*.log")
    assert sorted(path.read_text(encoding="utf-8").splitlines()) == ["dying words", "hello"]  # stdout is buffered
