# Build kit

The build, check and deploy files every Hiro app shares (HomeHiro, NetHiro, TrainHiro, StudyHiro): one copy, here,
that each app runs from its own folder with its own facts. Before it, each app had its own copy of every file, and
they drifted (shared-code plan, step 2). A change to how apps are built, checked or deployed is one edit here.

| File | What it is | Run by |
|---|---|---|
| `Dockerfile` | The app's image: the UI built and checked, the backend installed and checked, the image that runs | the app's `compose.yaml` (`dockerfile: ../hiroleague/build-kit/Dockerfile`) |
| `deploy.sh` | A deploy on the server: the image built, the database copied, the migrations tried on a copy, the new version started, back to the previous one if it doesn't answer | the app's `deploy.sh` (the post-receive hook after `git push server main`) |
| `nightly-check.sh` | The nightly full check on the server (the Dockerfile's `fullcheck` target), reported to NetHiro's System health | the app's `deploy/nightly-check.sh` (aicam's timers) |
| `check-engine.sh` | The engine of every repo's `./scripts/check.sh`: when a part runs or is skipped, the summary | every repo's `scripts/check.sh`, HiroLeague's too |
| `backend-check.sh` | The backend checks (ruff, pyright, import rules, pytest), the same on the PC and in the image | the app's `scripts/check.sh` and the Dockerfile's `check` stage |
| `dev.ps1` | `.\dev` on the PC: packages installed, backend and UI started with live reload (env0's ports) | the app's `dev.ps1` |
| `work/hiro_work.py` | `hiro-work`: the environments (env0 to env5), tasks and their claims, servers, landing (hiro-docs `standards/workflow.md`); its tests beside it | `C:\hiro\bin\hiro-work.cmd`; the core's check runs its tests |

The UI kit has the two frontend pieces: `ui-kit/scripts/kit-sync.mjs` (each app's `npm run kit`) and
`ui-kit/src/lib/eslint-preset.js` (each app's `eslint.config.js`).

## An app's facts: `app.env`

Each app has an `app.env` at its root, read by everything here (bash `source`, PowerShell, and Docker Compose's
`env_file`, which gives the running container `APP` and `APP_PORT`):

```bash
APP=homehiro                 # the Python package, the image (homehiro:local), the container, the compose service
APP_NAME=HomeHiro            # as people read it
APP_PORT=8100                # where it listens on the server, loopback only (hiroleague.py SITE_PORT says the same)
START_PATIENCE=30            # seconds a new version may take to answer after a deploy (plus twice its migrations)
DEV_PORT=7003                # the backend in .\dev: env0's port (hiro-docs standards/workflow.md, Ports)
DEV_UI_PORT=7004             # the UI in .\dev (the one to open)
BACKEND_CHECKS="ruff pytest" # what backend-check.sh runs: ruff, pyright, imports, pytest
```

## What each app keeps

- `app.env`, `compose.yaml` (its volumes, environment and network: its own), `.dockerignore`, `deploy/post-receive`.
- `deploy.sh`, `deploy/nightly-check.sh`, `dev.ps1`: a few lines that run the copy here from the app's folder.
- `scripts/check.sh`: its parts (what it checks), on the engine here.
- Its `predeploy.py` (`python -m <app>.predeploy snapshot|trial|restore|settled`), the backend kit's unless it has more
  to copy (HomeHiro's streams.db).

## Where it runs

The app's repo sits beside the HiroLeague checkout: `../hiroleague` from the app's root, on the PC and on the server
(`~/hiroleague`, refreshed by the core's deploy). So **a change here reaches every app's next deploy and nightly check**:
deploy the core first, then each app, and run each app's `./scripts/check.sh --all` before (a change here doesn't start
an app's check by itself). HiroLeague's own check reads every script here with `bash -n` (part "build-kit").
