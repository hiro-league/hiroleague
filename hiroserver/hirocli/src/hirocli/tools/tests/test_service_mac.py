"""`hiro service` on a Mac (a LaunchDaemon), as far as it can be tested without a Mac: the plist the install writes,
what it asks root for, and the order of the install."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from hiro_commons import launchd_service as ld
from hiro_commons.env_file import parse_env_text
from hiro_commons.systemd_service import NeedsRootError, ServiceUser
from hirocli import front_door_setup as door
from hirocli import linux_service as ls
from hirocli import mac_service as ms
from hirocli.constants import ENV_SECRETS_FILE, ENV_SERVICE_MANAGER
from hirocli.tools import service as service_tools
from hirocli.tools import service_mac

EXE = "/Users/michel/.local/bin/hiro"
USER = ServiceUser(name="michel", uid=501, gid=20, group="staff", home=Path("/Users/michel"))


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(service_tools, "current_system", lambda: "darwin")
    monkeypatch.setattr(service_mac, "require_mac", lambda: None)
    monkeypatch.setattr(service_mac, "_is_root", lambda: False)
    monkeypatch.setattr(service_mac, "default_service_user", lambda: "michel")
    monkeypatch.setattr(ls, "hiro_executable", lambda: EXE)


@pytest.fixture
def mac_as_root(monkeypatch, mac):
    calls: list[tuple] = []
    monkeypatch.setattr(service_mac, "_is_root", lambda: True)
    monkeypatch.setattr(service_mac, "resolve_service_user", lambda name: USER)
    monkeypatch.setattr(ms, "check_user_can_run", lambda user, exe: calls.append(("check", user.name, exe)))
    monkeypatch.setattr(ms, "prepare_home", lambda user, workspace: calls.append(("home", user.name)))

    def fake_env(path, content, user):
        calls.append(("secrets", path, content))
        return True

    monkeypatch.setattr(service_mac, "write_env_file", fake_env)

    def fake_install(spec):
        calls.append(("install", spec))
        return ld.plist_path(spec.label)

    monkeypatch.setattr(service_mac, "install_service", fake_install)

    def fake_door(user, home):
        calls.append(("front_door", user.name))
        return door.FrontDoorSetup(admin=door.mac_admin(home), program="caddy", service=door.MAC_LABEL,
                                   account=user.name)

    monkeypatch.setattr(door, "install_mac", fake_door)
    return calls


def test_names_and_paths_follow_the_workspace() -> None:
    assert ms.label(None) == "com.hiroleague.hiro"
    assert ms.label("home") == "com.hiroleague.hiro-home"
    assert ms.secrets_file(None).as_posix() == "/Library/Application Support/HiroLeague/hiro.env"
    assert ms.log_file("home").as_posix() == "/Library/Application Support/HiroLeague/logs/hiro-home.log"


def test_spec_runs_the_server_as_the_user_with_its_secrets_file() -> None:
    spec = ms.build_spec(exe=EXE, user=USER, workspace=None)
    doc = plistlib.loads(ld.render_plist(spec))

    assert doc["ProgramArguments"] == [EXE, "start", "--foreground"]
    assert doc["UserName"] == "michel"
    assert doc["KeepAlive"] == {"SuccessfulExit": False}
    env = doc["EnvironmentVariables"]
    assert env[ENV_SERVICE_MANAGER] == "launchd"
    assert env[ENV_SECRETS_FILE] == "/Library/Application Support/HiroLeague/hiro.env"
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert env["PATH"].startswith("/Users/michel/.local/bin:")
    assert env["HOME"] == "/Users/michel"


def test_secrets_template_says_how_to_reload() -> None:
    text = ms.env_file_content("hiro", "michel", None)
    assert "# OPENAI_API_KEY=" in text
    assert "sudo launchctl kickstart -k system/com.hiroleague.hiro" in text
    assert parse_env_text(text) == ({}, [])


def test_install_without_root_says_exactly_what_to_run_and_why(mac) -> None:
    with pytest.raises(NeedsRootError) as info:
        service_tools.ServiceInstallTool().execute(workspace="home")
    assert info.value.command == f"sudo {EXE} service install --user michel --workspace home"
    assert "/Library/LaunchDaemons" in info.value.why
    assert "systemd" not in str(info.value)


def test_install_as_root_checks_the_user_then_writes_secrets_then_loads_it(mac_as_root) -> None:
    result = service_tools.ServiceInstallTool().execute()

    assert [c[0] for c in mac_as_root] == ["check", "home", "secrets", "front_door", "install"]
    spec = mac_as_root[-1][1]
    assert spec.environment["HIRO_FRONT_DOOR"] == "unix//Library/Application Support/HiroLeague/caddy/run/admin.sock"
    assert spec.label == "com.hiroleague.hiro"
    assert spec.user == "michel"
    assert result.manager == "launchd"
    assert result.definition_path == "/Library/LaunchDaemons/com.hiroleague.hiro.plist"
    assert result.restart_command == "sudo launchctl kickstart -k system/com.hiroleague.hiro"


def test_the_cores_name_reaches_the_service_for_its_new_workspace(mac_as_root) -> None:
    service_tools.ServiceInstallTool().execute(core_name="testpc")
    assert mac_as_root[-1][1].environment["HIRO_CORE_NAME"] == "testpc"


def test_stop_without_root_says_what_to_run(mac) -> None:
    with pytest.raises(NeedsRootError) as info:
        service_tools.ServiceStopTool().execute()
    assert info.value.command == f"sudo {EXE} service stop"


def test_status_counts_restarts_from_launchd_runs(mac, monkeypatch) -> None:
    monkeypatch.setattr(
        service_mac, "service_state",
        lambda label: ld.ServiceState(label=label, installed=True, state="running", pid=812, runs=3, last_exit_code=75),
    )
    monkeypatch.setattr(service_mac, "_plist_user", lambda label: "michel")
    result = service_tools.ServiceStatusTool().execute()
    assert (result.running, result.main_pid, result.restarts, result.user) == (True, 812, 2, "michel")
    assert result.at_boot is True
