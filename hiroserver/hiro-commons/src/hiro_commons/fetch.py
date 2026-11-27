"""Fetch a pinned program file (WinSW today, Caddy next) and keep it only when its SHA-256 is the one pinned.

The address, the file and its hash are pinned in the code that asks, after a person reviewed that release: nothing
is ever taken from a "latest" link. A file already in place with the right hash is not fetched again.

The machine's downloads folder (``shared_downloads(<the Hiro home>)``) keeps one copy of each pinned file, named by its
hash: a second place that wants the same file (each Windows service has its own WinSW) copies it from there instead of
downloading it again, and a test machine finds there what its run put in beforehand. A copy is checked like a
download, so a file changed there is refused. Kept with the Hiro home: one file per pinned version, tens of MB.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import truststore

from .log import Logger

log = Logger.get("FETCH")

_CHUNK = 1024 * 1024
_TIMEOUT_S = 60.0


class FetchError(RuntimeError):
    """The file couldn't be fetched, or wasn't the file pinned; the message says which and why."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def shared_downloads(home: Path) -> Path:
    """The machine's downloads folder under a Hiro home."""
    return home / "cache" / "downloads"


def shared_name(url: str, sha256: str) -> str:
    """A pinned file's name in the downloads folder: its hash, then the name it has at its address."""
    return f"{sha256.lower()}-{url.rsplit('/', 1)[-1]}"


def _from_shared(shared: Path, url: str, dest: Path, expected: str) -> bool:
    """Put the downloads folder's copy at ``dest`` when it has the pinned hash; True when it did."""
    kept = shared / shared_name(url, expected)
    if not kept.is_file():
        return False
    tmp = dest.with_name(f".{dest.name}.copy")
    try:
        shutil.copyfile(kept, tmp)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        log.warning("⚠️ Could not copy a pinned file from the downloads folder, so it is downloaded — HiroServer · fetch",
                    file=kept.name, error=str(exc))
        return False
    # Checked after the copy, so what lands at dest is what was checked
    if sha256_of(tmp) != expected:
        tmp.unlink(missing_ok=True)
        log.warning("⚠️ The downloads folder's copy is not the file pinned, so it is downloaded — HiroServer · fetch",
                    file=kept.name)
        return False
    os.replace(tmp, dest)
    log.info("✅ Pinned file taken from the downloads folder and checked — HiroServer · fetch", file=dest.name)
    return True


def _keep_shared(shared: Path, url: str, dest: Path, expected: str) -> None:
    """Keep a copy of a checked download in the downloads folder; a failure only costs a later download."""
    kept = shared / shared_name(url, expected)
    tmp = kept.with_name(f".{kept.name}.copy")
    try:
        shared.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dest, tmp)
        os.replace(tmp, kept)
    except OSError as exc:
        # Why the cleanup ignores its own failure: on Linux, with a file where the folder should be, the unlink raises
        # NotADirectoryError (Windows says FileNotFoundError, which missing_ok takes), and that failed the download.
        # The first error is the one logged below.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        log.warning("⚠️ Could not keep a copy in the downloads folder — HiroServer · fetch", file=kept.name, error=str(exc))


def fetch_checked(url: str, dest: Path, sha256: str, *, timeout: float = _TIMEOUT_S, shared: Path | None = None) -> bool:
    """Make ``dest`` the file at ``url`` whose SHA-256 is ``sha256``; return True when it was downloaded.

    The download goes to a temporary file beside ``dest`` and replaces it only once its hash matches, so ``dest`` is
    always either absent, the old file, or the pinned one. ``shared`` is the machine's downloads folder: its checked
    copy is used first, and a download leaves one there.
    """
    expected = sha256.lower()
    if dest.is_file() and sha256_of(dest) == expected:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if shared is not None and _from_shared(shared, url, dest, expected):
        return False
    tmp = dest.with_name(f".{dest.name}.download")
    started = time.monotonic()
    try:
        # A pinned https address from the code, never from a person or a page. The system checks the certificate
        # (truststore): a fresh Windows holds few roots and fetches a missing one only for its own checks, so Python's
        # check refused GitHub's (CERTIFICATE_VERIFY_FAILED, the fresh-install test in Windows Sandbox).
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response, tmp.open("wb") as out:  # noqa: S310
            while chunk := response.read(_CHUNK):
                out.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        reason = getattr(exc, "reason", None) or exc
        log.warning("⚠️ Could not download a pinned file — HiroServer · fetch", url=url, error=str(reason))
        raise FetchError(f"Could not download {dest.name} from {url}: {reason}.") from exc
    got = sha256_of(tmp)
    if got != expected:
        tmp.unlink(missing_ok=True)
        log.error(
            "❌ A downloaded file is not the one pinned: its checksum differs, so it was thrown away — HiroServer · fetch",
            url=url,
            expected=expected,
            got=got,
        )
        raise FetchError(
            f"{dest.name} from {url} is not the file this version of Hiro League expects (its SHA-256 differs), "
            "so it was not kept. Try again later; if it keeps happening, the release was changed and needs a review."
        )
    os.replace(tmp, dest)
    log.info(
        "✅ Pinned file downloaded and checked — HiroServer · fetch",
        file=dest.name,
        size_mb=round(dest.stat().st_size / 1_048_576, 1),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    if shared is not None:
        _keep_shared(shared, url, dest, expected)
    return True
