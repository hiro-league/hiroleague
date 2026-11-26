"""The front door's program: Caddy, one release pinned by its archives' SHA-256 (``hiro_commons.fetch``).

Caddy 2.11.9 (Nov 5, 2026), its latest stable release when reviewed (Nov 25, 2026): each archive's SHA-512 matched
the release's own ``caddy_2.11.9_checksums.txt`` and its SHA-256 matched GitHub's digest for the file. A new release
is pinned only after the same review; nothing is ever taken from a "latest" link.

``hiro service install`` fetches it into the Hiro home's ``caddy/<version>/`` (hirocli/front_door_setup.py), keeps
the archive beside the program (so a second install checks it again instead of downloading it) and takes out only
the program.
"""

from __future__ import annotations

import os
import platform
import sys
import tarfile
import zipfile
from pathlib import Path

from hiro_commons.fetch import FetchError, fetch_checked
from hiro_commons.systemd_service import ServiceError

CADDY_VERSION = "2.11.9"
_BASE = f"https://github.com/caddyserver/caddy/releases/download/v{CADDY_VERSION}"
# (system, machine) → (archive, its SHA-256)
ARCHIVES: dict[tuple[str, str], tuple[str, str]] = {
    ("linux", "amd64"): (f"caddy_{CADDY_VERSION}_linux_amd64.tar.gz",
                         "5b8cb7faf8726a2028ad96a66e54e6e81e8f361bc6175e5d22bbd997cc5177fb"),
    ("linux", "arm64"): (f"caddy_{CADDY_VERSION}_linux_arm64.tar.gz",
                         "5e377cff994fc9362a6fcf695c53f226cfca3a3ef85bd3a3687cf252d6310165"),
    ("mac", "amd64"): (f"caddy_{CADDY_VERSION}_mac_amd64.tar.gz",
                       "22af256a2cc45606f6bfa8786cd89130529331319665926f4e972234a658fb30"),
    ("mac", "arm64"): (f"caddy_{CADDY_VERSION}_mac_arm64.tar.gz",
                       "d075afc620376679a77b453399bf7ada264cab3280b2833e4ed1372abc0c1c13"),
    ("windows", "amd64"): (f"caddy_{CADDY_VERSION}_windows_amd64.zip",
                           "ad93112d335ee687100c4c9f11bced16ca590377976b7fe7883882b9e797e472"),
    ("windows", "arm64"): (f"caddy_{CADDY_VERSION}_windows_arm64.zip",
                           "bdf5fa34e7f3646ee04f59634d66cbcbfa39516f08108d8661ff3ceb3913a0c7"),
}
_MACHINES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def this_system() -> tuple[str, str]:
    system = "windows" if sys.platform == "win32" else "mac" if sys.platform == "darwin" else "linux"
    return system, _MACHINES.get(platform.machine().lower(), platform.machine().lower())


def program_name(system: str) -> str:
    return "caddy.exe" if system == "windows" else "caddy"


def fetch_caddy(caddy_home: Path, system: str | None = None, machine: str | None = None) -> Path:
    """Put the pinned Caddy at ``<caddy_home>/<version>/caddy[.exe]``; return its path. Raises ServiceError."""
    if system is None or machine is None:
        system, machine = this_system()
    pinned = ARCHIVES.get((system, machine))
    if pinned is None:
        raise ServiceError(f"Hiro League has no front door for {system} on {machine} yet.")
    archive_name, sha256 = pinned
    folder = caddy_home / CADDY_VERSION
    archive = folder / archive_name
    try:
        fetch_checked(f"{_BASE}/{archive_name}", archive, sha256)
    except FetchError as exc:
        raise ServiceError(str(exc)) from exc
    program = folder / program_name(system)
    _extract(archive, program_name(system), program)
    return program


def _extract(archive: Path, member: str, dest: Path) -> None:
    """Take ``member`` (and only it) out of the checked archive to ``dest``, replacing what was there."""
    tmp = dest.with_name(f".{dest.name}.new")
    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf, zf.open(member) as src:
                data = src.read()
        else:
            with tarfile.open(archive, "r:gz") as tf:
                found = tf.extractfile(member)
                if found is None:
                    raise ServiceError(f"{archive.name} holds no {member}.")
                with found as src:
                    data = src.read()
        # Fix: installing the service again replaced the program the running front door uses, which Windows refuses
        # (Access is denied, seen Nov 26, 2026). The archive is checked, so the same bytes are the pinned program.
        if dest.is_file() and dest.stat().st_size == len(data) and dest.read_bytes() == data:
            return
        tmp.write_bytes(data)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    except (OSError, KeyError, zipfile.BadZipFile, tarfile.TarError) as exc:
        tmp.unlink(missing_ok=True)
        raise ServiceError(f"Could not take Caddy out of {archive.name}: {exc}") from exc
