r"""The check engine's parts as Work events (hiro-docs standards/workflow.md, "Tracking").

check-engine.sh calls it when a part starts and when it ends:

    python check_events.py <repo folder> start <part>
    python check_events.py <repo folder> end <part> <exit code> <seconds> [<the part's output file>]

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


def record(folder: str, args: list[str]) -> dict | None:
    """The event for one call, or None when it isn't one to write."""
    place = where(folder)
    if not place or len(args) < 2 or args[0] not in ("start", "end"):
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
    if phase == "end":
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
