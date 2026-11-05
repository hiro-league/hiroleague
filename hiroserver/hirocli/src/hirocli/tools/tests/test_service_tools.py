"""`hiro service` (Linux systemd): unit/env generation and argument handling, without systemd."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hiro_commons import systemd_service as sd
from hirocli import linux_service as ls
from hirocli.constants import ENV_SERVICE_MANAGER, SERVICE_RESTART_EXIT_CODE
from hirocli.tools import service as service_tools

EXE = "/opt/hiroleague/current/bin/hiro"


@pytest.fixture
def linux_as_user(monkeypatch):
    """Pretend to be a non-root user on Linux with `hiro` at EXE."""
    monkeypatch.setattr(service_tools, "require_linux", lambda: None)
    monkeypatch.setattr(service_tools, "is_root", lambda: False)
    monkeypatch.setattr(service_tools, "default_service_user", lambda: "michel")
    monkeypatch.setattr(ls, "hiro_executable", lambda: EXE)


@pytest.fixture
def linux_as_root(monkeypatch, linux_as_user):
    """Pretend to be root on Linux; record what would be installed instead of touching /etc."""
    monkeypatch.setattr(service_tools, "is_root", lambda: True)
    monkeypatch.setattr(
        service_tools,
        "resolve_service_user",
        lambda name: sd.ServiceUser(name=name, uid=1001, gid=1001, group=name, home=Path(f"/var/lib/{name}")),
    )
    calls: dict = {}
    monkeypatch.setattr(service_tools, "check_user_can_run", lambda user, args: calls.setdefault("checked", (user.name, args)))

    def fake_install(spec, user, env_content, *, start=True):
        calls.update(spec=spec, user=user.name, env=env_content, start=start)
        return True

    monkeypatch.setattr(service_tools, "install_service", fake_install)
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
    assert result.env_file_created is True


def test_install_as_root_defaults_to_the_installing_user(linux_as_root) -> None:
    service_tools.ServiceInstallTool().execute()
    assert linux_as_root["spec"].user == "michel"


def test_service_tools_are_cli_only() -> None:
    for tool in (service_tools.ServiceInstallTool, service_tools.ServiceUninstallTool, service_tools.ServiceStatusTool):
        assert tool.surfaces == frozenset({"cli"})


def test_cli_install_without_root_prints_sudo_command(linux_as_user) -> None:
    from hirocli.commands.app import app

    result = CliRunner().invoke(app, ["service", "install", "--user", "hiro"])
    assert result.exit_code == 1
    assert "needs root" in result.output
    assert f"sudo {EXE} service install --user hiro" in result.output


def test_cli_status_when_not_installed(monkeypatch, linux_as_user) -> None:
    from hirocli.commands.app import app

    monkeypatch.setattr(service_tools, "service_state", lambda name: sd.ServiceState(name=name, installed=False))
    result = CliRunner().invoke(app, ["service", "status"])
    assert result.exit_code == 1
    assert "hiro.service is not installed" in result.output
    assert f"sudo {EXE} service install" in result.output


def test_cli_service_on_windows_explains_it_is_linux_only(monkeypatch) -> None:
    from hirocli.commands.app import app

    monkeypatch.setattr(sd.sys, "platform", "win32")
    result = CliRunner().invoke(app, ["service", "status"])
    assert result.exit_code == 1
    assert "only available on Linux" in result.output


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
