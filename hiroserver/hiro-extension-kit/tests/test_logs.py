"""Log files (logs.py): the app logs through the logging foundation into DATA_DIR/logs, one file a day, each line
naming the app as the core knows it; the link to the core's lines land there too. (The foundation's own tests, in
hiro-commons, cover the line's shape, the levels, the days and what must not escape the file.)"""

import json
import logging
from datetime import date

import pytest
from hiro_commons.log import Logger

from hiro_extension_kit import logs


@pytest.fixture
def log_dir(tmp_path):
    yield tmp_path
    logs.close()


def read(folder) -> list[dict]:
    logs.close()  # writes what is queued
    path = folder / f"testapp-{date.today().isoformat()}.jsonl"
    return [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_the_apps_lines_go_to_the_days_file_under_the_extensions_name(log_dir):
    logs.setup(log_dir, console=False)
    logging.getLogger("testapp.people").info("People: Maro is now tracked")
    logging.getLogger("testapp.ha").warning("HA connection lost (timeout); retrying in 5 s")
    got = read(log_dir)
    assert [(g["SeverityText"], g["InstrumentationScope"], g["Body"]) for g in got] == [
        ("INFO", "testapp.people", "People: Maro is now tracked"),
        ("WARNING", "testapp.ha", "HA connection lost (timeout); retrying in 5 s"),
    ]
    assert {g["Resource"]["service.name"] for g in got} == {"test"}  # the extension's name (conftest: `test`)


def test_the_link_to_the_core_lands_in_the_apps_file(log_dir):
    logs.setup(log_dir, console=False)
    Logger.get("EXTENSION").info("🔌 Extension couldn't stay connected to the core", url="ws://127.0.0.1:18082",
                                 error="connection refused")
    (got,) = read(log_dir)
    assert got["InstrumentationScope"] == "EXTENSION"
    assert got["Attributes"] == {"url": "ws://127.0.0.1:18082", "error": "connection refused"}
