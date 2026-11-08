"""Signing a plan tool in from the core (ported from HomeHiro's agents/signin.py).

The tool's own sign-in runs here; the person finishes it in a browser:

- **Claude Code** (``claude auth login --claudeai``) prints a link; after approving, Claude's page shows a
  code, which the person pastes into the admin (or the CLI) and the core writes to the tool's input. On a
  computer with a browser the tool may also finish by itself.
- **Codex** (``codex login --device-auth``) prints a link and a code to type on that page, then finishes by
  itself. Until device-code sign-in is turned on in ChatGPT's Security settings it stops at once and says so
  (state ``blocked``).

The tool keeps its own login; the core passes the pasted code on and keeps nothing. What the tool prints goes
to a file in the tool's folder (read when asked), deleted when the sign-in ends. One sign-in per workspace and
tool at a time; one not finished within EXPIRES is stopped (``tidy``, also run by the AI background job).
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from hiro_commons.log import Logger

from . import cli, status
from .kinds import PlanKind

log = Logger.get("PLANS")

EXPIRES = 15 * 60  # seconds: Codex's device code lasts 15 minutes too
KEEP_ENDED = 5 * 60  # seconds an ended sign-in's outcome stays to be read

SignInState = Literal["none", "waiting", "blocked", "done", "failed", "expired"]


class SignInRefused(ValueError):
    """The sign-in can't take that now (no code given, nothing waiting for one)."""


@dataclass
class SignInOut:
    state: SignInState
    link: str | None = None  # the page to open
    code: str | None = None  # the code to type on that page (Codex)
    takes_code: bool = False  # waiting for the code the tool's page shows, pasted back (Claude)
    code_sent: bool = False
    message: str | None = None  # why it stopped, in the tool's words when it said something

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Run:
    workspace_path: Path
    kind: PlanKind
    proc: subprocess.Popen
    output: Path
    started: float  # time.monotonic()
    code_sent: bool = False
    ended: float | None = None
    outcome: SignInOut | None = None


class SignIns:
    """Running sign-ins in this process, by (workspace, tool). Thread-safe (routes run in threads)."""

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], _Run] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(workspace_path: Path, kind: PlanKind) -> tuple[str, str]:
        return (str(workspace_path), kind.id)

    def begin(self, workspace_path: Path, kind: PlanKind) -> SignInOut:
        self.drop(workspace_path, kind)
        output = cli.tool_home(workspace_path, kind).parent / f"{kind.id}-signin.txt"
        with output.open("wb") as f:  # the tool keeps its own copy of the handle
            proc = cli.start(workspace_path, kind, kind.signin_args, f)
        with self._lock:
            self._runs[self._key(workspace_path, kind)] = _Run(workspace_path, kind, proc, output, time.monotonic())
        log.info(f"🔌 Plan sign-in started — {kind.name}")
        return self.state(workspace_path, kind)

    def state(self, workspace_path: Path, kind: PlanKind) -> SignInOut:
        with self._lock:
            r = self._runs.get(self._key(workspace_path, kind))
        if r is None:
            return SignInOut(state="none")
        if r.outcome is not None:
            return r.outcome
        text = _read(r.output)
        seen = kind.signin_text(text)
        code = r.proc.poll()
        if code is None and not seen.blocked:
            if time.monotonic() - r.started > EXPIRES:
                log.warning(f"⚠️ Plan sign-in not finished in {EXPIRES // 60} min; stopped — {kind.name}")
                outcome = SignInOut(state="expired", message="Not finished within 15 minutes. Start again.")
                self._finish(r, outcome)
                return outcome
            return SignInOut(
                state="waiting", link=seen.link, code=seen.code, takes_code=kind.takes_code, code_sent=r.code_sent
            )
        if code == 0 and not seen.blocked:
            outcome = SignInOut(state="done")
            log.info(f"✅ Plan tool signed in — {kind.name}")
            status.note_signed_in(workspace_path, kind)
        elif seen.blocked:
            outcome = SignInOut(state="blocked", message=seen.blocked)
            log.warning(f"⚠️ Plan sign-in stopped — {kind.name}", error=seen.blocked)
        else:
            outcome = SignInOut(state="failed", message=_last_lines(text) or f"{kind.name} stopped (exit code {code}).")
            log.warning(f"❌ Plan sign-in failed — {kind.name}", error=outcome.message, exit_code=code)
        self._finish(r, outcome)
        return outcome

    def send_code(self, workspace_path: Path, kind: PlanKind, code: str) -> SignInOut:
        code = code.strip()
        if not code:
            raise SignInRefused("Paste the code Claude showed you.")
        with self._lock:
            r = self._runs.get(self._key(workspace_path, kind))
        if r is None or r.outcome is not None or r.proc.poll() is not None or r.proc.stdin is None:
            raise SignInRefused(f"{kind.name} isn't waiting for a code. Start the sign-in again.")
        try:
            r.proc.stdin.write(code.encode() + b"\n")
            r.proc.stdin.flush()
        except OSError as exc:  # it ended between the check and the write
            raise SignInRefused(f"{kind.name} stopped waiting for the code. Start the sign-in again.") from exc
        r.code_sent = True
        return self.state(workspace_path, kind)

    def drop(self, workspace_path: Path, kind: PlanKind) -> SignInOut:
        """Stop the tool's sign-in, if one runs, and forget it."""
        with self._lock:
            r = self._runs.pop(self._key(workspace_path, kind), None)
        if r is not None:
            self._end(r)
        return SignInOut(state="none")

    def tidy(self) -> None:
        """Note how ended sign-ins ended, stop expired ones, forget old outcomes (blocks briefly)."""
        now = time.monotonic()
        with self._lock:
            runs = list(self._runs.values())
        for r in runs:
            if r.outcome is None:
                self.state(r.workspace_path, r.kind)  # ended or expired: noted and cleaned up there
            elif r.ended is not None and now - r.ended > KEEP_ENDED:
                with self._lock:
                    key = self._key(r.workspace_path, r.kind)
                    if self._runs.get(key) is r:
                        del self._runs[key]

    def stop_all(self) -> None:
        with self._lock:
            runs, self._runs = list(self._runs.values()), {}
        for r in runs:
            self._end(r)

    def _finish(self, r: _Run, outcome: SignInOut) -> None:
        r.outcome, r.ended = outcome, time.monotonic()
        self._end(r)

    @staticmethod
    def _end(r: _Run) -> None:
        cli.kill(r.proc)
        if r.proc.stdin is not None:
            try:
                r.proc.stdin.close()
            except OSError:
                pass  # already closed with the process
        r.output.unlink(missing_ok=True)


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""  # ended and cleaned up meanwhile


def _last_lines(text: str, lines: int = 1) -> str:
    """The tool's last words, without links or its prompt ("Paste code here if prompted > ")."""
    parts = [p.strip() for line in cli.plain(text).splitlines() for p in line.split("> ")]
    kept = [p for p in parts if p and "http" not in p and not p.startswith("Paste code")]
    return " ".join(kept[-lines:])


signins = SignIns()
