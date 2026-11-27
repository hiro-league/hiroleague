"""Where the admin is said to be (issue 448): its local address always, its LAN name when the front door serves it,
and the service's install reads its real port from the service's own workspace."""

from __future__ import annotations

import io
import json
from pathlib import Path

from rich.console import Console

from hirocli.admin_address import lan_url, print_ready_panel
from hirocli.domain.front_door import ENV_FRONT_DOOR
from hirocli.tools import service as service_tools
from hirocli.tools.service_models import ServiceInstallResult


def test_the_lan_name_shows_only_when_the_front_door_serves_it(monkeypatch) -> None:
    assert lan_url("hiro.local", front_door=True) == "http://hiro.local"
    assert lan_url("hiro.local", front_door=False) is None
    monkeypatch.delenv(ENV_FRONT_DOOR, raising=False)
    assert lan_url("home.local") is None
    monkeypatch.setenv(ENV_FRONT_DOOR, "127.0.0.1:18079")  # what the service gives its server
    assert lan_url("home.local") == "http://home.local"


def test_the_panel_names_both_addresses() -> None:
    out = io.StringIO()
    print_ready_panel(Console(file=out, width=100), 18087, "http://home.local")
    text = out.getvalue()
    assert "http://localhost:18087" in text and "http://home.local" in text and "Hiro is running" in text


def _service_data(tmp_path: Path, *, admin_port: int, core_name: str) -> Path:
    ws = tmp_path / "workspaces" / "home"
    ws.mkdir(parents=True)
    (ws / "config.json").write_text(json.dumps({"admin_port": admin_port, "core_name": core_name}), encoding="utf-8")
    registry = {"default_workspace": "id-1", "workspaces": {"id-1": {"name": "home", "path": str(ws)}}}
    (tmp_path / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    return tmp_path


def _result(data_dir: Path) -> ServiceInstallResult:
    return ServiceInstallResult(
        service="hiro-home", manager="winsw", user="NT SERVICE\\hiro-home", definition_path="x", secrets_file="s",
        secrets_file_created=True, exec_start="hiro start -f", started=True, edit_secrets="e", restart_command="r",
        logs="l", data_dir=str(data_dir),
    )


def test_the_install_reads_the_services_own_admin_port(tmp_path: Path) -> None:
    data = _service_data(tmp_path, admin_port=18087, core_name="home")
    assert service_tools.wait_for_admin(_result(data), "home") == (18087, "home.local")  # not slot 0's 18083
    assert service_tools.wait_for_admin(_result(data), None) == (18087, "home.local")  # its default


def test_an_unreadable_service_folder_names_no_port(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service_tools, "_WORKSPACE_WAIT_S", 0.0)
    assert service_tools.wait_for_admin(_result(tmp_path / "missing"), None) is None
