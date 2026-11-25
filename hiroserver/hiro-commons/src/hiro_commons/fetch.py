"""Fetch a pinned program file (WinSW today, Caddy next) and keep it only when its SHA-256 is the one pinned.

The address, the file and its hash are pinned in the code that asks, after a person reviewed that release: nothing
is ever taken from a "latest" link. A file already in place with the right hash is not fetched again.
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

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


def fetch_checked(url: str, dest: Path, sha256: str, *, timeout: float = _TIMEOUT_S) -> bool:
    """Make ``dest`` the file at ``url`` whose SHA-256 is ``sha256``; return True when it was downloaded.

    The download goes to a temporary file beside ``dest`` and replaces it only once its hash matches, so ``dest`` is
    always either absent, the old file, or the pinned one.
    """
    expected = sha256.lower()
    if dest.is_file() and sha256_of(dest) == expected:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.download")
    started = time.monotonic()
    try:
        # A pinned https address from the code, never from a person or a page.
        with urllib.request.urlopen(url, timeout=timeout) as response, tmp.open("wb") as out:  # noqa: S310
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
    return True
