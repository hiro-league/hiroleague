from __future__ import annotations

import hashlib
import io
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import truststore

from hiro_commons import fetch
from hiro_commons import log as core_log
from hiro_commons import logging_foundation as foundation
from hiro_commons.log import Logger
from hiro_commons.logging_foundation import daily
from hiro_commons.fetch import FetchError, fetch_checked

BODY = b"pinned program bytes" * 1000
GOOD = hashlib.sha256(BODY).hexdigest()


@pytest.fixture
def logged(tmp_path, monkeypatch):
    """The core's logger writing to a folder of this test's own; returns a reader of its lines."""
    monkeypatch.delenv(foundation.LEVELS_SETTING, raising=False)
    saved = (Logger._level, dict(core_log._MODULE_OVERRIDES))
    folder = tmp_path / "logs"
    Logger.start(folder, name="server", service="core", console=False)

    def lines() -> list[dict]:
        foundation.flush()
        found = []
        for _day, path in daily.files(folder, "server"):
            found += [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
        return found

    yield lines
    Logger.close()
    Logger._level = saved[0]
    core_log._MODULE_OVERRIDES.clear()
    core_log._MODULE_OVERRIDES.update(saved[1])


class _Handler(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self) -> None:  # noqa: N802 — http.server's name
        type(self).hits += 1
        if self.path != "/winsw.exe":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    _Handler.hits = 0
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_downloads_and_keeps_the_pinned_file(server, tmp_path: Path) -> None:
    dest = tmp_path / "service" / "hiro.exe"
    assert fetch_checked(f"{server}/winsw.exe", dest, GOOD.upper()) is True
    assert dest.read_bytes() == BODY
    assert list(dest.parent.iterdir()) == [dest]  # no temporary file left


def test_a_file_already_in_place_is_not_fetched_again(server, tmp_path: Path) -> None:
    dest = tmp_path / "hiro.exe"
    dest.write_bytes(BODY)
    assert fetch_checked(f"{server}/winsw.exe", dest, GOOD) is False
    assert _Handler.hits == 0


def test_a_different_file_is_thrown_away_and_logged(server, tmp_path: Path, logged) -> None:
    dest = tmp_path / "bin" / "hiro.exe"
    dest.parent.mkdir()
    dest.write_bytes(b"the old, good wrapper")

    with pytest.raises(FetchError, match="SHA-256 differs"):
        fetch_checked(f"{server}/winsw.exe", dest, "0" * 64)

    assert dest.read_bytes() == b"the old, good wrapper"  # the old file is untouched
    assert sorted(p.name for p in dest.parent.iterdir()) == ["hiro.exe"]
    (error,) = [line for line in logged() if line["SeverityText"] == "ERROR"]
    assert "not the one pinned" in error["Body"]
    assert error["Attributes"]["expected"] == "0" * 64


def test_a_failed_download_says_which_file_and_leaves_nothing(server, tmp_path: Path, logged) -> None:
    folder = tmp_path / "bin"
    with pytest.raises(FetchError, match="Could not download hiro.exe"):
        fetch_checked(f"{server}/missing.exe", folder / "hiro.exe", GOOD)
    assert list(folder.iterdir()) == []
    (warning,) = [line for line in logged() if line["SeverityText"] == "WARNING"]
    assert "Could not download" in warning["Body"]


def test_the_certificate_is_checked_by_the_system_not_by_pythons_own_list(tmp_path, monkeypatch) -> None:
    # A fresh Windows fetches a missing root only for the system's own checks: Python's refused GitHub's in Sandbox
    seen = {}

    def fake_urlopen(url, *, timeout, context=None):
        seen["context"] = context
        return io.BytesIO(BODY)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert fetch.fetch_checked("https://github.com/example/pinned.zip", tmp_path / "pinned.zip", GOOD) is True
    assert isinstance(seen["context"], truststore.SSLContext)


# The machine's downloads folder: one copy of each pinned file, used by the next place that wants it


def test_a_download_leaves_a_copy_the_next_service_takes_without_downloading(server, tmp_path: Path, logged) -> None:
    # Each Windows service has its own WinSW: the fresh-install test downloaded it from GitHub once per service
    shared = fetch.shared_downloads(tmp_path / "home")
    url = f"{server}/winsw.exe"
    assert fetch_checked(url, tmp_path / "core" / "hiro.exe", GOOD, shared=shared) is True
    assert (shared / fetch.shared_name(url, GOOD)).read_bytes() == BODY

    app = tmp_path / "app" / "hiro-example-hello.exe"
    assert fetch_checked(url, app, GOOD, shared=shared) is False
    assert app.read_bytes() == BODY
    assert _Handler.hits == 1
    assert list(app.parent.iterdir()) == [app]  # no temporary file left
    assert any("taken from the downloads folder" in line["Body"] for line in logged())


def test_a_copy_put_there_beforehand_is_used(server, tmp_path: Path) -> None:
    # The fresh-install test fills the folder before the core installs, so a run downloads nothing
    shared = tmp_path / "downloads"
    shared.mkdir()
    url = f"{server}/winsw.exe"
    (shared / fetch.shared_name(url, GOOD)).write_bytes(BODY)
    assert fetch_checked(url, tmp_path / "hiro.exe", GOOD.upper(), shared=shared) is False
    assert _Handler.hits == 0


def test_a_changed_copy_is_refused_and_the_file_downloaded(server, tmp_path: Path, logged) -> None:
    shared = tmp_path / "downloads"
    shared.mkdir()
    url = f"{server}/winsw.exe"
    kept = shared / fetch.shared_name(url, GOOD)
    kept.write_bytes(b"someone changed this file")
    dest = tmp_path / "hiro.exe"

    assert fetch_checked(url, dest, GOOD, shared=shared) is True
    assert dest.read_bytes() == BODY
    assert kept.read_bytes() == BODY  # the download's checked copy replaces it
    assert sorted(p.name for p in tmp_path.iterdir()) == ["downloads", "hiro.exe", "logs"]
    (warning,) = [line for line in logged() if line["SeverityText"] == "WARNING"]
    assert "not the file pinned" in warning["Body"]


def test_a_folder_it_cannot_write_costs_only_a_later_download(server, tmp_path: Path, logged) -> None:
    shared = tmp_path / "downloads"
    shared.write_text("a file where the folder should be", encoding="utf-8")
    dest = tmp_path / "hiro.exe"
    assert fetch_checked(f"{server}/winsw.exe", dest, GOOD, shared=shared) is True
    assert dest.read_bytes() == BODY
    (warning,) = [line for line in logged() if line["SeverityText"] == "WARNING"]
    assert "Could not keep a copy" in warning["Body"]
