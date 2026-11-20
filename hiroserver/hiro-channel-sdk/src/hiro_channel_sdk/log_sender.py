"""An app sends its log lines to the core (the logging plan, phase 5).

Every part writes its own file first (the logging foundation) and sends its lines to the core, which keeps them in
its log store; the core never asks for them. The sender reads the app's own daily files, so what it sends is exactly
what the file holds, and it can't lose a line the file has:

- every 2 s while the link is up, it reads what its files gained since the last place the core kept, and sends the
  lines at INFO and up (debug lines stay in the app's own file) in batches of up to 500 (`logs.send`);
- each line goes with its place in the file, `"<YYYY-MM-DD>:<byte offset where it ends>"`; the core keeps what is
  after the last place it kept for this app and answers that place, which the sender keeps in `sent.json` beside its
  files;
- **the core away, the link down, the app restarted:** nothing is lost and nothing is asked. The lines wait in the
  file; when the link is back the sender starts from the place in `sent.json` and sends everything after it, from
  every daily file still kept (30 days), oldest first, before the newest;
- **the link drops mid-batch:** the batch goes again; the core keeps a line it already had once.
- **No place kept yet** (a new app, a lost `sent.json`): it starts at the beginning of today's file.
- **The file is shorter than the place kept** (replaced): it reads it from its start, and its next batch says
  `restart`, so the core forgets its place for this app.

It logs only what changes (sending fails, then works again), so its own lines don't feed it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from hiro_commons.logging_foundation import daily

from .constants import METHOD_LOGS_SEND
from .extension import ExtensionClient, ExtensionRequestError

log = logging.getLogger("hiro.logs.sender")

EVERY = 2.0  # seconds between looks at the file
BATCH_LINES = 500
BATCH_BYTES = 1_000_000  # a batch stops before this much text (one longer line still goes alone)
MIN_SEVERITY = 9  # OpenTelemetry's INFO: debug and fine-info lines stay in the app's file
SENT_FILE = "sent.json"
TIMEOUT = 30.0


def place_of(day: date, offset: int) -> str:
    return f"{day.isoformat()}:{offset}"


def parse_place(text: Any) -> tuple[date, int] | None:
    day, sep, offset = str(text or "").partition(":")
    if not sep:
        return None
    try:
        return date.fromisoformat(day), int(offset)
    except ValueError:
        return None


def _severity(raw: bytes) -> int:
    try:
        return int(json.loads(raw).get("SeverityNumber") or 0)
    except (ValueError, TypeError, AttributeError):
        return 0  # not a line: skipped (a half-written one is never read: only whole lines are)


class LogSender:
    """Sends the lines of one part's daily files (`folder`, `name`: the foundation's `where()`) over its link."""

    def __init__(self, client: ExtensionClient, folder: Path, name: str, *, every: float = EVERY) -> None:
        self.client = client
        self.folder = Path(folder)
        self.name = name
        self.every = every
        self.sent: tuple[date, int] | None = self._read_sent()
        self.failing: str | None = None  # why sending fails now (said once)
        self.restarted = False  # the file was replaced under the place kept: the next batch says so

    # --- the loop ----------------------------------------------------------------------------------------------------

    async def run(self) -> None:
        """Send what is new, again and again, until cancelled (the app's link worker runs it as one of its tasks)."""
        while True:
            if self.client.connected:
                try:
                    while await self.send_new():  # catching up: batch after batch, until nothing is left
                        pass
                except ExtensionRequestError as exc:
                    self._failed(f"{exc.code}: {exc}")
                except OSError as exc:
                    self._failed(f"reading the log files: {exc}")
            await asyncio.sleep(self.every)

    async def send_new(self) -> int:
        """Send the next batch; the number of lines sent (0: nothing new)."""
        lines, scanned = await asyncio.to_thread(self.next_batch)
        if scanned is None:
            return 0
        if lines:
            params: dict[str, Any] = {"lines": lines}
            if self.restarted:
                params["restart"] = True
            answer = await self.client.request(METHOD_LOGS_SEND, params, timeout=TIMEOUT)
            self.restarted = False
            kept = parse_place(answer.get("last"))
            # The core's answer is where it is; never move back past what this batch read (its last lines were debug)
            scanned = max(scanned, kept) if kept is not None else scanned
        self._save_sent(scanned)
        if self.failing is not None:
            log.info("Sending this app's log lines to the core again", extra={"after": self.failing})
            self.failing = None
        return len(lines)

    # --- reading the files -----------------------------------------------------------------------------------------

    def next_batch(self) -> tuple[list[list[Any]], tuple[date, int] | None]:
        """The next lines to send (`[[place, line], ...]`), and the place read up to (None: nothing new)."""
        start = self.sent or (self._today(), 0)
        batch: list[list[Any]] = []
        size = 0
        scanned: tuple[date, int] | None = None
        for day, path in sorted(daily.files(self.folder, self.name)):  # oldest first
            if day < start[0]:
                continue
            offset = start[1] if day == start[0] else 0
            try:
                end = path.stat().st_size
            except OSError:
                continue
            if end < offset:
                # The file is shorter than the place kept: it was replaced (data copied over, deleted by hand). Read it
                # from its start, and tell the core to forget its place, or it would drop these lines as kept already.
                offset, self.restarted = 0, True
            if end <= offset:
                continue
            with path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read(end - offset)
            pos = offset
            for raw in chunk.split(b"\n")[:-1]:  # whole lines only: one being written waits for the next look
                if batch and (len(batch) >= BATCH_LINES or size + len(raw) > BATCH_BYTES):
                    return batch, scanned
                pos += len(raw) + 1
                scanned = (day, pos)
                if _severity(raw) >= MIN_SEVERITY:
                    text = raw.decode("utf-8", errors="replace")
                    batch.append([place_of(day, pos), text])
                    size += len(text)
        return batch, scanned

    # --- the place kept ----------------------------------------------------------------------------------------------

    @staticmethod
    def _today() -> date:
        return datetime.now().astimezone().date()  # the house's day, as the files are named

    def _read_sent(self) -> tuple[date, int] | None:
        try:
            data = json.loads((self.folder / SENT_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("This app's %s couldn't be read (%s): sending from the start of today's file", SENT_FILE, exc)
            return None
        return parse_place(data.get("place")) if isinstance(data, dict) else None

    def _save_sent(self, at: tuple[date, int]) -> None:
        if at == self.sent:
            return
        self.sent = at
        path = self.folder / SENT_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"place": place_of(*at)}), encoding="utf-8")
        os.replace(tmp, path)

    def _failed(self, why: str) -> None:
        if why.startswith("not_connected"):
            return  # the link is down or going: the link's own lines say so, and the lines wait in the file
        if why != self.failing:
            log.warning("This app's log lines couldn't be sent to the core; they wait in its file",
                        extra={"error": why})
            self.failing = why
