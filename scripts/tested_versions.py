"""The core's tested versions: every third-party version hiroserver/uv.lock pins, written where an install reads them.

    python scripts/tested_versions.py            # check: both places say what uv.lock says (scripts/check.sh)
    python scripts/tested_versions.py --write    # write both from uv.lock, then uv lock (after a `uv add`)
    python scripts/tested_versions.py --upgrade  # refresh: uv lock --upgrade, then write both (hiro-work lock-refresh)

uv resolves a tool afresh at every `uv tool install`, whatever a lock says (it reads no pins from the installed
package's own [tool.uv] settings either). So the versions the check tested are written in two places:

- **The hiroleague package's dependencies** (hiroserver/hiroleague/pyproject.toml, between the two "tested versions"
  lines): every version its tree locks, exactly (``name==version``, the lock's markers kept). A person's
  ``uv tool install hiroleague``, ``hiro upgrade``, pipx and pip then install the tested set, and an upgrade moves to
  the next release's.
- **The core's constraints file** (hirocli/hiro-constraints.txt, inside the core's package): every version of the whole
  workspace, its channels' included. The core passes it to ``uv tool install --constraints`` for a channel
  (tools/channel.py), and the deploy for the WhatsApp plugin's tool.

Neither pins the workspace's own packages (hirocli, the SDK, the channels): they are released together. Its header says
when the lock was last refreshed to the latest (``--upgrade``); the session-start check reads it, and says when the
weekly refresh is due. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "hiroserver"
LOCK = SERVER / "uv.lock"
META = SERVER / "hiroleague" / "pyproject.toml"
CONSTRAINTS = SERVER / "hirocli" / "src" / "hirocli" / "hiro-constraints.txt"
PACKAGE = "hiroleague"

START = "    # --- tested versions: written by scripts/tested_versions.py from uv.lock, never by hand ---"
END = "    # --- tested versions: end ---"
REFRESHED = re.compile(r"^# Refreshed to the latest: (\d{4}-\d{2}-\d{2}|never)", re.MULTILINE)
NEVER = "never"  # a lock nobody has refreshed with --upgrade yet
_EXPORT = ("export", "--frozen", "--no-emit-workspace", "--no-dev", "--no-hashes", "--no-header",
           "--format", "requirements.txt")


class Refused(Exception):
    """What the script won't do, in words."""


def requirements(exported: str) -> list[str]:
    """The ``name==version [; marker]`` lines of a ``uv export``, comments and options left out."""
    return [line.strip() for line in exported.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))]


def versions(lock_text: str) -> dict[str, str]:
    """Each locked package's version by name; a package locked at two versions (two Pythons) keeps both, joined."""
    found: dict[str, set[str]] = {}
    for p in tomllib.loads(lock_text).get("package", []):
        if "version" in p:
            found.setdefault(p["name"], set()).add(p["version"])
    return {name: ", ".join(sorted(v)) for name, v in found.items()}


def with_pins(pyproject: str, pins: list[str]) -> str:
    """The meta-package's pyproject with its tested-versions block holding ``pins`` (none: an empty block)."""
    block = [START, *(f'    "{pin}",' for pin in pins), END]
    lines = pyproject.splitlines()
    if START not in lines or END not in lines or lines.index(END) < lines.index(START):
        raise Refused(f"{META.relative_to(REPO)} has no tested-versions block: its dependencies need the lines\n"
                      f"{START}\n{END}")
    start, end = lines.index(START), lines.index(END)
    return "\n".join([*lines[:start], *block, *lines[end + 1:]]) + "\n"


def refreshed(constraints: str) -> str | None:
    """The day the lock was last refreshed to the latest, as the constraints file says it (ISO); None when it never
    was, or the file doesn't say."""
    match = REFRESHED.search(constraints)
    return match[1] if match and match[1] != NEVER else None


def constraints_text(pins: list[str], refreshed_on: str | None) -> str:
    return (
        "# The versions hiroserver/uv.lock tested, for every package of the core's workspace (its channels' too):\n"
        "# written by scripts/tested_versions.py, never by hand. The core passes this file to `uv tool install\n"
        "# --constraints` when it installs a channel.\n"
        f"# Refreshed to the latest: {refreshed_on or NEVER} (uv lock --upgrade)\n"
        + "".join(f"{pin}\n" for pin in pins)
    )


def changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """What a refresh changed, one line a package: ``name: old → new``, added or gone. Sorted by name."""
    out = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        out.append(f"{name}: {old} → {new}" if old and new else f"{name}: {new} (new)" if new else f"{name}: gone")
    return out


def _uv(*args: str) -> str:
    out = subprocess.run(["uv", *args], cwd=SERVER, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise Refused(f"uv {' '.join(args[:3])} failed:\n{(out.stderr or out.stdout).strip()[-3000:]}")
    return out.stdout


def expected(refreshed_on: str | None) -> tuple[str, str]:
    """What the meta-package's pyproject and the constraints file should hold for today's uv.lock."""
    pins = requirements(_uv(*_EXPORT, "--package", PACKAGE))
    every = requirements(_uv(*_EXPORT, "--all-packages"))
    return with_pins(META.read_text(encoding="utf-8"), pins), constraints_text(every, refreshed_on)


def _today() -> str:
    """This PC's day (ISO): the day a person refreshed the lock."""
    return datetime.now().astimezone().date().isoformat()


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def _current_refreshed() -> str | None:
    return refreshed(CONSTRAINTS.read_text(encoding="utf-8")) if CONSTRAINTS.is_file() else None


def _relock() -> None:
    """uv lock after the pins are written: the lock keeps each package's declared dependencies, so the meta-package's
    new pins change its record there, never a version (they are the lock's own)."""
    before = versions(LOCK.read_text(encoding="utf-8"))
    _uv("lock")
    if moved := changes(before, versions(LOCK.read_text(encoding="utf-8"))):
        raise Refused("Writing the tested versions moved versions in uv.lock, which it never should:\n  "
                      + "\n  ".join(moved))


def check() -> int:
    _uv("lock", "--check")  # a pyproject changed without `uv lock` would be a lock nobody tested
    meta, constraints = expected(_current_refreshed())
    stale = [p.relative_to(REPO).as_posix() for p, text in ((META, meta), (CONSTRAINTS, constraints))
             if not p.is_file() or p.read_text(encoding="utf-8") != text]
    if stale:
        print(f"The tested versions in {' and '.join(stale)} aren't uv.lock's: run "
              "`python scripts/tested_versions.py --write` and commit them with the lock.")
        return 1
    print("The tested versions match uv.lock.")
    return 0


def write() -> int:
    meta, constraints = expected(_current_refreshed())
    _write(META, meta)
    _write(CONSTRAINTS, constraints)
    _relock()
    print(f"Wrote the tested versions from uv.lock: {META.relative_to(REPO)}, {CONSTRAINTS.relative_to(REPO)}.")
    return 0


def upgrade() -> int:
    """uv lock --upgrade, then both places written. The pins come out first, or they would hold the lock where it is;
    on a failure the three files are put back as they were. A version held back on purpose is a constraint in the workspace's
    pyproject ([tool.uv] constraint-dependencies), with its reason: uv lock keeps to it."""
    before_lock = LOCK.read_text(encoding="utf-8")
    before_meta = META.read_text(encoding="utf-8")
    before_constraints = CONSTRAINTS.read_text(encoding="utf-8")
    try:
        _write(META, with_pins(before_meta, []))
        _uv("lock", "--upgrade")
        meta, constraints = expected(_today())
        _write(META, meta)
        _write(CONSTRAINTS, constraints)
        _relock()
    except BaseException:
        _write(META, before_meta)
        _write(LOCK, before_lock)
        _write(CONSTRAINTS, before_constraints)
        raise
    changed = changes(versions(before_lock), versions(LOCK.read_text(encoding="utf-8")))
    print(f"uv.lock refreshed to the latest: {len(changed)} package(s) changed.")
    for line in changed:
        print(f"  {line}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The core's tested versions, from uv.lock.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write both places from uv.lock")
    mode.add_argument("--upgrade", action="store_true", help="uv lock --upgrade, then write both places")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # "→" on a piped Windows console
    try:
        return upgrade() if args.upgrade else write() if args.write else check()
    except Refused as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
