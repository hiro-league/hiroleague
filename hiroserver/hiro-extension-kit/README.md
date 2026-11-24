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
from .extension import EXTENSION  # Extension(name="net", port=8130, features=..., rules=..., ...)

hiro_extension_kit.setup(name="nethiro", title="NetHiro", package=Path(__file__).parent,
                         data_dir=config.data_dir, static_dir=config.static_dir, extension=EXTENSION)
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
| `logs` | `setup(folder)`: the app on the logging foundation (`hiro_commons.logging_foundation`): one JSON-lines file a day, the console, the link's lines, uncaught exceptions, crashes |
| `logfiles`, `logs_api` | reading those files; the Logs page's routes (`router`) and its `notifier` worker |
| `db` | `Database` (an app may make a second one: HomeHiro's streams.db); the app's own (`main`): `engine`, `get_session`, `run_db()`, `migrate()` |
| `models` | the table every app has (`Setting`); the app's `models.py` imports it |
| `settings` | `get()` and `put()` for key/value settings; each app names its own keys |
| `timeline` | `slots()`: counting times into slots |
| `ui` | `router`: the app's built UI, for every path that isn't the API |
| `extension` | `Extension`: what the app is as an extension (name in the core, port, Apps card, features, route rules, offers, AI uses), passed to `setup(..., extension=)` |
| `hiroleague`, `hiroleague_api` | `link`: the connection to the core (pairing, the app's LAN name, `info_for`), its settings in the app's database or a store the app hands it (`use_settings`, `LinkSettings`: CodeHiro's own); Settings → HiroLeague's routes |
| `pair` | `main(argv)`: the first pairing from the server's shell (an app's `pair.py` runs it) |
| `family` | the copy of the core's family list and roles (`worker`, `sync`, `update_person`, `reachable`), and the one-time copy of rights from the app a feature came from |
| `auth` | `identity`, `sessions`, `access` (rights per role), `api` (`/api/me`, sign-in, Settings → Users and Roles), `one_sign_in` (the one sign-in as far as it talks to the core: `auth.code`, the sign-in and sign-out addresses; CodeHiro uses it alone), `guard` (every route's check), `rules` (`Rule`, `for_features`), `models` (`CorePerson`, `Role`, `AppUser`, `WebSession`, imported by an app that uses them). All three apps use it; an app's extras come in through `Extension`: another way in (`other_way`, HomeHiro's HA add-on), what it keeps per user beside the role (`users_scope`, HomeHiro's My room), its own rows tidied after each family sync (`family_tidy`) |
| `site_name` | the LAN name rules (`site_name`, `name_of`) |
| `llm` | optional, for an app that asks the core's AI: `profiles.ask()` (with a `folder` for a plan tool to read), `core_ai` (the core's profiles and the app's uses, kept in the link's settings), `recorder` and `requests_api` (Logs → LLM requests; `Extension(llm_log=False)` keeps none), `ai_api`, and its table (`llm.models.LlmRequest`, which the app's models.py imports) |
| `voices` | optional: the core's voice profiles for the pickers (`read`, `choices`, the `reader` worker), and for an app with a voice use (`Extension.voice_uses`) `speak()` and `set_default()` |
| `whatsapp` | optional: `send()` (text, picture, voice note; honours `Extension.outputs`), `check()`, `status()`, `notify()` through the core's WhatsApp |
| `predeploy` | a deploy's safety steps for the app's one database (`snapshot`, `trial`, `restore`, `main`); HomeHiro takes its helpers (`copy_db`, `counts`, `losses`) for its own two-database steps |
| `api_types` | the frontend's types from the API description (`generate`, `clashes`); each app's `scripts/api_types.py` says where they go |
| `notices` | `Browsers(notices, hello=...)` and `events_router(browsers)`: `GET /api/events`, the notices open pages reload on |
| `testing` | for an app's tests only: `guard_network()`, `RunLog`, `CleanDatabases`, `wait_until()`, `FakeCore`, `FakeLink`, `DictSettings` (a settings store of the app's own), `join_family()`, `ai_answer()` and `ai_profiles()` (the core's AI answers), `auth()` and `outputs()` (sign-in or sending on or off for one test) |
| `contract` | for an app's tests only: `AppContract`, what every app checks of itself (below) |

## Rules

- **The build, check and deploy files are shared too**, in HiroLeague's `build-kit/` (shared-code plan, step 2): the
  Dockerfile, the deploy, the nightly check, `check.sh`'s engine and `dev.ps1`. Each app keeps its entry points
  (`deploy.sh`, `deploy/nightly-check.sh`, `scripts/check.sh`, `dev.ps1`: a few lines each) and its facts (`app.env`).
  So a change there reaches every app's next deploy without a commit in the app: deploy the core first, and run each
  app's `./scripts/check.sh --all` before (`build-kit/README.md`).

- **Nothing here names an app.** What differs comes from `identity`; an app's own additions stay in the app.
- **A move changes no behaviour**: no route, no answer's shape, no file name. Each app's `./scripts/check.sh` passes
  before and after.
- **The kit ships no migrations.** Each app's migrations already made the shared tables. A change to one of them is
  a change here plus a migration in every app.
- **No copies left behind.** An app imports the kit's module directly; its own copy is deleted, not kept as a wrapper.

## Tests

An app's `tests/conftest.py` builds on `testing`: it sets its environment, imports its package (which calls
`setup()`), then calls `testing.guard_network()`, registers `testing.RunLog`, and copies its databases back for every
test with `testing.CleanDatabases`. Its `tests/fakes.py` gives `testing.FakeCore` its own defaults (NetHiro: its AI
use and HomeHiro's answers) and keeps the fakes of its own outside systems (HA, Frigate).

**The kit's features are tested here, once** (shared-code plan, step 1): sign-in, the route check, the family copy,
WhatsApp, voices, the core's AI and the LLM requests log, the site name, Settings → HiroLeague, predeploy, times. An
app's tests keep only its own code: its routes' rules, what it declares (`tests/test_extension.py`), its hooks
(HomeHiro's HA add-on sign-in, My room, family tidy) and its features. What only the app can show (its test setup is
safe, every route has a rule and declares its answer, its frontend's types are fresh, its workers can run, its
migrations match its models and lose nothing, it writes files through `files` and logs to its data folder, the kit's
routes are mounted) is `contract.AppContract`, which each app subclasses in `tests/test_contract.py`.

`./scripts/check.sh` in the HiroLeague repo runs them with the rest of the workspace (`hiroserver: pytest`). Only
this package: from `hiroserver/`, `uv run pytest hiro-extension-kit`. The tests run as an app called `testapp` with
an empty data folder of their own and every table the kit ships (`tests/conftest.py`): an extension shaped like
NetHiro's, with sign-in off and nothing sent unless a test turns them on.

A change here doesn't start an app's own check: after one, run `./scripts/check.sh --all` in each app that uses it.
