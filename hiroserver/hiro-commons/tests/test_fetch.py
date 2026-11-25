from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

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
