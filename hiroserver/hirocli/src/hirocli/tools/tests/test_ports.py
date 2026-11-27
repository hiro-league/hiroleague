"""Workspaces' ports (issue 455): a new workspace takes the first slot whose ports are all free on the machine and
its gateway gets the slot's spare port; one made before keeps its own; a start names a port another program holds."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from hiro_commons.ports import port_free

from hirocli.constants import ENV_DATA_DIR
from hirocli.domain.config import Config, load_config, save_config
from hirocli.domain.workspace import WorkspaceRegistry, create_workspace, next_free_slot, slot_ports
from hirocli.tools import server_control
from hirocli.tools.server import SetupTool


def test_a_slot_with_a_port_in_use_is_skipped() -> None:
    registry = WorkspaceRegistry()
    busy = set(slot_ports(registry, 0)[3:])  # something holds slot 0's admin port
    assert next_free_slot(registry, is_free=lambda p: p not in busy) == 1
    assert next_free_slot(registry, is_free=lambda p: True) == 0


def test_the_bind_test_sees_a_listening_port() -> None:
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        assert not port_free(held.getsockname()[1])


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    return tmp_path


def test_a_new_workspace_gets_its_slots_gateway_port_and_an_old_one_keeps_its_own(data_dir: Path) -> None:
    entry, registry = create_workspace("home")
    SetupTool().execute(gateway_url=Config.model_fields["gateway_url"].default, workspace="home", skip_env_import=True)
    cfg = load_config(Path(entry.path))
    assert cfg.gateway_port == slot_ports(registry, entry.port_slot)[1]
    assert cfg.gateway_url == f"ws://localhost:{cfg.gateway_port}"

    cfg.gateway_port = 8765  # a workspace made before: its phones were paired to this port
    save_config(Path(entry.path), cfg)
    SetupTool().execute(gateway_url="ws://gate.hiro.local", workspace="home", skip_env_import=True)
    assert load_config(Path(entry.path)).gateway_port == 8765


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_start_names_the_port_another_program_holds() -> None:
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        cfg = Config(http_port=_free_port(), extension_port=_free_port(), gateway_port=_free_port(), admin_port=port)
        with pytest.raises(ValueError, match=rf"port {port} \(the admin\) is in use"):
            server_control.check_ports(cfg, admin=True)
        server_control.check_ports(cfg, admin=False)  # no admin: its port isn't opened
