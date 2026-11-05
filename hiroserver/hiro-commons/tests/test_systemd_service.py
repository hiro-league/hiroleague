from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hiro_commons import systemd_service as sd
from hiro_commons.timestamps import human_datetime


def _spec(**overrides) -> sd.ServiceSpec:
    values = dict(
        name="hiro",
        description="HiroLeague server",
        user="hiro",
        group="hiro",
        exec_args=["/opt/hiroleague/current/bin/hiro", "start", "--foreground"],
        env_file=Path("/etc/hiro/hiro.env"),
        environment={"PYTHON_KEYRING_BACKEND": sd.NULL_KEYRING_BACKEND, "PATH": "/opt/hiroleague/current/bin:/usr/bin"},
        restart_exit_code=75,
        documentation="https://docs.example/linux-service",
    )
    values.update(overrides)
    return sd.ServiceSpec(**values)


def _unit_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def test_render_unit_runs_foreground_as_user_with_env_file_and_restart_policy() -> None:
    lines = _unit_lines(sd.render_unit(_spec()))

    assert "User=hiro" in lines
    assert "Group=hiro" in lines
    assert "WorkingDirectory=~" in lines
    assert "EnvironmentFile=/etc/hiro/hiro.env" in lines
    assert 'Environment="PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring"' in lines
    assert "ExecStart=/opt/hiroleague/current/bin/hiro start --foreground" in lines
    assert "Restart=on-failure" in lines
    assert "RestartForceExitStatus=75" in lines
    assert "WantedBy=multi-user.target" in lines
    assert "After=network-online.target" in lines
    assert "Documentation=https://docs.example/linux-service" in lines


def test_render_unit_without_restart_code_has_no_force_status() -> None:
    assert "RestartForceExitStatus" not in sd.render_unit(_spec(restart_exit_code=None))


def test_exec_args_with_spaces_percent_and_dollar_are_escaped() -> None:
    text = sd.render_unit(_spec(exec_args=["/opt/my apps/hiro", "start", "--workspace", "50%$off"]))
    assert 'ExecStart="/opt/my apps/hiro" start --workspace 50%%$$off' in text


def test_environment_values_are_quoted_and_escaped() -> None:
    text = sd.render_unit(_spec(environment={"NOTE": 'say "hi" 100%'}))
    assert 'Environment="NOTE=say \\"hi\\" 100%%"' in text


@pytest.mark.parametrize(
    "overrides",
    [
        {"exec_args": ["hiro", "start"]},  # not absolute
        {"exec_args": []},
        {"user": "root"},
        {"user": ""},
        {"name": "bad name"},
        {"environment": {"BAD-NAME": "x"}},
        {"environment": {"OK": "two\nlines"}},
    ],
)
def test_render_unit_rejects_unsafe_specs(overrides) -> None:
    with pytest.raises(sd.ServiceError):
        sd.render_unit(_spec(**overrides))


def test_paths_follow_the_service_name() -> None:
    assert sd.unit_path("hiro-home").as_posix() == "/etc/systemd/system/hiro-home.service"
    assert sd.env_file_path("hiro-home").as_posix() == "/etc/hiro/hiro-home.env"


def test_render_env_file_lists_every_variable_commented_out() -> None:
    text = sd.render_env_file(
        service_name="hiro",
        user="hiro",
        restart_command="sudo systemctl restart hiro.service",
        sections=[("Provider API keys", ["OPENAI_API_KEY", "GOOGLE_API_KEY"]), ("Empty", [])],
    )
    assert "# OPENAI_API_KEY=" in text
    assert "# GOOGLE_API_KEY=" in text
    assert "Empty" not in text  # empty sections are left out
    assert "0600" in text
    assert "sudo systemctl restart hiro.service" in text
    # Nothing is set by default: every non-blank line is a comment.
    assert all(line.startswith("#") for line in text.splitlines() if line.strip())


def test_needs_root_error_names_the_command() -> None:
    exc = sd.NeedsRootError("Installing the HiroLeague service", "sudo /x/hiro service install --user michel")
    assert exc.command == "sudo /x/hiro service install --user michel"
    assert "needs root" in str(exc)
    assert exc.command in str(exc)


def test_parse_show_output_reads_running_service() -> None:
    text = "\n".join(
        [
            "LoadState=loaded",
            "ActiveState=active",
            "SubState=running",
            "UnitFileState=enabled",
            "MainPID=4242",
            "ActiveEnterTimestamp=@1762348546",
            "User=hiro",
            "NRestarts=2",
            "FragmentPath=/etc/systemd/system/hiro.service",
        ]
    )
    state = sd.parse_show_output("hiro", text)
    assert state.installed
    assert state.active_state == "active"
    assert state.sub_state == "running"
    assert state.enabled_state == "enabled"
    assert state.main_pid == 4242
    assert state.active_since == datetime.fromtimestamp(1762348546, UTC)
    assert state.user == "hiro"
    assert state.restarts == 2
    assert state.unit_path == Path("/etc/systemd/system/hiro.service")


def test_parse_show_output_unknown_unit_is_not_installed() -> None:
    state = sd.parse_show_output("hiro", "LoadState=not-found\nActiveState=inactive\nMainPID=0\nActiveEnterTimestamp=\n")
    assert not state.installed
    assert state.main_pid is None
    assert state.active_since is None


def test_system_operations_refuse_non_linux(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(sd.ServiceError, match="only available on Linux"):
        sd.require_linux()


def test_default_service_user_is_the_sudo_caller(monkeypatch) -> None:
    monkeypatch.setattr(sd, "is_root", lambda: True)
    monkeypatch.setenv("SUDO_USER", "michel")
    assert sd.default_service_user() == "michel"


def test_default_service_user_without_sudo_is_current_user(monkeypatch) -> None:
    import getpass

    monkeypatch.setattr(sd, "is_root", lambda: False)
    monkeypatch.setenv("SUDO_USER", "someone-else")
    assert sd.default_service_user() == getpass.getuser()


@pytest.mark.skipif(not hasattr(os, "chown"), reason="needs POSIX file ownership")
def test_write_env_file_creates_0600_and_keeps_existing(tmp_path) -> None:
    user = sd.ServiceUser(name="me", uid=os.getuid(), gid=os.getgid(), group="me", home=tmp_path)
    path = tmp_path / "etc" / "hiro.env"

    assert sd.write_env_file(path, "# first\n", user) is True
    assert (path.stat().st_mode & 0o777) == 0o600

    path.write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    os.chmod(path, 0o644)
    assert sd.write_env_file(path, "# template\n", user) is False
    assert path.read_text(encoding="utf-8") == "OPENAI_API_KEY=secret\n"
    assert (path.stat().st_mode & 0o777) == 0o600


def _local(*args: int) -> datetime:
    # Built per moment (not .replace() on one aware value) so DST changes between dates don't shift the clock.
    return datetime(*args).astimezone()


def test_human_datetime_says_which_day_in_12_hour_clock() -> None:
    now = _local(2026, 11, 5, 15, 0)
    assert human_datetime(_local(2026, 11, 5, 13, 15), now) == "Today, 1:15 PM"
    assert human_datetime(_local(2026, 11, 4, 23, 57), now) == "Yesterday, 11:57 PM"
    assert human_datetime(_local(2026, 9, 28, 9, 5), now) == "Mon, Sep 28, 9:05 AM"
    assert human_datetime(_local(2025, 12, 27, 0, 5), now) == "Sat, Dec 27, 2025, 12:05 AM"
