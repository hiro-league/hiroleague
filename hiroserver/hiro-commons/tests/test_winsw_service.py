from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from hiro_commons import winsw_service as w
from hiro_commons.systemd_service import ServiceError


def _spec(**overrides) -> w.WinswSpec:
    values = dict(
        id="hiro",
        name="HiroLeague (hiro)",
        description="HiroLeague server",
        executable=Path(r"C:\ProgramData\HiroLeague\releases\20261125T120000Z\bin\hiro.exe"),
        arguments=["start", "--foreground"],
        working_directory=Path(r"C:\ProgramData\HiroLeague\data"),
        log_dir=Path(r"C:\ProgramData\HiroLeague\data\service-logs"),
        environment={"HIRO_SERVICE_MANAGER": "winsw", "HIRO_DATA_DIR": r"C:\ProgramData\HiroLeague\data"},
    )
    values.update(overrides)
    return w.WinswSpec(**values)


def _xml(spec: w.WinswSpec) -> ET.Element:
    return ET.fromstring(w.render_config(spec))  # noqa: S314 — text this test just rendered


def test_the_pinned_release_is_2_12_0_with_its_reviewed_checksum() -> None:
    # Changing any of these is a new review of WinSW (the module's comment says why 2.12.0).
    assert w.WINSW_VERSION == "2.12.0"
    assert w.WINSW_URL == "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
    assert w.WINSW_SHA256 == "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da"


def test_config_runs_the_program_as_its_virtual_account_and_restarts_on_failure() -> None:
    root = _xml(_spec())

    assert root.findtext("id") == "hiro"
    assert root.findtext("executable").endswith(r"\bin\hiro.exe")
    assert root.findtext("arguments") == "start --foreground"
    assert root.findtext("serviceaccount/domain") == "NT SERVICE"
    assert root.findtext("serviceaccount/user") == "hiro"
    assert root.find("serviceaccount/password") is None
    assert root.findtext("startmode") == "Automatic"
    assert root.findtext("delayedAutoStart") == "true"
    failure = root.findall("onfailure")
    assert [(f.get("action"), f.get("delay")) for f in failure] == [("restart", "5 sec")]
    assert root.findtext("stoptimeout") == "60 sec"
    assert root.findtext("logpath") == r"C:\ProgramData\HiroLeague\data\service-logs"
    assert {e.get("name"): e.get("value") for e in root.findall("env")}["HIRO_SERVICE_MANAGER"] == "winsw"


def test_arguments_with_spaces_and_xml_characters_survive() -> None:
    root = _xml(_spec(arguments=["start", "--workspace", "Home & <Kids>"], description='say "hi" & go'))
    assert root.findtext("arguments") == 'start --workspace "Home & <Kids>"'
    assert root.findtext("description") == 'say "hi" & go'


def test_a_percent_sign_is_refused_since_winsw_would_expand_it() -> None:
    with pytest.raises(ServiceError, match="%"):
        w.render_config(_spec(environment={"PATH": r"%SystemRoot%\System32"}))
    with pytest.raises(ServiceError, match="%"):
        w.render_config(_spec(arguments=["start", "--workspace", "50%off"]))


def test_a_relative_program_and_a_bad_name_are_refused() -> None:
    with pytest.raises(ServiceError, match="absolute"):
        w.render_config(_spec(executable=Path("hiro.exe")))
    with pytest.raises(ServiceError, match="not a valid service name"):
        w.render_config(_spec(id="hiro home"))
    with pytest.raises(ServiceError, match="environment variable"):
        w.render_config(_spec(environment={"BAD-NAME": "x"}))


def test_wrapper_and_config_sit_side_by_side_under_the_service_name() -> None:
    folder = Path(r"C:\ProgramData\HiroLeague\service")
    assert w.wrapper_path(folder, "hiro-home") == folder / "hiro-home.exe"
    assert w.config_path(folder, "hiro-home") == folder / "hiro-home.xml"


QUERYEX_RUNNING = """
SERVICE_NAME: hiro
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
        CHECKPOINT         : 0x0
        WAIT_HINT          : 0x0
        PID                : 4812
        FLAGS              :
"""

QC = r"""[SC] QueryServiceConfig SUCCESS

SERVICE_NAME: hiro
        TYPE               : 10  WIN32_OWN_PROCESS
        START_TYPE         : 2   AUTO_START  (DELAYED)
        ERROR_CONTROL      : 1   NORMAL
        BINARY_PATH_NAME   : "C:\ProgramData\HiroLeague\service\hiro.exe"
        LOAD_ORDER_GROUP   :
        TAG                : 0
        DISPLAY_NAME       : HiroLeague (hiro)
        DEPENDENCIES       :
        SERVICE_START_NAME : NT SERVICE\hiro
"""


def test_parse_sc_output_reads_a_running_service() -> None:
    state = w.parse_sc_output("hiro", QUERYEX_RUNNING, QC)
    assert state.installed is True
    assert state.state == "RUNNING"
    assert state.pid == 4812
    assert state.start_type == "AUTO_START (DELAYED)"
    assert state.account == r"NT SERVICE\hiro"
    assert state.binary_path == r"C:\ProgramData\HiroLeague\service\hiro.exe"
    assert state.exit_code == 0


def test_parse_sc_output_reads_a_stopped_service_with_no_pid() -> None:
    queryex = QUERYEX_RUNNING.replace("4  RUNNING", "1  STOPPED").replace("4812", "0").replace(
        "WIN32_EXIT_CODE    : 0  (0x0)", "WIN32_EXIT_CODE    : 1067  (0x42b)"
    )
    state = w.parse_sc_output("hiro", queryex, "")
    assert state.state == "STOPPED"
    assert state.pid is None
    assert state.exit_code == 1067
    assert state.start_type == ""


def test_needs_admin_error_names_the_command() -> None:
    exc = w.NeedsAdminError("Installing the HiroLeague service", r"C:\x\hiro.exe service install")
    assert exc.command == r"C:\x\hiro.exe service install"
    assert "needs an administrator" in str(exc)
    assert isinstance(exc, ServiceError)
