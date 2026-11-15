# Build kit

The build, check and deploy files every Hiro app shares (HomeHiro, NetHiro, TrainHiro, StudyHiro): one copy, here,
that each app runs from its own folder with its own facts. Before it, each app had its own copy of every file, and
they drifted (shared-code plan, step 2). A change to how apps are built, checked or deployed is one edit here.

| File | What it is | Run by |
|---|---|---|
| `Dockerfile` | The app's image: the UI built and checked, the backend installed and checked, the image that runs | the app's `compose.yaml` (`dockerfile: ../hiroleague/build-kit/Dockerfile`) |
| `deploy.sh` | A deploy on the server: the image built, the database copied, the migrations tried on a copy, the new version started, back to the previous one if it doesn't answer | the app's `deploy.sh` (the post-receive hook after `git push server main`) |
| `nightly-check.sh` | The nightly full check on the server (the Dockerfile's `fullcheck` target), reported to NetHiro's System health | the app's `deploy/nightly-check.sh` (aicam's timers) |
| `check-engine.sh` | The engine of every repo's `./scripts/check.sh`: when a part runs or is skipped (an app's parts name the core files they read, `@hiroleague:...`), lanes side by side (two at once, memory permitting; `--serial`, `--dry-run`), the summary with each part's time | every repo's `scripts/check.sh`, HiroLeague's too |
| `backend-check.sh` | The backend checks (ruff, pyright, import rules, pytest), the same on the PC and in the image | the app's `scripts/check.sh` and the Dockerfile's `check` stage |
| `dev.ps1` | `.\dev` on the PC: packages installed, backend and UI started with live reload (env0's ports) | the app's `dev.ps1` |
| `git-hooks/` | Every Hiro repo's git hooks: `pre-commit` runs `./scripts/check.sh`, `post-checkout` warns when an env0 checkout leaves `dev`/`main` (hiro-docs `standards/workflow.md`, "Enforcement") | git, through each repo's `core.hooksPath`, set by `git-hooks/install.py` |
| `work/hiro_work.py` | `hiro-work`: the environments (env0 to env5), tasks and their claims, servers (and each repo's `.claude/launch.json` for the browser pane), landing (hiro-docs `standards/workflow.md`); its tests beside it | `C:\hiro\bin\hiro-work.cmd`; the core's check runs its tests |
| `work/train.py` | `hiro-work train`: the deploy train (what GitHub and live lack, the pushes, the core's deploy then the apps' side by side through each one's own deploy, a check of each, one report; hiro-docs `standards/building-and-releasing.md`); its tests beside it | `hiro-work train`, when Michel says; the core's check runs its tests |
| `work/ship.py` | The sender: posts `events.jsonl`'s new lines to CodeHiro's Work area with the key in `C:\hiro\secrets\work.key` (hiro-docs `standards/workflow.md`, "Tracking"); its tests beside it | Started by hiro-work whenever it writes an event; the core's check runs its tests |
| `work/check_events.py` | A check's parts as Work events, of the task that claims the repo in its environment (hiro-docs `standards/workflow.md`, "Tracking"); its tests beside it | `check-engine.sh`, as each part starts and ends; writes nothing outside `C:\hiro` |

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

## The git hooks

`git-hooks/install.py` points every repo's `core.hooksPath` at env0's copy of `git-hooks/`
(`C:/hiro/env0/hiroleague/build-kit/git-hooks`, the core folder every repo reads the build kit from). env1 to env5 are
worktrees of env0's repos and share their config, so one setting per repo covers every environment. `hiro-work init`
runs it when it makes an environment; by hand, `--check` lists which repos have them and `--remove` takes them off.

- **`pre-commit`** runs the repo's own `.git/hooks/pre-commit` first, when it has one (the core's pre-commit framework
  hook), then `./scripts/check.sh` when the repo has one (aicam and hiro-docs don't). Parts that passed on these files
  are skipped, so a checked change commits in seconds. `git commit --no-verify` skips it, only when Michel asks
  (`hiro-work park` uses it for its WIP commit).
- **`post-checkout`** warns when a branch checkout in `C:\hiro\env0` leaves the repo's main branch.
- **No `pre-push` yet:** the deploy train (the work-flow plan's step 4) will own pushes.
- The check reads the working tree, not the staged files: a commit that stages only part of a file is checked as the
  whole file stands.
