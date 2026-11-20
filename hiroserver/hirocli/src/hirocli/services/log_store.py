"""The core's log store: the lines every other part sends, kept beside the core's own (the logging plan, phase 5).

Every part writes its own file first (the logging foundation) and sends its lines to the core; the core never asks for
them. The store keeps what arrives in the core's own log folder, one stream per part, in the foundation's format and
under its daily rule (daily.py: one file a day, 30 days in plain files, then the monthly archive the nightly backup
keeps):

- `app-<name>-<YYYY-MM-DD>.jsonl`: an app's lines (`app-home`, `app-net`), sent over its link (`logs.send`);
- other streams by their writer's name (the device app's `device`).

The core's own processes need none of this: the server and the CLI write their files in the same folder, the gateway
and the plugins theirs, and the log tools (tools/logs.py) read every daily stream there. So "the store" is that
folder; this module is how other parts' lines get into it.

A line lands in the file of the day the core received it, never an earlier day's: a line sent late (after the link
was down) is in a later file than its own time says, and the readers go by each line's own time.

Two calls:
- `write(stream, lines)`: append lines as they are (phase 8's device problems come in this way).
- `receive(stream, items)`: an app's batch, each line with its place in the app's own file (`"<day>:<offset>"`). The
  store keeps, per stream, the last place it wrote (`received.json` in the log folder), and drops what is at or
  before it: a batch sent again after the link dropped mid-answer is kept once. The answer is that last place, which
  the app's sender starts from next time (hiro_channel_sdk.log_sender).
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import IO, Any

from hiro_commons.log import Logger
from hiro_commons.logging_foundation import daily, line

log = Logger.get("LOG_STORE")

STREAM = re.compile(r"^[a-z0-9][a-z0-9-]*$")
APP_PREFIX = "app-"
# The core's own streams: nobody else writes into them.
_OWN = frozenset({"server", "cli", "gateway"})
_OWN_PREFIXES = ("channel-",)
RECEIVED_FILE = "received.json"


def app_stream(name: str) -> str:
    """The stream an app's lines are kept in: `app-<its extension name>`."""
    return f"{APP_PREFIX}{name}".lower()


def check_stream(stream: str) -> str:
    if not STREAM.match(stream or ""):
        raise ValueError(f"A log stream's name is lowercase letters, digits and dashes, not {stream!r}.")
    if stream in _OWN or stream.startswith(_OWN_PREFIXES):
        raise ValueError(f"{stream!r} is one of the core's own log streams.")
    return stream


def place(text: str) -> tuple[date, int] | None:
    """A line's place in its part's own file, `"<YYYY-MM-DD>:<offset>"`, as something that sorts; None if unreadable."""
    day, sep, offset = str(text).partition(":")
    if not sep:
        return None
    try:
        return date.fromisoformat(day), int(offset)
    except ValueError:
        return None


def _normalized(raw: Mapping[str, Any] | str, stream: str) -> str | None:
    """A sent line as the store writes it (one JSON line), or None when it isn't a line."""
    try:
        obj = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    attributes = obj.get("Attributes")
    if isinstance(attributes, dict):
        obj["Attributes"] = line.hide_secrets(attributes)
    elif attributes is not None:
        obj.pop("Attributes")
    resource = obj.get("Resource")
    if not isinstance(resource, dict) or not resource.get("service.name"):
        obj["Resource"] = {**(resource if isinstance(resource, dict) else {}), "service.name": stream}
    text = line.render(obj)
    return text if line.parse(text) is not None else None


class _File:
    """One stream's file of today, opened on its first line of a day (and the old days archived then)."""

    def __init__(self, folder: Path, stream: str) -> None:
        self.folder, self.stream = folder, stream
        self.day: date | None = None
        self.fh: IO[str] | None = None

    def append(self, texts: list[str]) -> None:
        today = datetime.now().astimezone().date()  # the house's day, as the foundation names its files
        if self.fh is None or self.day != today:
            self.close()
            self.folder.mkdir(parents=True, exist_ok=True)
            self.fh = (self.folder / daily.file_name(self.stream, today)).open("a", encoding="utf-8", newline="\n")
            self.day = today
            daily.prune(self.folder, self.stream, today)
        self.fh.write("".join(t + "\n" for t in texts))
        self.fh.flush()  # the log tools read the file as it grows

    def close(self) -> None:
        if self.fh is not None:
            self.fh.close()
            self.fh = None


