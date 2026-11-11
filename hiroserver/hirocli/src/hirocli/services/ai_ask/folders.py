"""The folder an ``ai.ask`` may name for a plan tool to read (a code review).

An extension names a folder on the core's machine; the tool then starts there and reads it. So a use must
declare ``folder``, and the folder must lie inside one the admin allowed that extension (``ai.folders``):
without that, any paired extension could have a tool read any folder the core's user can. A symlink inside
an allowed folder that points out of it doesn't count: the folder is resolved before it is compared.
"""

from __future__ import annotations

from pathlib import Path

from hiro_channel_sdk.constants import AI_ERROR_INVALID

from .errors import AskError


def check_folder(folder: str, allowed: list[str], *, extension: str, use: str, use_reads_folders: bool) -> Path:
    """The resolved folder to read, or ``AskError`` invalid saying why it is refused."""
    if not use_reads_folders:
        raise AskError(AI_ERROR_INVALID, f"The use {use!r} doesn't declare that it reads a folder.")
    roots = [Path(r) for r in allowed if r.strip()]
    if not roots:
        raise AskError(AI_ERROR_INVALID, f"{extension} isn't allowed to name any folder: the admin allows folders in ai.folders.")
    if not folder.strip() or not Path(folder).is_absolute():
        raise AskError(AI_ERROR_INVALID, "folder must be an absolute path.")
    try:
        resolved = Path(folder).resolve(strict=True)
    except (OSError, RuntimeError):
        raise AskError(AI_ERROR_INVALID, f"There's no folder {folder!r} on the core's machine.") from None
    if not resolved.is_dir():
        raise AskError(AI_ERROR_INVALID, f"{folder!r} isn't a folder.")
    for root in roots:
        try:
            if resolved.is_relative_to(root.resolve()):
                return resolved
        except (OSError, RuntimeError):
            continue  # an allowed folder that can't be read allows nothing
    raise AskError(AI_ERROR_INVALID, f"{extension} isn't allowed to read {folder!r}: it is outside the folders the admin allowed.")
