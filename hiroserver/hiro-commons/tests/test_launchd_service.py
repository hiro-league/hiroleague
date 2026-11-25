"""The Mac's LaunchDaemon, as far as it can be tested without a Mac: the plist and launchctl's answers."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from hiro_commons import launchd_service as ld
from hiro_commons.systemd_service import ServiceError


def _spec(**overrides) -> ld.LaunchdSpec:
    values = dict(
        label="com.hiroleague.hiro",
        user="michel",
        program_args=["/Users/michel/.local/bin/hiro", "start", "--foreground"],
        working_directory=Path("/Users/michel"),
        log_path=Path("/Library/Application Support/HiroLeague/logs/hiro.log"),
        environment={"HIRO_SERVICE_MANAGER": "launchd", "HIRO_SECRETS_FILE": "/Library/Application Support/HiroLeague/hiro.env"},
    )
    values.update(overrides)
    return ld.LaunchdSpec(**values)


def test_plist_runs_the_program_at_boot_as_the_user_and_restarts_like_on_failure() -> None:
    doc = plistlib.loads(ld.render_plist(_spec()))

    assert doc["Label"] == "com.hiroleague.hiro"
    assert doc["ProgramArguments"] == ["/Users/michel/.local/bin/hiro", "start", "--foreground"]
    assert doc["UserName"] == "michel"
    assert doc["RunAtLoad"] is True
    # Restart=on-failure: any exit but 0 (75 included) or a crash starts it again; a clean exit stays stopped.
    assert doc["KeepAlive"] == {"SuccessfulExit": False}
    assert doc["ThrottleInterval"] == 5
    assert doc["ExitTimeOut"] == 60
    assert doc["EnvironmentVariables"]["HIRO_SERVICE_MANAGER"] == "launchd"
    assert doc["StandardErrorPath"] == "/Library/Application Support/HiroLeague/logs/hiro.log"
    assert doc["WorkingDirectory"] == "/Users/michel"


def test_no_secret_value_goes_in_the_plist_only_the_file_name() -> None:
    raw = ld.render_plist(_spec())
    assert b"HIRO_SECRETS_FILE" in raw
    assert b"API_KEY" not in raw


def test_root_a_relative_program_and_bad_names_are_refused() -> None:
    with pytest.raises(ServiceError, match="not root"):
        ld.render_plist(_spec(user="root"))
    with pytest.raises(ServiceError, match="absolute"):
        ld.render_plist(_spec(program_args=["hiro", "start"]))
    with pytest.raises(ServiceError, match="label"):
        ld.render_plist(_spec(label="com.hiroleague.my hiro"))
    with pytest.raises(ServiceError, match="environment variable"):
        ld.render_plist(_spec(environment={"BAD NAME": "x"}))


def test_paths_and_targets_follow_the_label() -> None:
    assert ld.plist_path("com.hiroleague.hiro-home").as_posix() == "/Library/LaunchDaemons/com.hiroleague.hiro-home.plist"
    assert ld.service_target("com.hiroleague.hiro") == "system/com.hiroleague.hiro"


# What `launchctl print system/<label>` answers for a running daemon (macOS 14), trimmed. Nested blocks carry
# fields with the same names (`state`, `pid`) that belong to other things and must not be read.
PRINT_RUNNING = """system/com.hiroleague.hiro = {
\tactive count = 1
\tpath = /Library/LaunchDaemons/com.hiroleague.hiro.plist
\ttype = LaunchDaemon
\tstate = running

\tprogram = /Users/michel/.local/bin/hiro
\targuments = {
\t\tstart
\t\t--foreground
\t}

\tenvironment = {
\t\tstate = not-a-service-field
\t}

\truns = 3
\tpid = 812
\tlast exit code = 75
}
"""


def test_parse_print_output_reads_the_service_own_fields() -> None:
    state = ld.parse_print_output("com.hiroleague.hiro", PRINT_RUNNING)
    assert state.installed is True
    assert state.state == "running"
    assert state.pid == 812
    assert state.runs == 3
    assert state.last_exit_code == 75
    assert state.plist_path == Path("/Library/LaunchDaemons/com.hiroleague.hiro.plist")


def test_parse_print_output_of_a_stopped_daemon() -> None:
    text = "system/com.hiroleague.hiro = {\n\tstate = not running\n\truns = 1\n\tlast exit code = 0\n}\n"
    state = ld.parse_print_output("com.hiroleague.hiro", text)
    assert state.state == "not running"
    assert state.pid is None
    assert state.last_exit_code == 0


def test_system_calls_refuse_another_system(monkeypatch) -> None:
    monkeypatch.setattr(ld.sys, "platform", "win32")
    with pytest.raises(ServiceError, match="not a Mac"):
        ld.service_state("com.hiroleague.hiro")
