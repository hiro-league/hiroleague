"""Logs: what the app did and what went wrong, kept in files that survive restarts and deploys.

The console (`docker logs`) is lost whenever the container is replaced, which every deploy does, and it mixes
problems with everything else. So the app logs through the Hiro League logging foundation
(`hiro_commons.logging_foundation`), which writes DATA_DIR/logs:
- `<app>-<YYYY-MM-DD>.jsonl` (the app's name, identity.py: `nethiro-2026-11-19.jsonl`): one file a day, kept 30 days;
  one JSON line per entry with OpenTelemetry's field names; INFO and up, or the level LOG_LEVELS gives an area;
- `crash.log`: a hard crash in native code (ONNX, OpenCV): every thread's Python stack, written by faulthandler.

The foundation also catches what would escape the file (uvicorn's own lines, a request that crashed included; an
exception nobody caught, in any thread; one nobody could raise; Python warnings), sends the SDK's lines (the link to
the core: `EXTENSION`, `CH_TRANSPORT`) into the same file, and never makes a request wait on the disk. Each app's
docs/backend-best-practices.md, section 5, says how the app logs.
"""

from pathlib import Path

from hiro_commons import logging_foundation as foundation

from . import extension, identity

KEEP_DAYS = foundation.KEEP_DAYS
LOGGERS = foundation.LOGGERS
CRASH_FILE = foundation.CRASH_FILE


def service() -> str:
    """The app in each line: its name as an extension (`net`), the name the core knows it by (design.md, rule 6);
    the kit's own name for it (`nethiro`) when it declares none."""
    try:
        return extension.ext().name
    except RuntimeError:
        return identity.app().name


def setup(folder: Path, console: bool = True) -> None:
    """Log INFO and above to the day's file in `folder`, and to the console (unless `console` is False: something
    else already does)."""
    foundation.setup(folder, name=identity.app().name, service=service(), console=console)


def close() -> None:
    """Write what is queued and close the files (the tests do, before deleting their folder; Windows can't delete an
    open file)."""
    foundation.close()
