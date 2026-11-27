"""`hiro service` on Windows (WinSW): the layout, the service's settings, the order of the install, the elevation;
without touching the service manager."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hiro_commons import winsw_service as w
from hiro_commons.env_file import parse_env_text
from hiro_commons.systemd_service import ServiceError
from hirocli import cpp_runtime
from hirocli import front_door_setup as door
from hirocli import linux_service as ls
from hirocli import windows_service as ws
from hirocli.constants import ENV_DATA_DIR, ENV_SECRETS_FILE, ENV_SERVICE_MANAGER
from hirocli.tools import service as service_tools
from hirocli.tools import service_windows

EXE = r"C:\Users\michel\.local\bin\hiro.exe"
HOME = Path(r"D:\HiroLeague")


@pytest.fixture
def windows(monkeypatch):
    """Pretend to be Windows with `hiro` at EXE, not elevated."""
    monkeypatch.setattr(service_tools, "current_system", lambda: "win32")
    monkeypatch.setattr(service_windows, "require_windows", lambda: None)
    monkeypatch.setattr(service_windows, "is_admin", lambda: False)
    monkeypatch.setattr(ls, "hiro_executable", lambda: EXE)


@pytest.fixture
def elevated(monkeypatch, windows):
    """An administrator; every system step recorded, in order, instead of done."""
    calls: list[tuple] = []
    monkeypatch.setattr(service_windows, "is_admin", lambda: True)
    monkeypatch.setattr(service_windows, "require_permissions_disk", lambda path, label: calls.append(("disk", path)))
    monkeypatch.setattr(service_windows, "lock_program_folder", lambda path: calls.append(("lock_program", path)))
    monkeypatch.setattr(Path, "mkdir", lambda self, **kw: None)
    exe = HOME / "releases" / "20261125T120000Z" / "bin" / "hiro.exe"

    def fake_release(lay, source):
        calls.append(("release", source))
        return exe

    monkeypatch.setattr(ws, "install_release", fake_release)
    monkeypatch.setattr(ws, "copy_uv_into", lambda home: calls.append(("uv", home)))

    def fake_runtime(cache):
        calls.append(("cpp_runtime", cache))
        return "installed now (Microsoft's Visual C++ Redistributable)"

    monkeypatch.setattr(cpp_runtime, "install", fake_runtime)
    monkeypatch.setattr(door, "which_python", lambda release: HOME / "python" / "cpython-3.12" / "python.exe")

    def fake_door(home, core_python):
        calls.append(("front_door", home, core_python))
        return door.FrontDoorSetup(admin=door.WINDOWS_ADMIN, program=str(home / "caddy" / "caddy.exe"),
                                   service="hiro-caddy", account=r"NT SERVICE\hiro-caddy",
                                   firewall=[door.RULE_CADDY, door.RULE_NAMES])

    monkeypatch.setattr(door, "install_windows", fake_door)
    monkeypatch.setattr(service_windows, "install_service", lambda spec, folder: calls.append(("register", spec, folder)))
    monkeypatch.setattr(service_windows, "grant_read", lambda path, *, service_id: calls.append(("grant_read", path)))
    monkeypatch.setattr(
        service_windows, "lock_folder",
        lambda path, *, service_id, service_rights: calls.append(("lock_data", path, service_id, service_rights)),
    )

    def fake_secrets(path, content):
        calls.append(("secrets", path, content))
        return True

    monkeypatch.setattr(ws, "write_secrets_file", fake_secrets)
    monkeypatch.setattr(service_windows, "lock_file", lambda path, *, service_id: calls.append(("lock_secrets", path)))
    monkeypatch.setattr(
        service_windows, "start_service",
        lambda name: calls.append(("start", name)) or w.ServiceState(name=name, installed=True, state="RUNNING"),
    )
    return calls


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths join only on Windows")
def test_layout_defaults_to_programdata_and_takes_other_folders(monkeypatch) -> None:
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    lay = ws.layout(None, None)
    assert lay.home == Path(r"C:\ProgramData\HiroLeague")
    assert lay.data_dir == Path(r"C:\ProgramData\HiroLeague\data")
    assert lay.logs_dir == Path(r"C:\ProgramData\HiroLeague\data\service-logs")
    assert lay.secrets_file("hiro") == Path(r"C:\ProgramData\HiroLeague\hiro.env")

    lay = ws.layout(r"D:\HiroLeague", r"E:\HiroData")
    assert (lay.home, lay.data_dir, lay.python_dir) == (Path(r"D:\HiroLeague"), Path(r"E:\HiroData"), Path(r"D:\HiroLeague\python"))


def test_layout_refuses_a_relative_folder() -> None:
    with pytest.raises(ServiceError, match="--data-dir must be a full path"):
        ws.layout(None, "HiroData")


def test_spec_runs_the_server_under_winsw_with_its_own_data_and_secrets() -> None:
    lay = ws.Layout(home=HOME, data_dir=HOME / "data")
    exe = HOME / "releases" / "r1" / "bin" / "hiro.exe"
    spec = ws.build_spec(exe=exe, lay=lay, workspace=None)

    assert spec.id == "hiro"
    assert spec.account == r"NT SERVICE\hiro"
    assert spec.arguments == ["start", "--foreground"]
    env = spec.environment
    assert env[ENV_SERVICE_MANAGER] == "winsw"
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert env[ENV_SECRETS_FILE] == str(HOME / "hiro.env")
    assert env[ENV_DATA_DIR] == str(HOME / "data")
    # hirogate and the channel plugins sit beside hiro.exe; nothing for WinSW to expand.
    assert env["PATH"].startswith(str(exe.parent) + ";")
    assert "%" not in w.render_config(spec)


def test_spec_for_a_named_workspace_is_a_service_of_its_own() -> None:
    lay = ws.Layout(home=HOME, data_dir=HOME / "data")
    spec = ws.build_spec(exe=HOME / "bin" / "hiro.exe", lay=lay, workspace="home")
    assert spec.id == "hiro-home"
    assert spec.arguments[-2:] == ["--workspace", "home"]
    assert spec.environment[ENV_SECRETS_FILE] == str(HOME / "hiro-home.env")


def test_secrets_template_lists_provider_keys_and_sets_none() -> None:
    text = ws.env_file_content("hiro")
    assert "# OPENAI_API_KEY=" in text
    assert "NT SERVICE\\hiro" in text
    assert "Restart-Service hiro" in text
    assert "systemd" not in text
    assert parse_env_text(text) == ({}, [])


def test_exe_from_config_reads_the_registered_wrapper() -> None:
    assert ws.exe_from_config('"C:\\Program Data\\HiroLeague\\service\\hiro.exe"') == Path(r"C:\Program Data\HiroLeague\service\hiro.exe")
    assert ws.exe_from_config(r"C:\HiroLeague\service\hiro.exe") == Path(r"C:\HiroLeague\service\hiro.exe")
    assert ws.exe_from_config("") is None


def test_install_without_an_administrator_says_exactly_what_to_run(windows) -> None:
    with pytest.raises(w.NeedsAdminError) as info:
        service_tools.ServiceInstallTool().execute(home=r"D:\HiroLeague", data_dir=r"E:\Data", workspace="home")
    assert info.value.command == subprocess.list2cmdline(
        [EXE, "service", "install", "--home", r"D:\HiroLeague", "--data-dir", r"E:\Data", "--workspace", "home"]
    )


def test_install_without_an_administrator_keeps_the_name(windows) -> None:
    with pytest.raises(w.NeedsAdminError) as info:
        service_tools.ServiceInstallTool().execute(core_name="testpc")
    assert info.value.command == subprocess.list2cmdline([EXE, "service", "install", "--name", "testpc"])


def test_the_cores_name_reaches_the_service_for_its_new_workspace(elevated) -> None:
    service_tools.ServiceInstallTool().execute(home=str(HOME), core_name="testpc")
    spec = next(c[1] for c in elevated if c[0] == "register")
    assert spec.environment["HIRO_CORE_NAME"] == "testpc"


def test_install_registers_then_locks_the_data_then_starts(elevated) -> None:
    result = service_tools.ServiceInstallTool().execute(home=str(HOME), source=r"C:\hiro\env4\hiroleague\hiroserver\hiroleague")

    steps = [c[0] for c in elevated]
    assert steps == [
        "disk", "disk", "lock_program", "release", "uv", "cpp_runtime", "front_door", "register", "grant_read",
        "lock_data", "secrets", "lock_secrets", "start",
    ]
    assert elevated[3] == ("release", r"C:\hiro\env4\hiroleague\hiroserver\hiroleague")
    # The service core's own uv, in the home: it installs a channel with it before any app is installed.
    assert elevated[4] == ("uv", HOME)
    # Microsoft's C++ runtime before the service starts: the graph database can't load without it
    assert elevated[5] == ("cpp_runtime", HOME / "cache")
    assert result.cpp_runtime.startswith("installed now")
    # The front door's firewall rule for names follows the release's own Python; the core is given its address.
    assert elevated[6] == ("front_door", HOME, HOME / "python" / "cpython-3.12" / "python.exe")
    assert elevated[7][1].environment["HIRO_FRONT_DOOR"] == "127.0.0.1:18079"
    # The account exists only once registered, so it is given the program and the data after, and it starts last.
    assert elevated[8] == ("grant_read", HOME)
    assert elevated[9] == ("lock_data", HOME / "data", "hiro", "M")
    assert elevated[11] == ("lock_secrets", HOME / "hiro.env")
    assert result.front_door == "hiro-caddy" and result.firewall == [door.RULE_CADDY, door.RULE_NAMES]
    assert result.manager == "winsw"
    assert result.user == r"NT SERVICE\hiro"
    assert result.data_dir == str(HOME / "data")
    assert result.secrets_file == str(HOME / "hiro.env")
    assert result.definition_path == str(HOME / "service" / "hiro.xml")


def test_install_on_a_disk_with_no_permissions_changes_nothing(elevated, monkeypatch) -> None:
    def refuse(path, label):
        raise ServiceError(f"{label} {path} is on a exFAT disk, which has no permissions")

    monkeypatch.setattr(service_windows, "require_permissions_disk", refuse)
    with pytest.raises(ServiceError, match="exFAT"):
        service_tools.ServiceInstallTool().execute(home=str(HOME))
    assert elevated == []


def test_a_failed_release_install_leaves_no_folder(tmp_path, monkeypatch) -> None:
    lay = ws.Layout(home=tmp_path, data_dir=tmp_path / "data")
    monkeypatch.setattr(ws.shutil, "which", lambda name: r"C:\uv\uv.exe")

    def fake_run(cmd, **kw):
        Path(kw["env"]["UV_TOOL_BIN_DIR"]).mkdir(parents=True)  # uv got as far as making its folder
        return subprocess.CompletedProcess(cmd, 2)

    monkeypatch.setattr(ws.subprocess, "run", fake_run)
    with pytest.raises(ServiceError, match="uv exit code 2"):
        ws.install_release(lay, "hiroleague==0.2.0")
    assert list((tmp_path / "releases").iterdir()) == []


def test_release_install_without_uv_says_so(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ws.shutil, "which", lambda name: None)
    with pytest.raises(ServiceError, match="uv is needed"):
        ws.install_release(ws.Layout(home=tmp_path, data_dir=tmp_path / "data"), "hiroleague==0.2.0")


def test_status_reads_the_service_and_its_configuration(windows, tmp_path, monkeypatch) -> None:
    service_dir = tmp_path / "service"
    service_dir.mkdir()
    secrets = tmp_path / "hiro.env"
    secrets.write_text("", encoding="utf-8")
    # The program is a Windows path on every system (WinSW refuses anything else); the files the status reads are real.
    exe = Path(r"C:\HiroLeague\releases\r1\bin\hiro.exe")
    spec = ws.build_spec(exe=exe, lay=ws.Layout(home=tmp_path, data_dir=tmp_path / "data"), workspace=None)
    (service_dir / "hiro.xml").write_text(w.render_config(spec), encoding="utf-8")
    monkeypatch.setattr(
        service_windows, "service_state",
        lambda name: w.ServiceState(
            name=name, installed=True, state="RUNNING", pid=4812, start_type="AUTO_START (DELAYED)",
            account=r"NT SERVICE\hiro", binary_path=f'"{service_dir / "hiro.exe"}"', exit_code=0,
        ),
    )
    result = service_tools.ServiceStatusTool().execute()

    assert (result.running, result.at_boot, result.main_pid) == (True, True, 4812)
    assert result.secrets_file == str(secrets)
    assert result.logs == str(tmp_path / "data" / "service-logs")
    assert result.definition_path == str(service_dir / "hiro.xml")


def test_status_when_not_installed_names_the_install_command(windows, monkeypatch) -> None:
    from hirocli.commands.app import app

    monkeypatch.setattr(service_windows, "service_state", lambda name: w.ServiceState(name=name, installed=False))
    result = CliRunner().invoke(app, ["service", "status"])
    assert result.exit_code == 1
    assert "hiro is not installed" in result.output
    assert "service install" in result.output


def test_cli_install_asks_for_an_administrator_once_and_shows_its_outcome(windows, monkeypatch) -> None:
    from hirocli.commands.app import app

    seen: dict = {}

    def fake_elevated(args, cwd=None):
        seen["args"] = args
        report = args[args.index("--report") + 1]
        Path(report).write_text(json.dumps({"ok": True, "result": {
            "service": "hiro", "manager": "winsw", "user": r"NT SERVICE\hiro", "definition_path": r"D:\x\hiro.xml",
            "secrets_file": r"D:\x\hiro.env", "secrets_file_created": True, "exec_start": "hiro.exe start --foreground",
            "started": True, "edit_secrets": "notepad", "restart_command": "Restart-Service hiro",
            "logs": r"D:\x\data\service-logs", "data_dir": r"D:\x\data",
        }}), encoding="utf-8")
        return 0

    monkeypatch.setattr(w, "run_elevated", fake_elevated)
    result = CliRunner().invoke(app, ["service", "install", "--home", r"D:\x"])

    assert result.exit_code == 0, result.output
    assert seen["args"][:5] == [EXE, "service", "install", "--home", r"D:\x"]
    assert "needs an administrator" in result.output
    assert "installed and started" in result.output
    assert r"D:\x\data" in result.output


def test_cli_install_when_the_prompt_is_declined(windows, monkeypatch) -> None:
    from hirocli.commands.app import app

    def declined(args, cwd=None):
        raise w.ElevationRefused("The administrator prompt was declined, so nothing was changed.")

    monkeypatch.setattr(w, "run_elevated", declined)
    result = CliRunner().invoke(app, ["service", "install"])
    assert result.exit_code == 1
    assert "declined" in result.output
    assert "service install" in result.output


def test_cli_elevated_failure_is_shown_here(windows, monkeypatch) -> None:
    from hirocli.commands.app import app

    def failed(args, cwd=None):
        report = args[args.index("--report") + 1]
        Path(report).write_text(json.dumps({"ok": False, "error": "The data folder E:\\ is on a exFAT disk"}), encoding="utf-8")
        return 1

    monkeypatch.setattr(w, "run_elevated", failed)
    result = CliRunner().invoke(app, ["service", "install", "--data-dir", "E:\\"])
    assert result.exit_code == 1
    assert "exFAT" in result.output


def test_an_unexpected_error_in_the_elevated_run_still_reaches_the_asking_terminal(windows, monkeypatch, tmp_path) -> None:
    from hirocli.commands.app import app

    monkeypatch.setattr(service_windows, "is_admin", lambda: True)

    def broken(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(service_windows, "install", broken)
    report = tmp_path / "report.json"
    result = CliRunner().invoke(app, ["service", "install", "--report", str(report)])

    assert result.exit_code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert "OSError" in payload["error"]
    assert "disk full" not in payload["error"]  # never an exception's own text to a person


def test_a_failed_wrapper_download_is_a_service_error(monkeypatch, tmp_path) -> None:
    from hiro_commons.fetch import FetchError

    def refuse(url, dest, sha256):
        raise FetchError("Could not download hiro.exe from https://github.com/...: name not resolved.")

    monkeypatch.setattr(w, "fetch_checked", refuse)
    with pytest.raises(ServiceError, match="Could not download hiro.exe"):
        w.fetch_wrapper(tmp_path / "hiro.exe")


def test_a_checkout_install_rebuilds_its_packages_and_pins_its_lock(tmp_path, monkeypatch) -> None:
    root = tmp_path / "hiroserver"
    (root / "hiroleague").mkdir(parents=True)
    (root / "hirocli").mkdir()
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / "uv.lock").write_text("", encoding="utf-8")
    (root / ws.ADMIN_ASSETS).mkdir(parents=True)
    (root / ws.ADMIN_ASSETS / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "hiroleague" / "pyproject.toml").write_text('[project]\nname = "hiroleague"\n', encoding="utf-8")
    (root / "hirocli" / "pyproject.toml").write_text('[project]\nname = "hirocli"\n', encoding="utf-8")
    (root / ".venv" / "lib" / "pyproject.toml").write_text('[project]\nname = "somebody-else"\n', encoding="utf-8")
    exported: list = []
    monkeypatch.setattr(
        ws.subprocess, "run",
        lambda cmd, **kw: exported.append((cmd, kw["cwd"])) or subprocess.CompletedProcess(cmd, 0),
    )
    release = tmp_path / "releases" / "r1"

    args = ws._checkout_args("uv", root / "hiroleague", release)

    assert args == [
        "--refresh-package", "hirocli", "--refresh-package", "hiroleague",
        "--constraints", str(release / "constraints.txt"),
    ]
    ((cmd, cwd),) = exported
    assert cmd[:3] == ["uv", "export", "--frozen"] and "--package" in cmd and "hiroleague" in cmd
    assert cwd == root


def _fake_uv(home_line: str):
    """A uv that installs a release whose tool environment runs on the Python ``home_line`` names."""

    def run(cmd, **kw):
        if "tool" in cmd:
            assert "--managed-python" in cmd  # never a Python from someone's profile
            bin_dir, tools = Path(kw["env"]["UV_TOOL_BIN_DIR"]), Path(kw["env"]["UV_TOOL_DIR"])
            bin_dir.mkdir(parents=True)
            (bin_dir / "hiro.exe").write_bytes(b"")
            (tools / "hiroleague").mkdir(parents=True)
            (tools / "hiroleague" / "pyvenv.cfg").write_text(f"home = {home_line}\nversion_info = 3.12.10\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    return run


def test_a_release_on_a_python_in_someones_profile_is_refused(tmp_path, monkeypatch) -> None:
    lay = ws.Layout(home=tmp_path / "HiroLeague", data_dir=tmp_path / "HiroLeague" / "data")
    monkeypatch.setattr(ws.shutil, "which", lambda name: r"C:\uv\uv.exe")
    monkeypatch.setattr(ws.subprocess, "run", _fake_uv(r"C:\Users\michel\AppData\Local\Programs\Python\Python312"))

    with pytest.raises(ServiceError, match="could not start it"):
        ws.install_release(lay, "hiroleague==0.2.0")
    assert list(lay.releases_dir.iterdir()) == []


def test_a_release_copies_its_libraries_never_links_them_to_the_persons_uv_cache(tmp_path, monkeypatch) -> None:
    # A hard link shares its permissions with the person's cache: the service's account couldn't load
    # _pydantic_core from it, and every start failed (a clean laptop, Nov 26, 2026).
    lay = ws.Layout(home=tmp_path / "HiroLeague", data_dir=tmp_path / "HiroLeague" / "data")
    monkeypatch.setattr(ws.shutil, "which", lambda name: r"C:\uv\uv.exe")
    fake = _fake_uv(str(lay.python_dir / "cpython-3.12.10-windows-x86_64-none"))
    envs: list[dict] = []

    def run(cmd, **kw):
        if "tool" in cmd:
            envs.append(kw["env"])
        return fake(cmd, **kw)

    monkeypatch.setattr(ws.subprocess, "run", run)
    ws.install_release(lay, "hiroleague==0.2.0")
    assert [env.get("UV_LINK_MODE") for env in envs] == ["copy"]


def test_the_home_gets_its_own_uv_once(tmp_path, monkeypatch) -> None:
    person_uv = tmp_path / "person" / "uv.exe"
    person_uv.parent.mkdir()
    person_uv.write_bytes(b"uv")
    monkeypatch.setattr(ws.shutil, "which", lambda name: str(person_uv))

    ws.copy_uv_into(tmp_path / "HiroLeague")
    assert (tmp_path / "HiroLeague" / "bin" / "uv.exe").read_bytes() == b"uv"
    person_uv.write_bytes(b"newer")
    ws.copy_uv_into(tmp_path / "HiroLeague")  # kept: every app's admin step calls it again
    assert (tmp_path / "HiroLeague" / "bin" / "uv.exe").read_bytes() == b"uv"


def test_the_home_without_uv_anywhere_says_to_install_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ws.shutil, "which", lambda name: None)
    with pytest.raises(ServiceError, match="install uv"):
        ws.copy_uv_into(tmp_path / "HiroLeague")


def test_a_release_on_the_homes_own_python_is_kept(tmp_path, monkeypatch) -> None:
    lay = ws.Layout(home=tmp_path / "HiroLeague", data_dir=tmp_path / "HiroLeague" / "data")
    monkeypatch.setattr(ws.shutil, "which", lambda name: r"C:\uv\uv.exe")
    monkeypatch.setattr(ws.subprocess, "run", _fake_uv(str(lay.python_dir / "cpython-3.12.10-windows-x86_64-none")))

    exe = ws.install_release(lay, "hiroleague==0.2.0")
    assert exe.name == "hiro.exe" and exe.is_file()


def test_a_checkout_without_its_admin_pages_is_refused_with_the_build_command(tmp_path) -> None:
    root = tmp_path / "hiroleague" / "hiroserver"
    (root / "hiroleague").mkdir(parents=True)
    (root / "uv.lock").write_text("", encoding="utf-8")

    with pytest.raises(ServiceError, match="admin pages aren't built") as info:
        ws._checkout_args("uv", root / "hiroleague", tmp_path / "releases" / "r1")
    assert "run package:python" in str(info.value)
    assert str(tmp_path / "hiroleague" / "admin_frontend") in str(info.value)


def test_from_a_checkout_the_install_defaults_to_that_checkout(monkeypatch, tmp_path) -> None:
    from hiro_commons import process

    (tmp_path / "hiroleague").mkdir()
    (tmp_path / "hiroleague" / "pyproject.toml").write_text('[project]\nname = "hiroleague"\n', encoding="utf-8")
    monkeypatch.setattr(process, "find_workspace_root", lambda start=None: tmp_path)
    assert ws.installed_package_spec() == str(tmp_path / "hiroleague")


def test_an_installed_hiro_defaults_to_its_own_version(monkeypatch) -> None:
    from hiro_commons import process

    monkeypatch.setattr(process, "find_workspace_root", lambda start=None: None)
    assert ws.installed_package_spec().startswith("hiroleague==")
