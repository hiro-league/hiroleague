"""`hiro service` on Linux (systemd): unit/env generation and argument handling, without systemd."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hiro_commons import systemd_service as sd
from hirocli import front_door_setup as door
from hirocli import linux_service as ls
from hirocli.constants import ENV_SERVICE_MANAGER, SERVICE_RESTART_EXIT_CODE
from hirocli.tools import service as service_tools
from hirocli.tools import service_linux

EXE = "/opt/hiroleague/current/bin/hiro"


@pytest.fixture
def linux_as_user(monkeypatch):
    """Pretend to be a non-root user on Linux with `hiro` at EXE."""
    monkeypatch.setattr(service_tools, "current_system", lambda: "linux")
    monkeypatch.setattr(service_linux, "require_linux", lambda: None)
    monkeypatch.setattr(service_linux, "is_root", lambda: False)
    monkeypatch.setattr(service_linux, "default_service_user", lambda: "michel")
    monkeypatch.setattr(ls, "hiro_executable", lambda: EXE)


@pytest.fixture
def linux_as_root(monkeypatch, linux_as_user):
    """Pretend to be root on Linux; record what would be installed instead of touching /etc."""
    monkeypatch.setattr(service_linux, "is_root", lambda: True)
    monkeypatch.setattr(
        service_linux,
        "resolve_service_user",
        lambda name: sd.ServiceUser(name=name, uid=1001, gid=1001, group=name, home=Path(f"/var/lib/{name}")),
    )
    calls: dict = {}
    monkeypatch.setattr(service_linux, "check_user_can_run", lambda user, args: calls.setdefault("checked", (user.name, args)))

    def fake_install(spec, user, env_content, *, start=True):
        calls.update(spec=spec, user=user.name, env=env_content, start=start)
        return True

    monkeypatch.setattr(service_linux, "install_service", fake_install)

    def fake_door(user):
        calls["door"] = user.name
        return door.FrontDoorSetup(admin=door.LINUX_ADMIN, program="/opt/hiroleague/caddy/2.11.9/caddy",
                                   service="hiro-caddy.service", account="hiro-caddy")

    monkeypatch.setattr(door, "install_linux", fake_door)
    return calls


def test_service_name_per_workspace() -> None:
    assert ls.service_name(None) == "hiro"
    assert ls.service_name("home") == "hiro-home"
    assert ls.service_name("My Home") == "hiro-My-Home"


def test_build_spec_runs_hiro_in_foreground_with_server_environment() -> None:
    spec = ls.build_spec(exe=EXE, user="hiro", group="hiro", workspace=None)

    assert spec.exec_args == [EXE, "start", "--foreground"]
    assert spec.env_file.as_posix() == "/etc/hiro/hiro.env"
    assert spec.environment["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert spec.environment[ENV_SERVICE_MANAGER] == "systemd"
    # The folder holding `hiro` also holds hirogate and the channel plugins the server starts.
    assert spec.environment["PATH"].startswith("/opt/hiroleague/current/bin:")
    assert spec.restart_exit_code == SERVICE_RESTART_EXIT_CODE

    unit = sd.render_unit(spec)
    assert f"ExecStart={EXE} start --foreground" in unit
    assert "User=hiro" in unit


def test_build_spec_for_named_workspace_passes_it_on() -> None:
    spec = ls.build_spec(exe=EXE, user="michel", group="michel", workspace="home")
    assert spec.name == "hiro-home"
    assert spec.exec_args[-2:] == ["--workspace", "home"]
    assert spec.env_file.as_posix() == "/etc/hiro/hiro-home.env"


def test_env_file_lists_the_catalog_provider_variables() -> None:
    # Hidden catalog providers (e.g. Cloudflare while image generation is hidden) are left out,
    # like everywhere else providers are listed (scan-env included).
    text = ls.env_file_content("hiro", "hiro")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        assert f"# {name}=" in text
    assert "sudo systemctl restart hiro.service" in text


def test_sudo_command_spells_out_path_and_user() -> None:
    assert ls.sudo_command(EXE, "install", user="michel", workspace=None) == f"sudo {EXE} service install --user michel"
    assert (
        ls.sudo_command("/home/m/my apps/hiro", "install", user="hiro", workspace="home")
        == "sudo '/home/m/my apps/hiro' service install --user hiro --workspace home"
    )


def test_install_without_root_says_exactly_what_to_run(linux_as_user) -> None:
    with pytest.raises(sd.NeedsRootError) as info:
        service_tools.ServiceInstallTool().execute()
    assert info.value.command == f"sudo {EXE} service install --user michel"


def test_install_without_root_keeps_requested_user_and_workspace(linux_as_user) -> None:
    with pytest.raises(sd.NeedsRootError) as info:
        service_tools.ServiceInstallTool().execute(user="hiro", workspace="home")
    assert info.value.command == f"sudo {EXE} service install --user hiro --workspace home"


def test_uninstall_without_root_says_exactly_what_to_run(linux_as_user) -> None:
    with pytest.raises(sd.NeedsRootError) as info:
        service_tools.ServiceUninstallTool().execute()
    assert info.value.command == f"sudo {EXE} service uninstall"


@pytest.mark.parametrize("user", ["hiro", "michel"])
def test_install_as_root_runs_as_the_chosen_user(linux_as_root, user) -> None:
    result = service_tools.ServiceInstallTool().execute(user=user)

    assert linux_as_root["checked"] == (user, [EXE, "--help"])
    assert linux_as_root["spec"].user == user
    assert linux_as_root["start"] is True
    assert "# OPENAI_API_KEY=" in linux_as_root["env"]
    assert result.user == user
    assert result.service == "hiro.service"
    assert result.manager == "systemd"
    assert result.secrets_file_created is True
    assert result.restart_command == "sudo systemctl restart hiro.service"
    assert result.logs == "journalctl -u hiro.service -f"


def test_install_as_root_defaults_to_the_installing_user(linux_as_root) -> None:
    service_tools.ServiceInstallTool().execute()
    assert linux_as_root["spec"].user == "michel"


def test_the_default_service_sets_up_the_front_door_and_is_given_its_address(linux_as_root) -> None:
    result = service_tools.ServiceInstallTool().execute(user="michel")
    # Set up for the core's account (it joins Caddy's group), before the core starts with the address.
    assert linux_as_root["door"] == "michel"
    assert linux_as_root["spec"].environment["HIRO_FRONT_DOOR"] == "unix//run/hiro-caddy/admin.sock|0660"
    assert (result.front_door, result.front_door_account) == ("hiro-caddy.service", "hiro-caddy")


def test_a_named_workspace_leaves_the_machines_front_door_alone(linux_as_root) -> None:
    result = service_tools.ServiceInstallTool().execute(user="michel", workspace="home")
    assert "door" not in linux_as_root and "HIRO_FRONT_DOOR" not in linux_as_root["spec"].environment
    assert result.front_door is None


def test_caddys_unit_binds_port_80_by_its_capability_alone_and_resumes_what_it_had() -> None:
    from pathlib import PurePosixPath

    unit = door.render_linux_unit(PurePosixPath("/opt/hiroleague/caddy/2.11.9/caddy"))
    for line in (
        "User=hiro-caddy", "Group=hiro-caddy", "Type=notify",
        "AmbientCapabilities=CAP_NET_BIND_SERVICE", "CapabilityBoundingSet=CAP_NET_BIND_SERVICE",
        "RuntimeDirectory=hiro-caddy", "RuntimeDirectoryMode=0750",
        "Environment=XDG_CONFIG_HOME=/opt/hiroleague/caddy/config",
        "ExecStart=/opt/hiroleague/caddy/2.11.9/caddy run --resume --config /opt/hiroleague/caddy/initial.json",
        "Restart=on-failure", "WantedBy=multi-user.target",
    ):
        assert f"\n{line}\n" in unit, line


def test_service_tools_are_cli_only() -> None:
    for tool in (
        service_tools.ServiceInstallTool, service_tools.ServiceUninstallTool, service_tools.ServiceStatusTool,
        service_tools.ServiceStartTool, service_tools.ServiceStopTool,
    ):
        assert tool.surfaces == frozenset({"cli"})


def test_cli_install_without_root_prints_sudo_command(linux_as_user) -> None:
    from hirocli.commands.app import app

    result = CliRunner().invoke(app, ["service", "install", "--user", "hiro"])
    assert result.exit_code == 1
    assert "needs root" in result.output
    assert f"sudo {EXE} service install --user hiro" in result.output


def test_cli_status_when_not_installed(monkeypatch, linux_as_user) -> None:
    from hirocli.commands.app import app

    monkeypatch.setattr(service_linux, "service_state", lambda name: sd.ServiceState(name=name, installed=False))
    result = CliRunner().invoke(app, ["service", "status"])
    assert result.exit_code == 1
    assert "hiro.service is not installed" in result.output
    assert f"sudo {EXE} service install" in result.output


def test_cli_start_without_root_prints_sudo_command(linux_as_user) -> None:
    from hirocli.commands.app import app

    result = CliRunner().invoke(app, ["service", "stop"])
    assert result.exit_code == 1
    assert f"sudo {EXE} service stop" in result.output


def test_unsupported_system_says_so(monkeypatch) -> None:
    from hirocli.commands.app import app

    monkeypatch.setattr(service_tools, "current_system", lambda: "freebsd14")
    result = CliRunner().invoke(app, ["service", "status"])
    assert result.exit_code == 1
    assert "not supported" in result.output


def test_foreground_start_when_already_running_fails(monkeypatch) -> None:
    # Under systemd a do-nothing foreground start must not exit 0 (the service would look stopped
    # with no error); a background start keeps reporting "already running" as before.
    from hirocli.commands.app import app
    from hirocli.tools import server as server_tools
    from hirocli.tools.server_models import StartResult

    result_obj = StartResult(
        workspace="default", workspace_path="/x", already_running=True, pid=123,
        http_host="127.0.0.1", http_port=18080, admin_port=None,
    )
    monkeypatch.setattr(server_tools.StartTool, "execute", lambda self, **kw: result_obj)

    fg = CliRunner().invoke(app, ["start", "--foreground", "--no-admin"])
    assert fg.exit_code == 1
    assert "already running" in fg.output

    bg = CliRunner().invoke(app, ["start", "--no-admin"])
    assert bg.exit_code == 0
