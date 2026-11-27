"""Microsoft's C++ runtime on Windows: a fresh Windows lacks MSVCP140.dll, and the core can't load Kuzu without it."""

from __future__ import annotations

import io
import logging
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
import truststore

from hirocli import cpp_runtime
from hirocli.tools import server_control

MICROSOFT = "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US"


class _Windows:
    """A Windows without the runtime: the download, the signature check and Microsoft's installer stand in."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, signer: str = MICROSOFT, code: int = 0):
        self.dll = tmp_path / "System32" / "msvcp140.dll"
        self.ran: list[list[str]] = []
        self.downloaded: list[tuple[str, object]] = []
        self.code = code
        monkeypatch.setattr(cpp_runtime, "library", lambda: self.dll)
        monkeypatch.setattr(cpp_runtime, "signer_of", lambda path: signer)
        monkeypatch.setattr(cpp_runtime.urllib.request, "urlopen", self.urlopen)
        monkeypatch.setattr(cpp_runtime.subprocess, "run", self.run)

    def urlopen(self, url, *, timeout, context):
        self.downloaded.append((url, context))
        return io.BytesIO(b"installer")

    def run(self, cmd, **kw):
        self.ran.append(cmd)
        if self.code in cpp_runtime.INSTALLED_CODES:
            self.dll.parent.mkdir(parents=True, exist_ok=True)
            self.dll.write_bytes(b"dll")
        return subprocess.CompletedProcess(cmd, self.code, b"", b"")


def test_a_windows_with_the_runtime_downloads_nothing(tmp_path, monkeypatch) -> None:
    pc = _Windows(tmp_path, monkeypatch)
    pc.dll.parent.mkdir(parents=True)
    pc.dll.write_bytes(b"dll")
    assert cpp_runtime.install(tmp_path / "cache") == "present"
    assert pc.downloaded == [] and pc.ran == []


@pytest.mark.parametrize("code", [0, 3010])
def test_a_fresh_windows_gets_microsofts_signed_installer_run_without_its_window(tmp_path, monkeypatch, code) -> None:
    pc = _Windows(tmp_path, monkeypatch, code=code)
    assert cpp_runtime.install(tmp_path / "cache").startswith("installed now")
    assert pc.downloaded[0][0] == "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    assert isinstance(pc.downloaded[0][1], truststore.SSLContext)  # the system checks Microsoft's certificate
    assert pc.ran == [[str(tmp_path / "cache" / "vc_redist.x64.exe"), "/install", "/quiet", "/norestart"]]
    assert not (tmp_path / "cache" / "vc_redist.x64.exe").exists()  # the installer isn't kept


def test_an_installer_microsoft_didnt_sign_is_never_run(tmp_path, monkeypatch, caplog) -> None:
    pc = _Windows(tmp_path, monkeypatch, signer="CN=Someone Else")
    caplog.set_level(logging.WARNING)
    said = cpp_runtime.install(tmp_path / "cache")
    assert pc.ran == []
    assert said.startswith("not installed") and cpp_runtime.INSTALLER_URL in said
    assert any("isn't signed by Microsoft" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_no_network_never_fails_the_install_and_says_what_to_do(tmp_path, monkeypatch) -> None:
    _Windows(tmp_path, monkeypatch)

    def offline(url, **kw):
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(cpp_runtime.urllib.request, "urlopen", offline)
    assert cpp_runtime.install(tmp_path / "cache") == f"not installed: {cpp_runtime.BY_HAND}"


def test_an_installer_that_ends_without_the_runtime_says_its_code(tmp_path, monkeypatch) -> None:
    _Windows(tmp_path, monkeypatch, code=1603)
    assert "ended with 1603" in cpp_runtime.install(tmp_path / "cache")


def test_the_core_without_the_runtime_says_what_to_install_not_a_traceback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server_control, "load_or_create_master_key", lambda *a, **kw: None)
    monkeypatch.setattr(server_control, "ensure_mandatory_devices_channel", lambda *a, **kw: None)
    monkeypatch.setattr(server_control, "read_running_pid", lambda *a, **kw: None)
    monkeypatch.setitem(sys.modules, "hirocli.runtime.server_process", None)  # its import fails, as _kuzu's did
    monkeypatch.setattr(server_control.sys, "platform", "win32")
    monkeypatch.setattr(cpp_runtime, "missing", lambda: True)
    config = type("Config", (), {"master_key_file": "master.key"})()
    with pytest.raises(ValueError, match="Visual C\\+\\+ runtime is missing"):
        server_control.start_server(tmp_path, config, workspace_name="default", foreground=True)


def test_an_installer_in_the_downloads_folder_is_used_and_checked(tmp_path, monkeypatch) -> None:
    # The fresh-install test puts it there beforehand, so a run downloads nothing from Microsoft
    pc = _Windows(tmp_path, monkeypatch)
    downloads = tmp_path / "cache" / "downloads"
    downloads.mkdir(parents=True)
    (downloads / cpp_runtime.INSTALLER).write_bytes(b"installer")
    assert cpp_runtime.install(tmp_path / "cache", downloads).startswith("installed now")
    assert pc.downloaded == []
    assert pc.ran == [[str(tmp_path / "cache" / "vc_redist.x64.exe"), "/install", "/quiet", "/norestart"]]
    assert (downloads / cpp_runtime.INSTALLER).is_file()  # the folder's copy stays; the one that ran is gone
    assert not (tmp_path / "cache" / "vc_redist.x64.exe").exists()


def test_an_installer_in_the_downloads_folder_not_signed_by_microsoft_is_not_run(tmp_path, monkeypatch) -> None:
    pc = _Windows(tmp_path, monkeypatch, signer="CN=Someone Else")
    downloads = tmp_path / "cache" / "downloads"
    downloads.mkdir(parents=True)
    (downloads / cpp_runtime.INSTALLER).write_bytes(b"not microsoft's")
    assert "isn't signed by Microsoft" in cpp_runtime.install(tmp_path / "cache", downloads)
    assert pc.ran == [] and pc.downloaded == []
