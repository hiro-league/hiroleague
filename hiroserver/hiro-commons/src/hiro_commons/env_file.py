"""A service's secrets file (``NAME=value`` lines), read by the program itself where no service manager reads it.

On Linux systemd loads the file into the service's environment (``EnvironmentFile=``). Windows' WinSW 2.12 and Mac's
launchd have no such setting (a LaunchDaemon's plist is readable by everyone, so secrets can't go there), so the
service passes the file's path instead and the program loads it at start. The format is the one systemd reads and
:func:`hiro_commons.systemd_service.render_env_file` writes: one ``NAME=value`` per line, ``#`` starts a comment, no
quotes, no spaces around ``=``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .log import Logger

log = Logger.get("SERVICE")

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvFileError(RuntimeError):
    """The secrets file can't be read; the message says which file and what to do."""


def parse_env_text(text: str) -> tuple[dict[str, str], list[int]]:
    """Return the variables a secrets file sets, and the numbers of the lines it couldn't read.

    A value is taken as written (systemd strips one pair of surrounding quotes; nobody writes them in this file, and
    a key with a quote in it must stay whole). A line that is neither a comment nor ``NAME=value`` is skipped and
    reported by number, never by its text: it may hold a key.
    """
    values: dict[str, str] = {}
    bad: list[int] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not _NAME_RE.match(name):
            bad.append(number)
            continue
        values[name] = value.strip()
    return values, bad


def load_env_file(path: Path, *, environ: dict[str, str] | None = None) -> list[str]:
    """Put the file's variables into the environment and return their names (never their values).

    A variable already in the environment is kept: the service sets only its own settings there, never a secret,
    and a file line must not change them. An empty value (``NAME=``) is left out, as an unset key.
    """
    target = os.environ if environ is None else environ
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise EnvFileError(
            f"The secrets file {path} is missing. Install the service again to make a new one "
            "(`hiro service install`), or point HIRO_SECRETS_FILE at the right file."
        ) from exc
    except OSError as exc:
        raise EnvFileError(f"The secrets file {path} can't be read ({exc.strerror or exc}).") from exc
    values, bad = parse_env_text(text)
    if bad:
        log.warning(
            "⚠️ Secrets file: some lines are not NAME=value and were skipped — HiroServer · service",
            path=str(path),
            lines=bad,
        )
    loaded = []
    for name, value in values.items():
        if value and name not in target:
            target[name] = value
            loaded.append(name)
    return loaded
