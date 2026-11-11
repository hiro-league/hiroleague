"""Which app this is: the one thing every module here needs to know before it can do its work.

The kit is the same code in every app (HomeHiro, NetHiro, TrainHiro). What differs is told once, by the app, before
anything else of the kit is imported (`hiro_extension_kit.setup(...)` in the app package's `__init__.py`):

- `name`: the app's short name ("nethiro"). Its loggers are `<name>.<area>`, its log files `<name>.log` and
  `<name>-errors.log`, its database `<name>.db`, and its Logs page's own source is `<name>`.
- `title`: the name people read ("NetHiro"), for messages.
- `package`: the app's package folder (`.../src/nethiro`): its migrations are in `package/migrations`, and the
  watchdog reports the app's own frames of a stack.
- `data_dir`: where the database, the logs and every stored file live (the app's DATA_DIR).
- `static_dir`: the built UI (the app's STATIC_DIR).

One process is one app, so this is one module-level value. Modules read it when they load (their logger, their
folders), which is why `setup()` comes first; a module loaded before it fails with a sentence that says so.
(`errors` is the one module that may be imported before it: an app's config.py raises its errors, and the config is
what `setup()` is given.)
"""

import logging
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Identity:
    name: str
    title: str
    package: Path
    data_dir: Path
    static_dir: Path


_identity: Identity | None = None


def setup(*, name: str, title: str, package: Path, data_dir: Path, static_dir: Path) -> Identity:
    """Say which app this is. Called once, by the app's package, before any other module of the kit is imported."""
    global _identity
    _identity = Identity(name=name, title=title, package=Path(package).resolve(), data_dir=Path(data_dir).resolve(),
                         static_dir=Path(static_dir).resolve())
    return _identity


def app() -> Identity:
    """The app this process is."""
    if _identity is None:
        raise RuntimeError("hiro_extension_kit isn't set up: the app's package calls hiro_extension_kit.setup(...) "
                           "in its __init__.py, before anything else of the kit is imported")
    return _identity


def logger(area: str) -> logging.Logger:
    """The app's logger for an area: `nethiro.errors`. The Logs page shows each area by its logger's name, so the
    kit's modules log under the app's name, as the app's own copies of them did."""
    return logging.getLogger(f"{app().name}.{area}")
