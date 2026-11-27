"""The fresh-install tools' own rules: the Sandbox's configuration, WSL's paths (fresh.py), what a log may hold (read_logs.py)."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import fresh
import python_mirror
import pytest
import read_logs


def test_the_sandbox_maps_the_bundle_read_only_and_the_results_writable_and_runs_the_script() -> None:
    root = ET.fromstring(fresh.wsb(PureWindowsPath(r"C:\runs\a\bundle"), PureWindowsPath(r"C:\runs\a\results")))
    folders = {f.findtext("SandboxFolder"): (f.findtext("HostFolder"), f.findtext("ReadOnly"))
               for f in root.iter("MappedFolder")}
    assert folders == {fresh.SANDBOX_BUNDLE: (r"C:\runs\a\bundle", "true"),
                       fresh.SANDBOX_RESULTS: (r"C:\runs\a\results", "false")}
    command = root.findtext("LogonCommand/Command")
    assert f"{fresh.SANDBOX_BUNDLE}\\run-windows.ps1" in command and f"-Results {fresh.SANDBOX_RESULTS}" in command
    assert root.findtext("Networking") == "Enable"  # uv, Python, the packages, WinSW and Caddy come from the internet


def test_a_windows_path_is_where_wsl_mounts_it() -> None:
    assert fresh.to_linux(PureWindowsPath(r"C:\hiro\test-packages\fresh\runs\x")) == "/mnt/c/hiro/test-packages/fresh/runs/x"
    assert fresh.to_linux(PureWindowsPath(r"D:\a")) == "/mnt/d/a"



def _problems(*messages: str) -> str:
    return json.dumps({"groups": [{"level": "WARNING", "area": "X", "messages": list(messages)}]})


def test_the_problems_the_run_causes_on_purpose_pass_and_any_other_fails() -> None:
    on_purpose = _problems("⚠️ Upgrade refused — Hello stays on 0.1.0: Its trial step failed: RuntimeError: 0.1.2: this "
                           "migration fails on purpose.", "❌ No chat LLM configured — replies will be canned fallbacks")
    assert read_logs.problems(on_purpose) == []
    other = _problems("⚠️ Site names — avahi-publish isn't installed here, so names aren't announced on the LAN.")
    assert read_logs.problems(other) == [("WARNING X: ⚠️ Site names — avahi-publish isn't installed here, so names "
                                          "aren't announced on the LAN.")]


def test_a_traceback_passes_only_when_the_run_caused_it() -> None:
    expected = "hiro[9]: Traceback (most recent call last):\nhiro[9]:   File x\nhiro[9]: RuntimeError: 0.1.2: this migration fails on purpose"
    assert read_logs.service(expected) == []
    crash = "Traceback (most recent call last):\n  File x\nImportError: DLL load failed while importing _pydantic_core"
    assert len(read_logs.service(crash)) == 2  # the traceback and the failed load, each named


def _mirror(tmp_path: Path, monkeypatch) -> tuple[str, list[str]]:
    fetched: list[str] = []

    def fake_fetch(url: str, target: Path) -> None:  # stands in for GitHub
        fetched.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"python build")

    monkeypatch.setattr(python_mirror.Mirror, "_fetch", staticmethod(fake_fetch))
    python_mirror.Mirror.folder = tmp_path
    server = python_mirror.ThreadingHTTPServer(("127.0.0.1", 0), python_mirror.Mirror)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", fetched


def test_the_python_mirror_downloads_a_build_once_then_serves_it_from_disk(tmp_path, monkeypatch) -> None:
    base, fetched = _mirror(tmp_path, monkeypatch)
    for _ in range(2):
        with urllib.request.urlopen(f"{base}/20260211/cpython-3.12.12.tar.gz") as r:
            assert r.read() == b"python build"
    assert fetched == [f"{python_mirror.UPSTREAM}/20260211/cpython-3.12.12.tar.gz"]


@pytest.mark.parametrize("path", ["/../secret/x", "/one-part", "/a/b/c", "/a/.."])
def test_the_python_mirror_refuses_any_other_path(tmp_path, monkeypatch, path) -> None:
    base, fetched = _mirror(tmp_path, monkeypatch)
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(base + path)
    assert refused.value.code == 404 and fetched == []
