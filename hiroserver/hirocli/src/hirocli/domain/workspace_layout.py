"""Where a workspace keeps its credentials, and tidying an older workspace's root into that place (issue 438).

The root holds ``config.json``, ``preferences.json`` and each part's folder. The credentials live together in
``credentials/``: the providers' index (``credentials_index.json``; the keys themselves are in the OS keyring,
domain/credential_store.py) and the master key (``master_key.pem``, domain/crypto.py), which signs the devices'
pairing: a lost key means pairing every device again.

An older workspace has both files on its root. Whatever opens one moves it first (``move_credentials``): copy, check
the copy is the same bytes (the key: that it loads too), then remove the old one. When both exist and differ, both
stay and a warning says so: nothing is lost and nothing is guessed. The server's start also removes the copies the
settings conversions left behind (``drop_old_copies``): nothing reads them.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from hiro_commons.constants.storage import (
    CHARACTERS_DIR,
    CREDENTIALS_DIR,
    CREDENTIALS_INDEX_FILENAME,
    MASTER_KEY_FILENAME,
)
from hiro_commons.keys import load_private_key_pem
from hiro_commons.log import Logger

log = Logger.get("WORKSPACE")

# An older workspace's names, on its root.
_OLD_INDEX = "providers.json"
_OLD_KEY = MASTER_KEY_FILENAME
# The copies the settings conversions (v3 → v4, v4 → v5) left: on the root, and beside each character.
_OLD_COPIES = ("preferences.v3.json", "preferences.v4.json")
_OLD_CHARACTER_COPY = "character.v3.json"


def credentials_dir(workspace_path: Path) -> Path:
    return workspace_path / CREDENTIALS_DIR


def master_key_path(workspace_path: Path) -> Path:
    return credentials_dir(workspace_path) / MASTER_KEY_FILENAME


def credentials_index_path(workspace_path: Path) -> Path:
    return credentials_dir(workspace_path) / CREDENTIALS_INDEX_FILENAME


def _key_loads(data: bytes) -> None:
    load_private_key_pem(data)


def move_credentials(workspace_path: Path) -> None:
    """Move an older workspace's providers' index and master key into ``credentials/``. Cheap when there is nothing
    to move (two file checks), so whatever opens one calls it."""
    _move(workspace_path / _OLD_INDEX, credentials_index_path(workspace_path), "the providers' index", None)
    _move(workspace_path / _OLD_KEY, master_key_path(workspace_path), "the master key", _key_loads)


def _move(old: Path, new: Path, what: str, check: Callable[[bytes], None] | None) -> None:
    if not old.is_file():
        return
    data = old.read_bytes()
    if new.exists():
        if new.read_bytes() == data:
            old.unlink(missing_ok=True)  # a move that stopped before its last step: the copy is whole
            log.info(f"Workspace: {what}'s old copy on the root removed (the same file is in credentials/)", path=str(old))
        else:
            log.warning(
                f"⚠️ Workspace: {what} is both on the root and in credentials/, and they differ: both kept, "
                "credentials/ is used",
                old=str(old),
                new=str(new),
            )
        return
    new.parent.mkdir(parents=True, exist_ok=True)
    tmp = new.with_name(f"{new.name}.moving-{os.getpid()}")
    tmp.write_bytes(data)
    try:
        copied = tmp.read_bytes()
        if copied != data:
            raise OSError(f"the copy differs from {old.name}")
        if check is not None:
            check(copied)
    except (OSError, ValueError) as exc:
        tmp.unlink(missing_ok=True)
        log.error(f"❌ Workspace: {what} was not moved; it stays on the root", path=str(old), error=str(exc))
        return
    try:
        tmp.chmod(old.stat().st_mode)
    except OSError:
        pass  # Windows keeps no POSIX mode: the folder's own permissions hold
    os.replace(tmp, new)
    old.unlink()
    log.info(f"Workspace: {what} moved into credentials/", old=str(old), new=str(new))


def drop_old_copies(workspace_path: Path) -> None:
    """Remove the copies the settings conversions made of preferences.json and each character's file: nothing reads
    them, and a conversion writes none any more. Only these names, which the core itself wrote."""
    found = [workspace_path / name for name in _OLD_COPIES]
    characters = workspace_path / CHARACTERS_DIR
    if characters.is_dir():
        found += list(characters.glob(f"*/{_OLD_CHARACTER_COPY}"))
    for path in found:
        if path.is_file():
            path.unlink()
            log.info("Workspace: an old settings copy removed", path=str(path))
