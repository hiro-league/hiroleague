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


def test_the_mac_daemon_runs_as_the_app_and_sources_app_env() -> None:
    import plistlib

    a = check_job(SystemJob(action="install", key="example.hello", command="example-hello"),
                  PurePosixPath("/Library/Application Support/HiroLeague"))  # type: ignore[arg-type]
    plist = plistlib.loads(app_system.mac_plist(a))
    assert plist["Label"] == "com.hiroleague.app.example-hello" and plist["UserName"] == "hiro-example-hello"
    assert plist["KeepAlive"] == {"SuccessfulExit": False}  # as the core's own: a clean stop stays stopped
    home = "/Library/Application Support/HiroLeague/apps/example.hello"
    assert plist["ProgramArguments"] == [
        "/bin/sh", "-c", f"set -a; . '{home}/app.env'; set +a; exec '{home}/current/bin/example-hello'"]
    assert plist["WorkingDirectory"] == f"{home}/data"
    assert plist["EnvironmentVariables"] == {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}  # secrets: app.env


def test_the_sudoers_line_names_one_daemon_and_two_exact_commands() -> None:
    sudoers = app_system.mac_sudoers(app(), "michel")
    assert sudoers.count("NOPASSWD") == 1
    assert ("michel ALL=(root) NOPASSWD: /bin/launchctl bootstrap system "
            "/Library/LaunchDaemons/com.hiroleague.app.example-hello.plist, "
            "/bin/launchctl bootout system/com.hiroleague.app.example-hello") in sudoers
    assert "." not in app_system.mac_sudoers_path("hiro-example-hello").name  # sudo skips a name with a dot
    with pytest.raises(JobRefused):
        app_system.mac_sudoers(app(), "michel ALL=(ALL) NOPASSWD: ALL")


def test_a_mac_account_takes_the_first_id_free_for_both_accounts_and_groups() -> None:
    assert app_system.free_mac_id({400, 401, 403}) == 402
    with pytest.raises(app_system.ServiceError, match="No id is free"):
        app_system.free_mac_id(set(app_system.MAC_IDS))
    assert app_system.mac_ace("hiro-x", "list,search") == "user:hiro-x allow list,search,file_inherit,directory_inherit"


def test_an_account_macos_wont_delete_is_kept_and_any_other_failure_raises(monkeypatch) -> None:
    import subprocess

    def dscl(stderr: str, code: int):
        return lambda cmd, what, ok_codes=(0,): subprocess.CompletedProcess(cmd, code, "", stderr)

    # What macOS answers a delete over SSH (its privacy control), seen on the Mac test VM, Nov 27
    monkeypatch.setattr(app_system, "_run", dscl("<main> delete status: eDSPermissionError", 40))
    assert app_system._mac_delete("Users", "hiro-example-hello") is False
    monkeypatch.setattr(app_system, "_run", dscl("<main> delete status: eDSRecordNotFound", 40))
    with pytest.raises(app_system.ServiceError, match="eDSRecordNotFound"):
        app_system._mac_delete("Users", "hiro-example-hello")
    monkeypatch.setattr(app_system, "_run", dscl("", 0))
    assert app_system._mac_delete("Groups", "hiro-example-hello") is True


def test_a_mac_stop_returns_once_the_app_has_exited(monkeypatch) -> None:
    # launchctl bootout returned while the app was still stopping ("SIGTERMed"), seen on the Mac test VM, Nov 27
    import hiro_commons.launchd_service as launchd

    answers = iter([True, True, True, False])  # loaded, then two looks while it stops, then gone
    monkeypatch.setattr(launchd, "service_state", lambda label: launchd.ServiceState(label, installed=next(answers)))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(app_system, "_launchctl", lambda *args: calls.append(args))
    monkeypatch.setattr("time.sleep", lambda s: None)
    app_system._mac_stop("hiro-example-hello")
    assert calls == [("bootout", "system/com.hiroleague.app.example-hello")]
    with pytest.raises(StopIteration):
        next(answers)  # it asked until the daemon was gone


def test_a_windows_purge_removes_read_only_files_too(tmp_path, monkeypatch) -> None:
    # git writes its packs read-only (CodeHiro's mirrors), and Windows refused the purge on them ("Access is denied")
    import stat

    import hiro_commons.winsw_service as winsw

    monkeypatch.setattr(winsw, "remove_service", lambda name: True)
    a = check_job(SystemJob(action="remove", key="code", purge=True), tmp_path)  # type: ignore[arg-type]
    pack = a.folder.root / "data" / "mirrors" / "x.git" / "objects" / "pack" / "pack-1.idx"
    pack.parent.mkdir(parents=True)
    pack.write_bytes(b"idx")
    pack.chmod(stat.S_IREAD)
    done = app_system.remove_windows(a, purge=True)
    assert done.purged and not a.folder.root.exists()
