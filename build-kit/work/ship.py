r"""ship: sends the scripts' new events to CodeHiro's Work area (hiro-docs standards/workflow.md, "Tracking").

The log is the outbox. hiro-work, the deploy and the check engine only add lines to C:\hiro\logs\events.jsonl;
this sender posts the lines it hasn't sent yet to CodeHiro (``POST /api/work/events``, the key in ``X-Work-Key``),
from a position it keeps beside the log. Each line goes with its id, ``<source>:<file>:<position>`` (``<file>`` is a
short hash of the log's first line, so a log made again never reuses an old id): CodeHiro keeps each id once, so a line
sent twice does no harm. When CodeHiro can't be reached the lines simply wait, and go at the next try.

    python ship.py            send what is new, then keep sending every few seconds; stop after 10 idle minutes
    python ship.py --once     send what is new, then stop

hiro-work starts it (``kick()``) whenever it writes an event, unless one is already running: the second one finds the
lock taken and stops at once. With no key file (C:\hiro\secrets\work.key) it sends nothing. Standard library only.

Settings (environment): ``HIRO_WORK_URL`` (default http://code.hiro.local/api/work/events), ``HIRO_WORK_SOURCE``
(default ``pc``), ``HIRO_WORK_KEY_FILE`` (default <root>\secrets\work.key), ``HIRO_ROOT`` (default C:\hiro).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("HIRO_ROOT", r"C:\hiro"))
EVENTS = ROOT / "logs" / "events.jsonl"
URL = os.environ.get("HIRO_WORK_URL", "http://code.hiro.local/api/work/events")
SOURCE = os.environ.get("HIRO_WORK_SOURCE", "pc")
KEY_FILE = Path(os.environ.get("HIRO_WORK_KEY_FILE", str(ROOT / "secrets" / "work.key")))
EVERY = 2.0  # seconds between looks at the log
IDLE = 600  # seconds with nothing new before it stops
BATCH = 500  # lines in one post (CodeHiro takes up to 5000)
TIMEOUT = 10  # seconds a post may take
BACKOFF_MAX = 60  # seconds between tries while CodeHiro can't be reached


class Refused(Exception):
    """CodeHiro said no to the key (403) or takes no events (503): trying again won't help."""


def say(log: Path, msg: str) -> None:
    """A line in the sender's own log (ship.log, beside the events)."""
    with contextlib.suppress(OSError), open(log, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}\n")


def file_id(events: Path) -> str:
    """A short hash of the log's first line: who this log is, so a log made again gets new ids."""
    with open(events, "rb") as f:
        first = f.readline()
    return hashlib.sha1(first).hexdigest()[:8]


def new_lines(events: Path, position: int) -> tuple[list[tuple[int, dict]], int]:
    """The whole lines from *position* on (a line still being written waits): each with its position, and where the
    next look starts. A line that isn't JSON is skipped (it can't become one later)."""
    out: list[tuple[int, dict]] = []
    with open(events, "rb") as f:
        f.seek(position)
        while True:
            raw = f.readline()
            if not raw.endswith(b"\n"):
                break
            here = position
            position += len(raw)
            with contextlib.suppress(ValueError):
                line = json.loads(raw)
                if isinstance(line, dict):
                    out.append((here, line))
    return out, position


