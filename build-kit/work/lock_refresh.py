r"""hiro-work lock-refresh: the core's weekly lock refresh, to the latest versions, tested before anyone installs them.

    hiro-work lock-refresh TASK

Run inside a task that reserves hiroleague (``hiro-work start lock-refresh --repos hiroleague``), in its environment's
checkout, one step after another, each timed in the Work area and its output in ``C:\hiro\logs\envN\lock-refresh-*``;
the first that fails stops it:

1. **refresh:** ``scripts/tested_versions.py --upgrade`` (uv lock --upgrade, then the hiroleague package's pins written
   from the new lock), printing what moved;
2. **check:** ``scripts/check.sh --all``, every part;
3. **commit:** the two files, on the task's branch, what moved in the message (the fresh install installs the
   committed code only);
4. **admin pages:** built, for the bundle;
5. **fresh install:** ``build-kit/fresh-install/fresh.py linux``, then ``windows``: a person's whole path on a new
   machine, with the new versions.

Then the task merges as any other (``hiro-work merge``), and the next deploy ships it. A package that breaks a step is
held back: a ``[tool.uv] constraint-dependencies`` line in hiroserver/pyproject.toml, with its reason in a comment,
then the command again. Standard library only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import hiro_work as hw

REPO = "hiroleague"
FILES = ("hiroserver/uv.lock", "hiroserver/hiroleague/pyproject.toml")
SYSTEMS = ("linux", "windows")


def steps(bash: str, python: str) -> list[tuple[str, list[str]]]:
    """The refresh's steps before and after its commit, by name: what each runs in the checkout."""
    fresh = ["uv", "run", "--project", "hiroserver", "python", "build-kit/fresh-install/fresh.py"]
    return [
        ("refresh", [python, "scripts/tested_versions.py", "--upgrade"]),
        ("check", [bash, "-lc", "./scripts/check.sh --all"]),
        ("commit", []),  # commit_message's, run by cmd_lock_refresh
        ("admin pages", [bash, "-lc", "npm --prefix admin_frontend run package:python"]),
        *((f"fresh install {system}", [*fresh, system]) for system in SYSTEMS),
    ]


def moved(output: str) -> list[str]:
    """What the refresh printed it moved: its indented lines (``  cryptography: 47.0.0 → 50.0.2``)."""
    return [line.strip() for line in output.splitlines() if line.startswith("  ") and line.strip()]


def commit_message(changes: list[str]) -> str:
    subject = (f"The core's lock refreshed to the latest: {len(changes)} package(s) moved" if changes
               else "The core's lock refreshed to the latest: nothing moved")
    return subject + ("\n\n" + "\n".join(f"- {line}" for line in changes) if changes else "") + "\n"


def execute(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """One step's program, its output captured (a test fakes this, never git)."""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _run(task: hw.Task, env: int, name: str, args: list[str], cwd: Path) -> str:
    log = hw.LOGS / f"env{env}" / f"lock-refresh-{task.id}-{name.replace(' ', '-')}.log"
    with hw.step(task.id, env, f"lock-refresh {name}", REPO, log=log):
        out = execute(args, cwd)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(out.stdout + out.stderr, encoding="utf-8")
        if out.returncode != 0:
            raise hw.Stop(f"lock-refresh's {name} failed: its log is {log}. A package that breaks it is held back "
                          "(hiroserver/pyproject.toml's [tool.uv] constraint-dependencies, with the reason), then "
                          f"hiro-work lock-refresh {task.id} again.")
    return out.stdout


def cmd_lock_refresh(a) -> None:
    task = hw.get(a.task)
    if not task.env:
        raise hw.Stop(f"Task {task.id} is paused: resume it first (hiro-work resume {task.id}).")
    if REPO not in task.repos:
        raise hw.Stop(f"Task {task.id} doesn't reserve {REPO}: hiro-work reserve {task.id} {REPO}.")
    env, cwd = task.env, hw.repo_dir(task.env, REPO)
    changes: list[str] = []
    for name, args in steps(hw.bash(), sys.executable):
        if name == "commit":
            hw.git(cwd, "add", "--", *FILES)
            if hw.git(cwd, "diff", "--cached", "--name-only"):
                with hw.step(task.id, env, "lock-refresh commit", REPO):
                    hw.git(cwd, "commit", "-q", "-m", commit_message(changes))
            continue
        out = _run(task, env, name, args, cwd)
        if name == "refresh":
            changes = moved(out)
            hw.say(out.strip())
    hw.say(f"Lock refreshed and tested on {task.branch}: {len(changes)} package(s) moved. Merge it as any task: "
           f"hiro-work merge {task.id}.")


def add_parser(sub) -> None:
    p = sub.add_parser("lock-refresh", help="the core's lock to the latest versions: refresh, full check, commit, "
                                            "fresh install on Linux and Windows")
    p.add_argument("task", help="the task it runs in (it reserves hiroleague)")
    p.set_defaults(func=cmd_lock_refresh)
