"""The elevated system part's job check (domain/system_job.py) and what it writes on each system (app_system.py), as
text: nothing here touches the system."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from hirocli import app_system
from hirocli.domain.system_job import INSTALL, JobRefused, SystemJob, check_job

HOME = PurePosixPath("/opt/hiroleague")


def app(key: str = "example.hello", command: str = "example-hello"):
    return check_job(SystemJob(action="install", key=key, command=command), HOME)  # type: ignore[arg-type]


def test_a_job_becomes_names_and_a_folder_the_system_part_works_out_itself() -> None:
    a = app()
    assert (a.service, a.account) == ("hiro-example-hello", "hiro-example-hello")
    assert a.folder.root.as_posix() == "/opt/hiroleague/apps/example.hello"


@pytest.mark.parametrize(
    ("job", "words"),
    [
        (SystemJob(action="install", key="../etc", command="x"), "isn't name or publisher.name"),
        (SystemJob(action="install", key="weather", command="x"), "no publisher"),
        (SystemJob(action="install", key="hiroleague", command="x"), "HiroLeague's own"),
        (SystemJob(action="install", key="hiro.evil", command="x"), "reserved"),
        (SystemJob(action="install", key="acme.weather", command="/bin/sh"), "program name"),
        (SystemJob(action="install", key="acme.weather", command="x; rm -rf /"), "program name"),
        (SystemJob(action="install", key="acme.weather", command="x", purge=True), "can't purge"),
    ],
)
def test_the_system_part_refuses_a_job_outside_its_rule(job: SystemJob, words: str) -> None:
    with pytest.raises(JobRefused, match=words):
        check_job(job, HOME)  # type: ignore[arg-type]


def test_a_job_carries_no_account_folder_or_service_of_its_own() -> None:
    with pytest.raises(ValueError):
        SystemJob.model_validate({"action": "install", "key": "acme.weather", "command": "x", "folder": "/etc"})
    assert check_job(SystemJob(action="remove", key="home"), HOME).folder.root.as_posix() == "/opt/hiroleague/apps/home"  # type: ignore[arg-type]
    assert INSTALL == "install"


def test_the_linux_unit_runs_the_app_as_its_account_with_its_env_file() -> None:
    unit = app_system.linux_unit(app(), "michelhabib")
    assert "User=hiro-example-hello" in unit and "Group=michelhabib" in unit
    assert "EnvironmentFile=/opt/hiroleague/apps/example.hello/app.env" in unit
    assert "ExecStart=/opt/hiroleague/apps/example.hello/current/bin/example-hello" in unit
    assert "UMask=0007" in unit


def test_the_polkit_rule_names_one_unit_one_account_and_three_verbs() -> None:
    rule = app_system.polkit_rule("hiro-example-hello", "michelhabib")
    assert 'action.lookup("unit") == "hiro-example-hello.service"' in rule
    assert 'subject.user == "michelhabib"' in rule
    assert '["start", "stop", "restart"]' in rule
    with pytest.raises(JobRefused):
        app_system.polkit_rule("hiro-x", 'a" || true || "')


def test_the_core_gets_start_and_stop_on_the_service_before_its_audit_part() -> None:
    sid = "S-1-5-80-1-2-3-4-5"
    sddl = "D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)S:(AU;FA;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;WD)"
    out = app_system.with_core_ace(sddl, sid)
    assert out.startswith("D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)")
    assert f"(A;;{app_system.CORE_SERVICE_RIGHTS};;;{sid})S:(AU;" in out
    assert app_system.with_core_ace(out, sid) == out  # once only
    with pytest.raises(Exception, match="SID"):
        app_system.with_core_ace(sddl, "S-1-5;;;WD")


def test_the_mac_daemon_sources_app_env_and_the_sudoers_line_names_one_daemon() -> None:
    a = app()
    plist = app_system.mac_plist(a)
    assert "<key>UserName</key><string>hiro-example-hello</string>" in plist
    assert ". &apos;/opt/hiroleague/apps/example.hello/app.env&apos;" in plist or "/apps/example.hello/app.env" in plist
    sudoers = app_system.mac_sudoers(a, "michel")
    assert sudoers.count("NOPASSWD") == 1 and "com.hiroleague.app.example-hello" in sudoers
