"""An extension's package as the core reads it before it installs anything, and the checks that refuse it (the
design's §8: name_taken, core_version, port_taken, bad_manifest). Pure but for reading the wheel, and for the core's
own store of the packages handed to it.

**A package is the app's wheel**, built by build-kit/package.py and installed with ``uv tool install`` as the core
is. The wheel carries two files beside its code, in its module's folder: its manifest (``hiro-extension.toml``) and
the versions its uv.lock pins (``hiro-constraints.txt``, one ``name==version`` a line), which the install passes as
``--constraints``. Its libraries that aren't on PyPI (the kits) are wheels of their own beside it, each named for one
of those pins (``hiro_extension_kit-0.2.0-py3-none-any.whl``); every other pin comes from PyPI.

**The store:** the person's file may sit where the core's account can't read it (a service core on Windows can't read
a person's Downloads), so the CLI hands the core the wheels' bytes, kept in ``<workspace>/packages/<id>/`` under their
own names, the id being the app's wheel's SHA-256. The install names it by that id and installs only those files.
Retention: a package goes once its install is done, cancelled or removed; one no install names (its sheet was
declined) goes a day after it came.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import shutil
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hiro_channel_sdk.manifest import MANIFEST_FILE, Manifest, ManifestError, dashed, parse_manifest

CONSTRAINTS_FILE = "hiro-constraints.txt"
WHEEL = ".whl"

# The refusals, as the design names them (the CLI and the admin say the words; the code is for scripts)
BAD_MANIFEST = "bad_manifest"
NAME_TAKEN = "name_taken"
CORE_VERSION = "core_version"
PORT_TAKEN = "port_taken"

_CLAUSE = re.compile(r"(>=|<=|==|!=|~=|<|>)\s*(\d+(?:\.\d+)*)")
# A wheel's file name: {name}-{version}(-{build})?-{python}-{abi}-{platform}.whl (PEP 427)
_WHEEL_NAME = re.compile(r"(?P<name>[A-Za-z0-9_.]+)-(?P<version>[A-Za-z0-9_.+!]+)(?:-\d[^-]*)?-[^-]+-[^-]+-[^-]+\.whl")
_PIN = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;#]+)")


class PackageRefused(ValueError):
    """The core won't install this package: ``code`` says which rule, the message is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Package:
    path: Path  # the app's wheel
    manifest: Manifest
    constraints: str  # its pinned versions, as uv tool install's --constraints reads them
    libraries: tuple[Path, ...]  # the wheels beside it for its pins that aren't on PyPI (the kits)


def core_constraints() -> Path:
    """The core's own tested versions: every version its uv.lock pins, for every package of its workspace, its
    channels' included (scripts/tested_versions.py writes it, inside the core's package). A channel installs with it
    as ``--constraints``, so it runs on the versions the core was tested with."""
    return Path(__file__).resolve().parent.parent / CONSTRAINTS_FILE


def normalized(name: str) -> str:
    """A project's name as PyPI compares it (PEP 503): ``Hiro_Extension.Kit`` → ``hiro-extension-kit``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_name(file: str) -> tuple[str, str] | None:
    """(name, version) of a wheel's file name, the name normalized; None when it isn't a wheel's name."""
    match = _WHEEL_NAME.fullmatch(file)
    return (normalized(match["name"]), match["version"]) if match else None


def pins(constraints: str) -> dict[str, str]:
    """The ``name==version`` lines of a constraints file, by normalized name."""
    found: dict[str, str] = {}
    for line in constraints.splitlines():
        match = _PIN.match(line)
        if match:
            found[normalized(match[1])] = match[2]
    return found


def _module_file(names: list[str], file: str) -> str | None:
    """The one member ``<module>/<file>`` of a wheel (its module's folder, never its .dist-info), or None."""
    found = [n for n in names if (p := PurePosixPath(n)).name == file and len(p.parts) == 2
             and not p.parts[0].endswith((".dist-info", ".data"))]
    return found[0] if len(found) == 1 else None


def read_manifest(path: Path) -> tuple[Manifest, str] | None:
    """The manifest and the constraints inside a wheel; None for a wheel with no manifest (a library). Raises
    PackageRefused(bad_manifest) for a file that can't be read, or a manifest the core can't use."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            member = _module_file(names, MANIFEST_FILE)
            if member is None:
                return None
            manifest = parse_manifest(zf.read(member).decode("utf-8"))
            constraints_member = _module_file(names, CONSTRAINTS_FILE)
            constraints = zf.read(constraints_member).decode("utf-8") if constraints_member else ""
    except ManifestError as exc:
        raise PackageRefused(BAD_MANIFEST, str(exc)) from exc
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise PackageRefused(BAD_MANIFEST, f"{path.name} can't be read as a wheel: {exc}") from exc
    return manifest, constraints


def libraries_beside(path: Path, constraints: str) -> tuple[Path, ...]:
    """The wheels in the app's wheel's folder named for one of its pins, at that pin's version: its libraries that
    aren't on PyPI. Any other wheel there is left alone."""
    wanted = pins(constraints)
    found: list[Path] = []
    for other in sorted(path.parent.glob(f"*{WHEEL}")):
        named = wheel_name(other.name)
        if other != path and named is not None and wanted.get(named[0]) == named[1]:
            found.append(other)
    return tuple(found)


