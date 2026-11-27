"""A cache of the Pythons uv downloads, for the fresh-install test's machines (uv's ``python-install-mirror``).

    python3 python_mirror.py <folder> <port>

uv asks for ``<mirror>/<release>/<file>``; the file is served from ``<folder>`` when it is there, else downloaded once
from python-build-standalone's releases on GitHub, kept, and served. A file's name holds its Python's version, build
and system, and uv checks its hash: nothing is ever served in place of another. Standard library only (it runs on
Simone, started by cache-start.sh).
"""

from __future__ import annotations

import shutil
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM = "https://github.com/astral-sh/python-build-standalone/releases/download"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


class Mirror(BaseHTTPRequestHandler):
    folder: Path

    def do_GET(self) -> None:  # noqa: N802 — http.server's name
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if len(parts) != 2 or any(p in (".", "..") or "\\" in p for p in parts):
            self.send_error(404)
            return
        target = self.folder.joinpath(*parts)
        with _lock_for(str(target)):  # one download per file, however many machines ask at once
            if not target.is_file():
                try:
                    self._fetch(f"{UPSTREAM}/{parts[0]}/{parts[1]}", target)
                except OSError as exc:
                    self.log_message("upstream failed for %s: %s", self.path, exc)
                    self.send_error(502, "upstream failed")
                    return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        with target.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    @staticmethod
    def _fetch(url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:  # noqa: S310 — fixed upstream
                shutil.copyfileobj(response, out)
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    Mirror.folder = Path(argv[0])
    ThreadingHTTPServer(("0.0.0.0", int(argv[1])), Mirror).serve_forever()  # noqa: S104 — the test machines are elsewhere
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
