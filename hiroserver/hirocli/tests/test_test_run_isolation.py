"""A test run writes nothing into this machine's real Hiro data (conftest.py): no registry, no workspace, no log line.

The `hiro` callback starts the log in the default workspace, so a CLI test used to write into the real workspace's
`cli-<day>.jsonl` (on Simone, live's log store, during the deploy's check).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from platformdirs import user_data_dir
from typer.testing import CliRunner

from hiro_commons import logging_foundation
from hiro_commons.log import Logger
from hiro_commons.log import _MODULE_OVERRIDES as module_levels
from hiro_commons.logging_foundation import daily
from hirocli.constants import APP_NAME, ENV_DATA_DIR
from hirocli.domain import workspace


@pytest.fixture
def logger_put_back():
    """The `hiro` callback starts the log and sets the levels from the workspace: close it and put them back after."""
    saved = (Logger._level, Logger._console, dict(module_levels))
    yield
    Logger.close()
    Logger._level, Logger._console = saved[0], saved[1]
    module_levels.clear()
    module_levels.update(saved[2])


def test_the_run_resolves_no_real_data_folder(real_hiro_data) -> None:
    real = Path(user_data_dir(APP_NAME, appauthor=False)).resolve()

    assert not workspace.registry_path().resolve().is_relative_to(real)
    assert not real_hiro_data(workspace.registry_path().parent)
    assert not real_hiro_data(workspace.default_workspace_path("default"))
    assert workspace.load_registry().workspaces == {}  # the real registry's workspaces aren't seen


def test_a_cli_command_starts_no_log_in_a_real_workspace(real_hiro_data, logger_put_back) -> None:
    from hirocli.commands.app import app

    result = CliRunner().invoke(app, ["workspaces", "list"])

    assert result.exit_code == 0, result.output
    assert "No workspaces configured" in result.output
    started = logging_foundation.where()
    assert started is None or not real_hiro_data(started[0])


def test_a_cli_command_logs_into_the_workspace_its_data_folder_names(monkeypatch, tmp_path, logger_put_back) -> None:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "data"))
    entry, _ = workspace.create_workspace("home")
    from hirocli.commands.app import app

    result = CliRunner().invoke(app, ["workspaces", "list"])
    Logger.get("CLI.TEST").info("A line from the test")
    logging_foundation.flush()

    assert result.exit_code == 0, result.output
    logs = Path(entry.path) / "logs"
    assert logging_foundation.where() == (logs, "cli")
    written = [json.loads(text) for _day, path in daily.files(logs, "cli")
               for text in path.read_text(encoding="utf-8").splitlines()]
    assert any(line["Body"] == "A line from the test" for line in written)