class LogStore:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._lock = threading.Lock()
        self._files: dict[str, _File] = {}
        self._received: dict[str, str] = self._read_received()

    # --- writing -------------------------------------------------------------------------------------------------

    def write(self, stream: str, lines: Sequence[Mapping[str, Any] | str]) -> int:
        """Append these lines to the stream's file of today; the number kept (a line that isn't one is dropped)."""
        check_stream(stream)
        texts = [t for raw in lines if (t := _normalized(raw, stream)) is not None]
        if len(texts) < len(lines):
            log.warning("⚠️ Log store: lines sent that weren't log lines were dropped", stream=stream,
                        dropped=len(lines) - len(texts))
        if texts:
            with self._lock:
                self._file(stream).append(texts)
        return len(texts)

    def receive(self, stream: str, items: Sequence[Sequence[Any]], *, restart: bool = False) -> str | None:
        """An app's batch, `[[place, line], ...]` in the order of its file: writes the lines after the last place kept
        for the stream, and answers the last place kept now (None while nothing was ever kept). `restart`: the app's
        file was replaced, so its places start again: the last place kept is forgotten first."""
        check_stream(stream)
        with self._lock:
            if restart:
                self._received.pop(stream, None)
            last_text = self._received.get(stream)
            last = place(last_text) if last_text else None
            fresh: list[Mapping[str, Any] | str] = []
            newest: tuple[tuple[date, int], str] | None = None
            for item in items:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    continue
                at = place(item[0])
                if at is None or (last is not None and at <= last):
                    continue  # unreadable, or already kept (a batch sent again)
                fresh.append(item[1])
                if newest is None or at > newest[0]:
                    newest = (at, str(item[0]))
            texts = [t for raw in fresh if (t := _normalized(raw, stream)) is not None]
            if texts:
                self._file(stream).append(texts)
            if newest is not None:
                self._received[stream] = newest[1]
                self._save_received()
            return self._received.get(stream)

    def last_received(self, stream: str) -> str | None:
        with self._lock:
            return self._received.get(stream)

    def close(self) -> None:
        with self._lock:
            for f in self._files.values():
                f.close()
            self._files.clear()

    # --- inside ----------------------------------------------------------------------------------------------------

    def _file(self, stream: str) -> _File:
        f = self._files.get(stream)
        if f is None:
            f = self._files[stream] = _File(self.folder, stream)
        return f

    def _read_received(self) -> dict[str, str]:
        path = self.folder / RECEIVED_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            # Lost: every app's next batch is kept whole, so at worst a few lines are kept twice.
            log.warning("⚠️ Log store: what each app sent last couldn't be read; starting afresh", file=str(path),
                        error=str(exc))
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_received(self) -> None:
        path = self.folder / RECEIVED_FILE
        tmp = path.with_suffix(".tmp")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._received, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("⚠️ Log store: couldn't save what each app sent last", file=str(path), error=str(exc))


# --- the server's one store ----------------------------------------------------------------------------------------

_store: LogStore | None = None


def start(folder: Path) -> LogStore:
    """Open the server's store in its log folder (the server process, at start)."""
    global _store
    stop()
    _store = LogStore(folder)
    return _store


def stop() -> None:
    global _store
    if _store is not None:
        _store.close()
        _store = None


def store() -> LogStore:
    if _store is None:
        raise RuntimeError("The log store isn't open: only the server process keeps one.")
    return _store


def write(stream: str, lines: Sequence[Mapping[str, Any] | str]) -> int:
    """Append lines to a stream of the server's store (see LogStore.write)."""
    return store().write(stream, lines)


def receive(stream: str, items: Sequence[Sequence[Any]], *, restart: bool = False) -> str | None:
    """An app's batch into the server's store (see LogStore.receive)."""
    return store().receive(stream, items, restart=restart)
