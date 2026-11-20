"""The core's logger on the foundation: its detail kept field for field (FINEINFO, the message scope, the level per
area, the run ledger kept out), its old CSV files archived, and every core process's setup passing the self-test."""

import json
import logging
from pathlib import Path

import pytest

from hiro_commons import log as core_log
from hiro_commons import logging_foundation as foundation
from hiro_commons import tasks
from hiro_commons.log import FINEINFO, Logger, log_scope
from hiro_commons.logging_foundation import catches, daily


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.delenv(foundation.LEVELS_SETTING, raising=False)
    saved = (Logger._level, dict(core_log._MODULE_OVERRIDES))
    yield tmp_path
    Logger.close()
    Logger._level = saved[0]
    core_log._MODULE_OVERRIDES.clear()
    core_log._MODULE_OVERRIDES.update(saved[1])


def lines(folder: Path, name: str = "server") -> list[dict]:
    foundation.flush()
    found = []
    for _day, path in daily.files(folder, name):
        found += [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
    return found


def test_the_server_writes_its_own_daily_file_with_the_cores_source(folder):
    today = Logger.start(folder, name="server", service="core", console=False)
    Logger.get("COMM").info("📥 Inbound message", device_id="d1")
    assert today.name == f"server-{core_log._today().isoformat()}.jsonl"
    (got,) = [g for g in lines(folder) if g["Body"] == "📥 Inbound message"]
    assert got["InstrumentationScope"] == "COMM" and got["Resource"] == {"service.name": "core"}
    assert got["Attributes"] == {"device_id": "d1"}


def test_the_message_scope_fields_ride_on_every_line_inside_it(folder):
    Logger.start(folder, name="server", service="core", console=False)
    with log_scope(device_id="dev-1", msg_id="m-7", method="channels.list", text_preview="  hello there ",
                   traffic_class="inbound.message", traffic_subclass="text"):
        Logger.get("COMM").info("routed")
        Logger.get("COMM").info("explicit wins", device_id="other")
    got = {g["Body"]: g["Attributes"] for g in lines(folder)}
    assert got["routed"] == {"device_id": "dev-1", "msg_id": "m-7", "method": "channels.list",
                             "text_preview": "hello there", "traffic_class": "inbound.message", "traffic_subclass": "text"}
    assert got["explicit wins"]["device_id"] == "other"


def test_fineinfo_is_kept_with_its_own_level_and_number(folder):
    Logger.set_level("FINEINFO")
    Logger.start(folder, name="server", service="core", console=False)
    Logger.get("AGENT").fineinfo("a fine step")
    Logger.get("AGENT").debug("below the core's level")
    (got,) = lines(folder)
    assert got["SeverityText"] == "FINEINFO" and got["SeverityNumber"] == 8 and got["Body"] == "a fine step"
    assert logging.getLevelName(FINEINFO) == "FINEINFO"


def test_an_area_follows_its_longest_prefix_above_or_below_the_cores_level(folder):
    Logger.set_level("INFO")
    Logger.set_module_levels({"AGENT": "DEBUG", "AGENT.GRAPH": "WARNING", "COMM": "ERROR"})
    Logger.start(folder, name="server", service="core", console=False)
    Logger.get("AGENT.TOOLS").debug("agent debug passes")
    Logger.get("AGENT.GRAPH.NODE").info("graph info is held")
    Logger.get("COMM").warning("comm warning is held")
    Logger.get("SERVER").info("server info passes")
    Logger.get("SERVER").debug("server debug is held")
    assert [g["Body"] for g in lines(folder)] == ["agent debug passes", "server info passes"]


def test_libraries_stay_at_warning_and_the_cores_plain_loggers_follow_its_level(folder):
    Logger.start(folder, name="server", service="core", console=False)
    logging.getLogger("httpcore.connection").info("library chatter")
    logging.getLogger("neonize.client").warning("library warning")
    logging.getLogger("hirocli.domain.character").info("a core module's info")
    assert [g["Body"] for g in lines(folder)] == ["library warning", "a core module's info"]


def test_a_librarys_traceback_lands_at_any_level(folder):
    Logger.start(folder, name="server", service="core", console=False)
    try:
        raise ConnectionError("socket closed")
    except ConnectionError:
        logging.getLogger("websockets.client").warning("connection lost", exc_info=True)
    (got,) = lines(folder)
    assert "ConnectionError: socket closed" in got["Attributes"]["exception.stacktrace"]


def test_the_run_ledgers_rows_never_reach_the_log(folder):
    Logger.start(folder, name="server", service="core", console=False)
    Logger.get("AGENT.GRAPH.LEDGER.ab12").info("node_done")  # no ledger file open: still not a log line
    handler = Logger.add_file_sink(str(folder / "graph.log"), level="INFO", csv_columns=["event"],
                                   include_prefix="AGENT.GRAPH.LEDGER.cd34")
    try:
        Logger.get("AGENT.GRAPH.LEDGER.cd34").info("turn_done")
        handler.flush()
        assert (folder / "graph.log").read_text(encoding="utf-8").splitlines() == ["event", "turn_done"]
        assert lines(folder) == []
    finally:
        Logger.remove_file_sink(handler)
        handler.close()


def test_the_old_csv_files_move_to_the_archive_as_they_are(folder):
    (folder / "server.log").write_text("timestamp,level,module,message,extra\n1,INFO,X,old,\n", encoding="utf-8")
    (folder / "server.log.1").write_text("older\n", encoding="utf-8")
    (folder / "server.logbook").write_text("not ours\n", encoding="utf-8")
    (folder / "cli.log").write_text("the cli's: moved by the cli\n", encoding="utf-8")
    Logger.start(folder, name="server", service="core", console=False)
    archived = folder / "archive" / "csv"
    assert sorted(p.name for p in archived.iterdir()) == ["server.log", "server.log.1"]
    assert (archived / "server.log").read_text(encoding="utf-8").endswith("1,INFO,X,old,\n")
    assert (folder / "server.logbook").exists() and (folder / "cli.log").exists()


def test_the_console_keeps_the_cores_colour_line(folder):
    record = logging.makeLogRecord({"name": "COMM", "levelname": "INFO", "levelno": 20, "msg": "routed", "created": 0})
    record.hiro_fields = {"device_id": "d1", "exception.stacktrace": "Traceback..."}
    text = core_log._ColourFormat().format(record)
    assert "[INF]" in text and "[COMM________]" in text and "routed" in text and "device_id=d1" in text
    assert "Traceback" not in text


@pytest.mark.parametrize("name, service", [("server", "core"), ("cli", "cli")])
def test_the_self_test_passes_in_the_server_and_the_cli(folder, name, service):
    Logger.start(folder, name=name, service=service, console=False)
    results = foundation.self_test(startup=foundation.watch_loop)  # each runs its loop watched (server_process._main)
    assert [net for net, ok in results.items() if not ok] == []


@pytest.mark.parametrize("component", ["gateway", "channel-whatsapp"])
def test_the_self_test_passes_in_the_gateway_and_a_plugin(folder, component):
    from hiro_channel_sdk import log_setup

    log_setup.init(component, folder, level="INFO")
    results = foundation.self_test(startup=foundation.watch_loop)  # log_setup.run() watches their loop
    assert [net for net, ok in results.items() if not ok] == []
    assert daily.files(folder, component)


def test_a_kept_task_that_fails_is_logged_and_let_go(folder):
    import asyncio

    Logger.start(folder, name="server", service="core", console=False)

    async def fails():
        raise ValueError("lost on the way")

    async def main():
        tasks.keep(fails(), name="agent-m1")
        await asyncio.sleep(0.01)

    asyncio.run(main())
    (got,) = [g for g in lines(folder) if g["InstrumentationScope"] == "hiro.tasks"]
    assert got["Body"] == "Background task agent-m1 failed: lost on the way"
    assert "ValueError: lost on the way" in got["Attributes"]["exception.stacktrace"]
    assert tasks.running() == 0


# The core's packages: nothing escapes the log by habit (the apps run the same scan in their contract).
_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES = ["hiro-commons/src/hiro_commons", "hiro-channel-sdk/src/hiro_channel_sdk", "hiro-extension-kit/src/hiro_extension_kit",
             "hirocli/src/hirocli", "hiro-memory/src/hiro_memory", "gateway/src/hirogateway", "channels", "hiroleague"]


# The core's own helpers that log the error they are given: the SDK workers' report() (the apps plug in the kit's
# failed()), the memory library's routes' _graph_failure()
_HELPERS = ("report", "_graph_failure")


@pytest.mark.parametrize("package", _PACKAGES)
def test_no_catch_in_the_core_drops_an_error(package):
    found = [f"{p.relative_to(_ROOT)}:{line}" for p, line in
             catches.silent_catches(_ROOT / package, skip=(".venv", "migrations"), tests=False, log_calls=_HELPERS)]
    assert not found, f"these catches drop the error: log it, or raise it again: {found}"
