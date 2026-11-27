"""The core's tested versions: every third-party version hiroserver/uv.lock pins, written into the hiroleague package.

    python scripts/tested_versions.py            # check: the pins say what uv.lock says (scripts/check.sh)
    python scripts/tested_versions.py --write    # after a dependency changed: uv lock, then the pins written
    python scripts/tested_versions.py --upgrade  # refresh: uv lock --upgrade, then the pins written (hiro-work lock-refresh)

uv resolves a tool afresh at every `uv tool install`, whatever a lock says (it reads no pins from the installed
package's own [tool.uv] settings either). So the hiroleague package's dependencies (hiroserver/hiroleague/pyproject.toml,
between its two "tested versions" lines) hold every version its tree locks, exactly (``name==version``, the lock's
markers kept): a person's ``uv tool install hiroleague``, ``hiro upgrade``, pipx and pip install the tested set, and an
upgrade moves to the next release's. The workspace's own packages (hirocli, the SDK, the channels) aren't pinned: they
are released together.

The block's first line says when the lock was last refreshed to the latest (``--upgrade``); the session-start check
reads it, and says when the weekly refresh is due. Standard library only.
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
PACKAGE = "hiroleague"

START = "    # --- tested versions: written by scripts/tested_versions.py from uv.lock, never by hand ---"
END = "    # --- tested versions: end ---"
REFRESHED = re.compile(r"^ *# Refreshed to the latest: (\d{4}-\d{2}-\d{2}|never)", re.MULTILINE)
NEVER = "never"  # a lock nobody has refreshed with --upgrade yet
_EXPORT = ("export", "--frozen", "--no-emit-workspace", "--no-dev", "--no-hashes", "--no-header",
           "--format", "requirements.txt", "--package", PACKAGE)


class Refused(Exception):
    """What the script won't do, in words."""


# A local version (``torch==2.12.0+cpu``): which build of a version, from PyTorch's own index. A pin names the version
# only, which matches every build: the install chooses the build (uv's ``--torch-backend``), and ``+cpu`` isn't on
# PyPI, so a pin that held it would fail every install from there.
_LOCAL_VERSION = re.compile(r"^([^\s;=]+==[^\s;+]+)\+[A-Za-z0-9.]+")


def requirements(exported: str) -> list[str]:
    """The ``name==version [; marker]`` lines of a ``uv export``, comments, options and builds (``+cpu``) left out."""
    return [_LOCAL_VERSION.sub(r"\1", line.strip()) for line in exported.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))]


def versions(lock_text: str) -> dict[str, str]:
    """Each locked package's version by name; a package locked at two versions (two Pythons) keeps both, joined."""
    found: dict[str, set[str]] = {}
    for p in tomllib.loads(lock_text).get("package", []):
        if "version" in p:
            found.setdefault(p["name"], set()).add(p["version"])
    return {name: ", ".join(sorted(v)) for name, v in found.items()}


def with_pins(pyproject: str, pins: list[str], refreshed_on: str | None) -> str:
    """The meta-package's pyproject with its tested-versions block holding the refresh day and ``pins`` (none: only
    the day)."""
    block = [START, f"    # Refreshed to the latest: {refreshed_on or NEVER} (uv lock --upgrade)",
             *(f'    "{pin}",' for pin in pins), END]
    lines = pyproject.splitlines()
    if START not in lines or END not in lines or lines.index(END) < lines.index(START):
        raise Refused(f"{META.relative_to(REPO)} has no tested-versions block: its dependencies need the lines\n"
                      f"{START}\n{END}")
    start, end = lines.index(START), lines.index(END)
    return "\n".join([*lines[:start], *block, *lines[end + 1:]]) + "\n"


def refreshed(pyproject: str) -> str | None:
    """The day the lock was last refreshed to the latest, as the block says it (ISO); None when it never was, or it
    doesn't say."""
    match = REFRESHED.search(pyproject)
    return match[1] if match and match[1] != NEVER else None


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


def expected(refreshed_on: str | None) -> str:
    """What the meta-package's pyproject should hold for today's uv.lock."""
    return with_pins(META.read_text(encoding="utf-8"), requirements(_uv(*_EXPORT)), refreshed_on)


def _today() -> str:
    """This PC's day (ISO): the day a person refreshed the lock."""
    return datetime.now().astimezone().date().isoformat()


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


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
    if META.read_text(encoding="utf-8") != expected(refreshed(META.read_text(encoding="utf-8"))):
        print(f"The tested versions in {META.relative_to(REPO).as_posix()} aren't uv.lock's: run "
              "`python scripts/tested_versions.py --write` and commit them with the lock.")
        return 1
    print("The tested versions match uv.lock.")
    return 0


def _resolve(lock: tuple[str, ...], refreshed_on: str | None) -> list[str]:
    """``uv lock`` (with ``lock``'s options), then the pins written from the new lock; returns what moved. The pins
    come out first, or they would hold the lock where it is; on a failure both files are put back as they were."""
    before_lock = LOCK.read_text(encoding="utf-8")
    before_meta = META.read_text(encoding="utf-8")
    try:
        _write(META, with_pins(before_meta, [], refreshed_on))
        _uv("lock", *lock)
        _write(META, expected(refreshed_on))
        _relock()
    except BaseException:
        _write(META, before_meta)
        _write(LOCK, before_lock)
        raise
    return changes(versions(before_lock), versions(LOCK.read_text(encoding="utf-8")))


def _say_moved(what: str, moved: list[str]) -> None:
    print(f"{what}: {len(moved)} package(s) changed.")
    for line in moved:
        print(f"  {line}")


def write() -> int:
    """After a dependency changed: uv lock moves only what the change needs (a locked version stays unless a
    requirement now refuses it), then the pins are written."""
    _say_moved("uv.lock and the tested versions written", _resolve((), refreshed(META.read_text(encoding="utf-8"))))
    return 0


def upgrade() -> int:
    """The refresh: uv lock --upgrade, every package to its latest. A version held back on purpose is a constraint in
    the workspace's pyproject ([tool.uv] constraint-dependencies), with its reason: uv lock keeps to it."""
    _say_moved("uv.lock refreshed to the latest", _resolve(("--upgrade",), _today()))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The core's tested versions, from uv.lock.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="after a dependency changed: uv lock, then the pins written")
    mode.add_argument("--upgrade", action="store_true", help="uv lock --upgrade, then the pins written")
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