def open_package(path: Path) -> Package:
    """The app's wheel at ``path`` and its libraries beside it; raises PackageRefused(bad_manifest) for a file that
    isn't an extension's wheel."""
    if path.suffix != WHEEL or wheel_name(path.name) is None:
        raise PackageRefused(BAD_MANIFEST, f"{path.name} isn't a wheel: a package is the app's .whl file.")
    read = read_manifest(path)
    if read is None:
        raise PackageRefused(BAD_MANIFEST, f"{path.name} has no {MANIFEST_FILE} in its module: it isn't an extension's "
                                           "package (build it with build-kit/package.py).")
    manifest, constraints = read
    return Package(path=path, manifest=manifest, constraints=constraints,
                   libraries=libraries_beside(path, constraints))


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
MAX_PACKAGE_BYTES = 512 * 1024 * 1024  # a wheel: HomeHiro's is a few MB
_PACKAGE_ID = re.compile(r"[0-9a-f]{64}")


def _store(workspace_path: Path, package_id: str) -> Path:
    if not _PACKAGE_ID.fullmatch(package_id or ""):
        raise PackageRefused(BAD_MANIFEST, "That isn't a package handed to this core.")
    return workspace_path / PACKAGES_DIR / package_id


def stored_package(workspace_path: Path, package_id: str) -> Path:
    """The app's wheel of the stored package with this id; PackageRefused(bad_manifest) when the id isn't one or it is
    gone."""
    folder = _store(workspace_path, package_id)
    for path in sorted(folder.glob(f"*{WHEEL}")) if folder.is_dir() else []:
        if read_manifest(path) is not None:
            return path
    raise PackageRefused(BAD_MANIFEST, "That package isn't kept here any more: hand it to the core again.")


def keep_package(workspace_path: Path, file: str, chunks: Iterable[bytes], *, into: str = "") -> str:
    """Keep one wheel of a package under its own name: the app's wheel (its id is its SHA-256, answered), or with
    ``into`` one of its libraries, beside the app's wheel of that id. Written to a temporary file, then renamed, so a
    stored wheel is whole. PackageRefused(bad_manifest) for a name that isn't a wheel's, or past MAX_PACKAGE_BYTES."""
    if "/" in file or "\\" in file or wheel_name(file) is None:
        raise PackageRefused(BAD_MANIFEST, f"{file} isn't a wheel's file name.")
    root = workspace_path / PACKAGES_DIR
    root.mkdir(parents=True, exist_ok=True)
    if into and not _store(workspace_path, into).is_dir():
        raise PackageRefused(BAD_MANIFEST, "That package isn't kept here any more: hand it to the core again.")
    digest = hashlib.sha256()
    size = 0
    tmp = root / f".incoming-{secrets.token_hex(6)}.part"
    try:
        with tmp.open("wb") as out:
            for chunk in chunks:
                size += len(chunk)
                if size > MAX_PACKAGE_BYTES:
                    raise PackageRefused(BAD_MANIFEST, f"A wheel is at most {MAX_PACKAGE_BYTES // 2**20} MB.")
                digest.update(chunk)
                out.write(chunk)
        package_id = into or digest.hexdigest()
        folder = _store(workspace_path, package_id)
        folder.mkdir(exist_ok=True)
        tmp.replace(folder / file)
    finally:
        tmp.unlink(missing_ok=True)
    return package_id


def keep_package_files(workspace_path: Path, package: Package) -> str:
    """Keep a package the core can read itself (the Hiro home's packages folder): its wheel, then its libraries."""
    package_id = keep_package(workspace_path, package.path.name, [package.path.read_bytes()])
    for library in package.libraries:
        keep_package(workspace_path, library.name, [library.read_bytes()], into=package_id)
    return package_id


def drop_package(workspace_path: Path, package_id: str) -> None:
    """Forget a stored package (its install was done, cancelled or removed)."""
    if _PACKAGE_ID.fullmatch(package_id or ""):
        # A folder that can't go now (a file held open on Windows) is no install's: prune_packages takes it later
        shutil.rmtree(workspace_path / PACKAGES_DIR / package_id, ignore_errors=True)


def prune_packages(workspace_path: Path, named: set[str], *, older_than_s: float = 86400.0) -> int:
    """Drop the stored packages no install names that came more than a day ago (a sheet declined, a CLI stopped);
    returns how many went."""
    root = workspace_path / PACKAGES_DIR
    if not root.is_dir():
        return 0
    cutoff = time.time() - older_than_s
    gone = 0
    for folder in root.iterdir():
        if folder.is_dir() and _PACKAGE_ID.fullmatch(folder.name) and folder.name not in named \
                and folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            gone += 1
    return gone
