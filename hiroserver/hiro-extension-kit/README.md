# Hiro Extension Kit

The backend every HiroLeague extension app is built on: the code HomeHiro, NetHiro and TrainHiro each had a copy of,
kept once. An app is a FastAPI + SQLModel + SQLite program that connects to the HiroLeague core as an extension.

- **`hiro-channel-sdk`** is the contract with the core: the extension socket, `Worker`, the rights check. It needs only
  pydantic and websockets, and channel plugins use it too.
- **`hiro-extension-kit`** (this package) is the app around it. It needs FastAPI, SQLModel and Alembic.

The plan and what moves next: the "Backend kit plan" Claude Doc.

## Using it

An app reads the kit from the HiroLeague checkout beside its own repo, as it reads the SDK (its `pyproject.toml`):

```toml
dependencies = ["hiro-extension-kit", "hiro-channel-sdk", ...]

[tool.uv.sources]
hiro-extension-kit = { path = "../../hiroleague/hiroserver/hiro-extension-kit", editable = true }
hiro-channel-sdk = { path = "../../hiroleague/hiroserver/hiro-channel-sdk", editable = true }
```

The app's package says which app it is before anything else of the kit is imported (its `__init__.py`):

```python
from pathlib import Path

import hiro_extension_kit

from .config import config

hiro_extension_kit.setup(name="nethiro", title="NetHiro", package=Path(__file__).parent,
                         data_dir=config.data_dir, static_dir=config.static_dir)
```

Everything that differs between apps comes from that one call (`identity.py`): logger names (`nethiro.<area>`), the
log files (`nethiro.log`, `nethiro-errors.log`), the database (`DATA_DIR/nethiro.db`), the migrations
(`<package>/migrations`) and the Logs page's source (`nethiro`). So moving an app onto the kit changes nothing on its
disk and nothing in its API.

## What is in it

| Module | What |
|---|---|
| `identity` | which app this is: `setup()`, `app()`, `logger(area)` |
| `errors` | `AppError` and its kinds (`Invalid` 400, `NotSignedIn` 401, `NotAllowed` 403, `NotFound` 404, `Busy` and `Conflict` 409, `Unavailable` 503, `OutsideError` 502), `failed()`, `guarded()`, `translate()`, and `install(app)`: every error turned into its HTTP answer in one place |
| `events` | `bus` (publish from any thread, subscribers run on the loop), `on_loop()`, `bind()` |
| `stopping` | `watch()`: the bus says "stopping" before uvicorn waits for open requests |
| `watchdog` | the `watchdog` worker: logs what blocks the event loop, and where |
| `calls` | timing calls to outside systems: `start()`, `done()` |
| `clock` | times in words, 12-hour with AM/PM and always the day: `spoken()`, `full()` |
| `files` | atomic writes: `write_bytes()`, `write_text()`, `write_lines()` |
| `schemas` | `Ok` |
| `logs` | `setup(folder)`: the console and the rotating files, uncaught exceptions, crashes |
| `logfiles`, `logs_api` | reading those files; the Logs page's routes (`router`) and its `notifier` worker |
| `db` | `Database`; the app's own: `engine`, `get_session`, `run_db()`, `migrate()` |
| `models` | the tables every app has (`Setting`); the app's `models.py` imports them |
| `settings` | `get()` and `put()` for key/value settings; each app names its own keys |
| `timeline` | `slots()`: counting times into slots |
| `ui` | `router`: the app's built UI, for every path that isn't the API |

## Rules

- **Nothing here names an app.** What differs comes from `identity`; an app's own additions stay in the app.
- **A move changes no behaviour**: no route, no answer's shape, no file name. Each app's `./scripts/check.sh` passes
  before and after.
- **The kit ships no migrations.** Each app's migrations already made the shared tables. A change to one of them is
  a change here plus a migration in every app.
- **No copies left behind.** An app imports the kit's module directly; its own copy is deleted, not kept as a wrapper.

## Tests

`./scripts/check.sh` in the HiroLeague repo runs them with the rest of the workspace (`hiroserver: pytest`). Only
this package: from `hiroserver/`, `uv run pytest hiro-extension-kit`. The tests run as an app called `testapp` with
an empty data folder of their own (`tests/conftest.py`).

A change here doesn't start an app's own check: after one, run `./scripts/check.sh --all` in each app that uses it.
