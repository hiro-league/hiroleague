r"""The check engine's parts as Work events (hiro-docs standards/workflow.md, "Tracking").

check-engine.sh calls it when a part starts and when it ends:

    python check_events.py <repo folder> start <part>
    python check_events.py <repo folder> progress <part> <the part's output file>
    python check_events.py <repo folder> end <part> <exit code> <seconds> [<the part's output file>]

While a part runs, the engine calls ``progress`` every few seconds: the tests the part's output shows done so far
(``count_tests``) become an event of their own (``phase: progress``, ``tests``) when the count changed since the last
call (kept beside the output, ``<output>.tests``). The end carries the part's last count too. Only counts: no test's name
or result goes in an event.

Each part is a step of its own, inside the repo's check (``parent: check``); a part that fails carries the last lines of
its output (the engine's output files are gone once the check ends). The task and the environment come from the repo's
folder: ``C:\hiro\env<N>\<repo>``, and the working task there that claims the repo (C:\hiro\tasks). Outside
C:\hiro (Simone's nightly check, a container) it writes nothing. It never fails the check: any trouble is ignored.
Standard library only.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import ship

ROOT = ship.ROOT
TASKS = ROOT / "tasks"
TAIL_LINES = 100
TAIL_CHARS = 20_000


def where(folder: str) -> tuple[int, str] | None:
    r"""(env, repo) for a repo folder under C:\hiro\env<N>; Git Bash's /c/... paths too. None outside it."""
    m = re.match(r"^/([a-zA-Z])/(.*)$", folder)
    path = Path(f"{m.group(1)}:/{m.group(2)}") if m else Path(folder)
    with contextlib.suppress(ValueError):
        parts = path.resolve().relative_to(ROOT.resolve()).parts
        if len(parts) >= 2 and re.fullmatch(r"env\d", parts[0]):
            return int(parts[0][3:]), parts[1]
    return None


def task_of(env: int, repo: str) -> str | None:
    """The working task in *env* that claims *repo*, if any (a check run with no task, as Michel's in env0, has none)."""
    for p in sorted(TASKS.glob("*.json")):
        with contextlib.suppress(OSError, ValueError):
            t = json.loads(p.read_text(encoding="utf-8"))
            if t.get("state") == "working" and t.get("env") == env and repo in t.get("repos", []):
                return str(t["id"])
    return None


def tail(output: str | None) -> str | None:
    if not output:
        return None
    with contextlib.suppress(OSError):
        lines = Path(output).read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL_LINES:]
        return "\n".join(lines)[-TAIL_CHARS:]
    return None


# What test runners print per test, as the checks run them: pytest's progress characters (-q, with xdist too:
# "....F.s  [ 42%]"), unittest's dots (one line, written as they go), pytest -v's "PASSED"/"FAILED" lines, and vitest's
# file lines ("✓ src/x.test.ts (12 tests) 4ms").
_DOTS = re.compile(r"^\s*([.FEsxX]+)\s*(\[\s*\d+%\])?\s*$")
_VERBOSE = re.compile(r"::\S+.*\b(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
_VITEST = re.compile(r"^\s*[✓✔❯×✗✘]\s+\S.*\((\d+) tests?\b")


def count_tests(text: str) -> int:
    """How many tests a part's output shows done so far (0 when it shows none: a linter, a build)."""
    n = 0
    for line in text.splitlines():
        if m := _DOTS.match(line):
            n += len(m.group(1))
        elif _VERBOSE.search(line):
            n += 1
        elif m := _VITEST.match(line):
            n += int(m.group(1))
    return n


def tests_in(output: str | None) -> int:
    if not output:
        return 0
    with contextlib.suppress(OSError):
        return count_tests(Path(output).read_text(encoding="utf-8", errors="replace"))
    return 0


def changed_count(output: str) -> int | None:
    """The output's count now, when it differs from the one sent last (None: no change, or no tests yet)."""
    n = tests_in(output)
    seen = Path(output + ".tests")
    last = -1
    with contextlib.suppress(OSError, ValueError):
        last = int(seen.read_text(encoding="utf-8"))
    if n == 0 or n == last:
        return None
    with contextlib.suppress(OSError):
        seen.write_text(str(n), encoding="utf-8")
    return n


def record(folder: str, args: list[str]) -> dict | None:
    """The event for one call, or None when it isn't one to write."""
    place = where(folder)
    if not place or len(args) < 2 or args[0] not in ("start", "progress", "end"):
        return None
    tests = None
    if args[0] == "progress":
        tests = changed_count(args[2]) if len(args) > 2 else None
        if tests is None:
            return None
    env, repo = place
    phase, part = args[0], args[1]
    e = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": task_of(env, repo),
        "env": env,
        "repo": repo,
        "step": part,
        "parent": "check",
        "phase": phase,
    }
    if phase == "progress":
        e["tests"] = tests
    if phase == "end":
        if n := tests_in(args[4] if len(args) > 4 else None):
            e["tests"] = n
        code = int(args[2]) if len(args) > 2 and args[2].lstrip("-").isdigit() else 1
        e["ok"] = code == 0
        e["seconds"] = float(args[3]) if len(args) > 3 and args[3].replace(".", "", 1).isdigit() else 0.0
        if code:
            e["error"] = f"exit {code}"
            e["tail"] = tail(args[4] if len(args) > 4 else None)
    return e


def main(argv: list[str]) -> int:
    with contextlib.suppress(Exception):
        if len(argv) >= 2:
            e = record(argv[0], argv[1:])
            if e:
                ship.append(ship.EVENTS, e)
                if e["phase"] == "start":
                    ship.kick()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
