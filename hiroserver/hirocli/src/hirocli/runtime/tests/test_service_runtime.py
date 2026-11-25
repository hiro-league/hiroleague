"""The server under a service manager (systemd, WinSW, launchd): its secrets file, its restart, its data folder."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from hirocli.constants import ENV_DATA_DIR, ENV_SECRETS_FILE, ENV_SERVICE_MANAGER, SERVICE_RESTART_EXIT_CODE
from hirocli.domain import workspace
from hirocli.runtime import server_process


@pytest.fixture
def no_service(monkeypatch):
    for name in (ENV_SECRETS_FILE, ENV_SERVICE_MANAGER, ENV_DATA_DIR, "HIRO_TEST_PROVIDER_KEY"):
        # setenv first, so monkeypatch puts back what was there (nothing) after a test whose code set it.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def test_without_a_secrets_file_setting_nothing_is_loaded(no_service) -> None:
    server_process._load_service_secrets()  # no file named: nothing to do, no error


def test_the_secrets_file_fills_the_environment_and_names_only_the_keys(no_service, monkeypatch, tmp_path, caplog) -> None:
    secrets = tmp_path / "hiro.env"
    secrets.write_text("# provider keys\nHIRO_TEST_PROVIDER_KEY=sk-secret-value\n", encoding="utf-8")
    monkeypatch.setenv(ENV_SECRETS_FILE, str(secrets))

    with caplog.at_level(logging.INFO, logger="SERVER"):
        server_process._load_service_secrets()

    assert os.environ["HIRO_TEST_PROVIDER_KEY"] == "sk-secret-value"
    (line,) = [r for r in caplog.records if "secrets loaded" in r.getMessage()]
    assert "sk-secret-value" not in caplog.text


def test_a_missing_secrets_file_stops_the_start_with_an_error(no_service, monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setenv(ENV_SECRETS_FILE, str(tmp_path / "gone.env"))

    with caplog.at_level(logging.ERROR, logger="SERVER"), pytest.raises(SystemExit) as info:
        server_process._load_service_secrets()

    assert info.value.code == 1
    (line,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "secrets file can't be read" in line.getMessage()


@pytest.mark.parametrize("manager", ["systemd", "winsw", "launchd"])
def test_a_restart_under_any_service_manager_exits_75(no_service, monkeypatch, tmp_path, manager, caplog) -> None:
    monkeypatch.setenv(ENV_SERVICE_MANAGER, manager)
    marked = []
    monkeypatch.setattr(server_process, "mark_disconnected", lambda path: marked.append(path))

    with caplog.at_level(logging.INFO, logger="SERVER"), pytest.raises(SystemExit) as info:
        server_process._exit_for_service_restart(tmp_path)

    assert info.value.code == SERVICE_RESTART_EXIT_CODE == 75
    assert marked == [tmp_path]
    assert any("service manager starts a fresh server" in r.getMessage() for r in caplog.records)


def test_a_restart_outside_a_service_returns_to_spawn_a_successor(no_service, tmp_path) -> None:
    assert server_process._exit_for_service_restart(tmp_path) is None


def test_the_data_folder_setting_moves_the_registry_and_workspaces(no_service, monkeypatch, tmp_path) -> None:
    default = workspace.registry_path()
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "data"))

    assert workspace.registry_path() == tmp_path / "data" / "registry.json"
    assert workspace.default_workspace_path("home") == tmp_path / "data" / "workspaces" / "home"
    assert default != workspace.registry_path()


def test_an_empty_data_folder_setting_is_ignored(no_service, monkeypatch) -> None:
    default = workspace.registry_path()
    monkeypatch.setenv(ENV_DATA_DIR, "  ")
    assert workspace.registry_path() == default
    assert Path(default).name == "registry.json"
