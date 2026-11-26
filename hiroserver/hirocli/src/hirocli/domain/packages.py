"""An extension's package (build-kit/package.py's zip) as the core reads it before it installs anything: its manifest,
its wheels and its pinned requirements, and the checks that refuse it (the design's §8: name_taken, core_version,
port_taken, bad_manifest). Pure but for reading the zip.
"""

from __future__ import annotations

import re
import zipfile
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


def _numbers(version: str) -> tuple[int, ...]:
    match = re.match(r"\d+(?:\.\d+)*", version)
    return tuple(int(n) for n in match[0].split(".")) if match else ()


def _compare(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def version_in(versions: str, version: str) -> bool:
    """Whether ``version`` (the core's, 0.2.0) is in the manifest's range (">=0.2,<0.3"): each clause compares the
    release numbers; ``~=X.Y`` is >=X.Y within X. Pure."""
    mine = _numbers(version)
    for clause in versions.split(","):
        match = _CLAUSE.fullmatch(clause.strip())
        if not match:
            return False
        op, other = match[1], _numbers(match[2])
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
