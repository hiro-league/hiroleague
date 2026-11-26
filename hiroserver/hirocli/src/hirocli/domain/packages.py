"""An extension's package (build-kit/package.py's zip) as the core reads it before it installs anything: its manifest,
its wheels and its pinned requirements, and the checks that refuse it (the design's §8: name_taken, core_version,
port_taken, bad_manifest). Pure but for reading the zip, and for the core's own store of the packages handed to it.

**The store:** the person's file may sit where the core's account can't read it (a service core on Windows can't read
a person's Downloads), so the CLI hands the core the package's bytes, kept as ``<workspace>/packages/<sha-256>.zip``.
The install names it by that id and unpacks only that file. Retention: a package goes once its install is unpacked,
cancelled or removed; one no install names (its sheet was declined) goes a day after it came.
"""

from __future__ import annotations

import hashlib
import re
import time
import secrets
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hiro_channel_sdk.manifest import MANIFEST_FILE, Manifest, ManifestError, dashed, parse_manifest

REQUIREMENTS = "requirements.txt"
WHEELS = "wheels/"

# The refusals, as the design names them (the CLI and the admin say the words; the code is for scripts)
BAD_MANIFEST = "bad_manifest"
NAME_TAKEN = "name_taken"
CORE_VERSION = "core_version"
PORT_TAKEN = "port_taken"

_CLAUSE = re.compile(r"(>=|<=|==|!=|~=|<|>)\s*(\d+(?:\.\d+)*)")


class PackageRefused(ValueError):
    """The core won't install this package: ``code`` says which rule, the message is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Package:
    path: Path
    manifest: Manifest
    wheels: tuple[str, ...]  # their names inside the zip
    requirements: str


def open_package(path: Path) -> Package:
    """The package at ``path``; raises PackageRefused(bad_manifest) for a file that isn't one."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if MANIFEST_FILE not in names:
                raise PackageRefused(BAD_MANIFEST, f"{path.name} has no {MANIFEST_FILE} at its top: it isn't a package.")
            manifest = parse_manifest(zf.read(MANIFEST_FILE).decode("utf-8"))
            requirements = zf.read(REQUIREMENTS).decode("utf-8") if REQUIREMENTS in names else ""
    except ManifestError as exc:
        raise PackageRefused(BAD_MANIFEST, str(exc)) from exc
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise PackageRefused(BAD_MANIFEST, f"{path.name} can't be read as a package: {exc}") from exc
    for name in names:
        # Every member stays inside the folder it is unpacked to (no "..", no absolute path)
        parts = PurePosixPath(name).parts
        if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
            raise PackageRefused(BAD_MANIFEST, f"{path.name} holds a file outside its own folder ({name}).")
    wheels = tuple(n for n in names if n.startswith(WHEELS) and n.endswith(".whl"))
    if not wheels:
        raise PackageRefused(BAD_MANIFEST, f"{path.name} holds no wheel in {WHEELS}.")
    return Package(path=path, manifest=manifest, wheels=wheels, requirements=requirements)


def version_numbers(version: str) -> tuple[int, ...]:
    match = re.match(r"\d+(?:\.\d+)*", version)
    return tuple(int(n) for n in match[0].split(".")) if match else ()


def _compare(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def version_in(versions: str, version: str) -> bool:
    """Whether ``version`` (the core's, 0.2.0) is in the manifest's range (">=0.2,<0.3"): each clause compares the
    release numbers; ``~=X.Y`` is >=X.Y within X. Pure."""
    mine = version_numbers(version)
    for clause in versions.split(","):
        match = _CLAUSE.fullmatch(clause.strip())
        if not match:
            return False
        op, other = match[1], version_numbers(match[2])
        c = _compare(mine, other)
        ok = {
            ">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "==": c == 0, "!=": c != 0,
            "~=": c >= 0 and mine[: max(len(other) - 1, 1)] == other[: max(len(other) - 1, 1)],
        }[op]
        if not ok:
            return False
    return True


def service_name(key: str) -> str:
    """The app's service and its account, both: ``hiro-<key, dashed>`` (``hiro-acme-weather``)."""
    return f"hiro-{dashed(key)}"


# ---------------------------------------------------------------------------
# The core's store of packages handed to it
# ---------------------------------------------------------------------------

PACKAGES_DIR = "packages"
MAX_PACKAGE_BYTES = 512 * 1024 * 1024  # a package is wheels: HomeHiro's is a few MB
_PACKAGE_ID = re.compile(r"[0-9a-f]{64}")


def stored_package(workspace_path: Path, package_id: str) -> Path:
    """The stored package with this id; PackageRefused(bad_manifest) when the id isn't one or it is gone."""
    if not _PACKAGE_ID.fullmatch(package_id or ""):
        raise PackageRefused(BAD_MANIFEST, "That isn't a package handed to this core.")
    path = workspace_path / PACKAGES_DIR / f"{package_id}.zip"
    if not path.is_file():
        raise PackageRefused(BAD_MANIFEST, "That package isn't kept here any more: hand it to the core again.")
    return path


def keep_package(workspace_path: Path, chunks: Iterable[bytes]) -> str:
    """Keep a package's bytes; returns its id (its SHA-256). Written to a temporary file, then renamed, so a stored
    package is whole. PackageRefused(bad_manifest) past MAX_PACKAGE_BYTES."""
    folder = workspace_path / PACKAGES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    tmp = folder / f".incoming-{secrets.token_hex(6)}.part"
    try:
        with tmp.open("wb") as out:
            for chunk in chunks:
                size += len(chunk)
                if size > MAX_PACKAGE_BYTES:
                    raise PackageRefused(BAD_MANIFEST, f"A package is at most {MAX_PACKAGE_BYTES // 2**20} MB.")
                digest.update(chunk)
                out.write(chunk)
        package_id = digest.hexdigest()
        tmp.replace(folder / f"{package_id}.zip")
    finally:
        tmp.unlink(missing_ok=True)
    return package_id


def drop_package(workspace_path: Path, package_id: str) -> None:
    """Forget a stored package (its install was unpacked, cancelled or removed)."""
    if _PACKAGE_ID.fullmatch(package_id or ""):
        (workspace_path / PACKAGES_DIR / f"{package_id}.zip").unlink(missing_ok=True)


def prune_packages(workspace_path: Path, named: set[str], *, older_than_s: float = 86400.0) -> int:
    """Drop the stored packages no install names that came more than a day ago (a sheet declined, a CLI stopped);
    returns how many went."""
    folder = workspace_path / PACKAGES_DIR
    if not folder.is_dir():
        return 0
    cutoff = time.time() - older_than_s
    gone = 0
    for path in folder.glob("*.zip"):
        if path.stem not in named and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            gone += 1
    return gone