def post(url: str, key: str, events: list[dict]) -> None:
    """One post; raises Refused on 403/503, OSError (urllib's errors among them) when it should be tried again."""
    body = json.dumps({"events": events}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "X-Work-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT):
            return
    except urllib.error.HTTPError as e:
        if e.code in (403, 503):
            raise Refused(f"CodeHiro answered {e.code}: {e.read().decode(errors='replace')[:200]}") from e
        raise


class Sender:
    """Sends one log's new lines, keeping its place in ``<log>.ship.json``."""

    def __init__(self, events: Path, url: str, key: str, source: str) -> None:
        self.events, self.url, self.key, self.source = events, url, key, source
        self.state = events.with_name(events.name + ".ship.json")
        self.log = events.with_name("ship.log")

    def _place(self, fid: str) -> int:
        with contextlib.suppress(OSError, ValueError):
            s = json.loads(self.state.read_text(encoding="utf-8"))
            if s.get("file") == fid and s.get("position", 0) <= self.events.stat().st_size:
                return int(s["position"])
        return 0  # a new log, or one made again: from the start

    def _keep(self, fid: str, position: int) -> None:
        tmp = self.state.with_suffix(".tmp")
        tmp.write_text(json.dumps({"file": fid, "position": position}), encoding="utf-8")
        os.replace(tmp, self.state)

    def once(self) -> int:
        """Send every whole line not sent yet; returns how many went. Raises OSError while CodeHiro can't be reached
        (the place is kept, so they go next time)."""
        if not self.events.exists() or self.events.stat().st_size == 0:
            return 0
        fid = file_id(self.events)
        lines, end = new_lines(self.events, self._place(fid))
        sent = 0
        for i in range(0, len(lines), BATCH):
            chunk = lines[i : i + BATCH]
            batch = [{"id": f"{self.source}:{fid}:{pos}", **line} for pos, line in chunk]
            try:
                post(self.url, self.key, batch)
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise
                # One of them is malformed: send them one by one, and leave out the ones CodeHiro refuses
                for one in batch:
                    try:
                        post(self.url, self.key, [one])
                    except urllib.error.HTTPError as e1:
                        if e1.code != 400:
                            raise
                        say(self.log, f"left out {one['id']}: {e1.read().decode(errors='replace')[:200]}")
            sent += len(chunk)
            last = lines[i + BATCH][0] if i + BATCH < len(lines) else end
            self._keep(fid, last)
        if not lines:
            self._keep(fid, end)
        return sent


@contextlib.contextmanager
def only_one(lock: Path) -> Iterator[bool]:
    """True while this is the one sender for the log (an OS lock, gone with the process); False when another runs."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock, "a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        f.close()


def append(events: Path, record: dict) -> None:
    """Add one event to the log, whole, even while other processes add theirs (the check engine's parts run side by
    side): the log's lock file is held for the write."""
    events.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record) + "\n").encode("utf-8")
    with open(events.with_name(events.name + ".lock"), "a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)  # waits up to 10 s, then raises
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        with open(events, "ab") as f:
            f.write(line)


def key() -> str:
    with contextlib.suppress(OSError):
        return KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


def kick(events: Path = EVENTS) -> None:
    """Start a sender in the background unless there is no key; a second one stops at once (only_one). Never fails
    the caller: the events stay in the log either way."""
    if not key() or os.environ.get("HIRO_WORK_SHIP") == "off":
        return
    with contextlib.suppress(OSError):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--events", str(events)],
            creationflags=flags if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ship", description=__doc__.split("\n\n")[0])
    p.add_argument("--once", action="store_true", help="send what is new, then stop")
    p.add_argument("--events", default=str(EVENTS), help="the log to send (default: C:\\hiro\\logs\\events.jsonl)")
    a = p.parse_args(argv)
    events = Path(a.events)
    secret = key()
    if not secret:
        print(f"No key in {KEY_FILE}: nothing is sent.")
        return 0
    sender = Sender(events, URL, secret, SOURCE)
    with only_one(events.with_name(events.name + ".ship.lock")) as mine:
        if not mine:
            return 0  # another sender has this log
        quiet_since, wait = time.monotonic(), EVERY
        while True:
            try:
                if sender.once():
                    quiet_since = time.monotonic()
                wait = EVERY
            except Refused as e:
                say(sender.log, f"stopped: {e}")
                print(e)
                return 1
            except OSError as e:  # CodeHiro can't be reached: the lines wait
                say(sender.log, f"not sent, trying again in {wait:.0f} s: {e}")
                wait = min(wait * 2, BACKOFF_MAX)
            if a.once or time.monotonic() - quiet_since > IDLE:
                return 0
            time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
