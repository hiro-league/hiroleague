"""Writing files: every file an app writes goes through here.

A write is atomic: the data goes to a temporary file next to the target, which is then renamed over it.
A reader never sees half a file, and a crash mid-write leaves the old file (or none), never a torn one.
Before this, a torn `state.json` made the WhatsApp worker forget a "hold" or "reset" it had been asked for.
"""

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path


def write_bytes(target: Path, data: bytes) -> Path:
    """Write `data` to `target` atomically, making its folder if needed."""
    target.parent.mkdir(parents=True, exist_ok=True)
    # A name of its own per write: two writers of the same file can't mix their data.
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)  # mkstemp makes it 0600; keep what a plain write would give
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def write_text(target: Path, text: str) -> Path:
    """Write `text` (UTF-8) to `target` atomically."""
    return write_bytes(target, text.encode("utf-8"))


def write_lines(target: Path, lines: Iterable[str]) -> Path:
    """Write `lines` (each with a line break added) to `target` atomically, without holding them all in memory (a
    list of millions of names)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for line in lines:
                f.write(line)
                f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
