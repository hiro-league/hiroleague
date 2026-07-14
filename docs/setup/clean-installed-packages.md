# Clean installed Hiro packages

Use this before a fresh local/PyPI smoke install when you want no leftover
`hiro*` packages or CLI shims from earlier `uv tool`, `pip`, `pipx`, or wheel
installs.

This does **not** remove workspace data (`~/hiro/` / configured workspaces) or
the repo’s `hiroserver/.venv` used for day-to-day development. It only clears
**installed package / tool environments**.

## Packages and CLIs to clear

| Distribution name | Typical CLI / entry point |
| --- | --- |
| `hiroleague` | `hiro`, `hirogate`, `hiro-channel-devices` (meta-package re-exports) |
| `hirocli` | `hiro` |
| `hirogate` | `hirogate` |
| `hirogateway` (legacy) | `hirogateway` |
| `hiro-commons` | (library) |
| `hiro-channel-sdk` | (library) |
| `hiro-channel-devices` | `hiro-channel-devices` |
| `hiro-channel-whatsapp` | `hiro-channel-whatsapp` |
| `hiro-channel-echo` | `hiro-channel-echo` |

Installs may have come from PyPI, a local wheel, or an editable checkout.

## 1. Stop running processes

File locks on Windows will block uninstalls if Hiro is still running:

```bash
hiro stop 2>/dev/null || true
hirogate stop 2>/dev/null || true

# Optional: kill leftover channel plugin processes (Windows)
# from repo root:
#   source scripts/stop-hiro-dev-processes.sh
#   stop_orphaned_hiro_channel_plugins
```

## 2. Inspect what is still installed

```bash
# uv user tools (most common for hiroleague / hirocli / hirogate / channels)
uv tool list

# Packages in the active / project venv
uv pip list | grep -iE '^hiro'

# pipx (only if you ever used it)
pipx list 2>/dev/null | grep -i hiro || true

# Which binary would run?
command -v hiro hirogate hiro-channel-devices hiro-channel-whatsapp hiro-channel-echo 2>/dev/null
where.exe hiro 2>/dev/null
where.exe hirogate 2>/dev/null
```

## 3. Uninstall with uv (primary)

uv has two uninstall surfaces — use both if you are unsure how things were installed.

### A. `uv tool uninstall` — user tools / CLIs

This is what `uv tool install hiroleague` (and `dev-sync.sh`) creates. Removes the
isolated tool env **and** the `hiro` / `hirogate` / channel shims.

**Important:** uninstall by the **tool package name** from `uv tool list`
(left column), not the CLI entry point (`hiro` is an entry point; the tool was
usually `hirocli` or `hiroleague`). Also, **one missing name aborts the whole
command** — nothing is removed. Prefer one name per call (or only names that
appear in `uv tool list`):

```bash
uv tool list   # see exact names installed on this machine

uv tool uninstall hiroleague 2>/dev/null || true
uv tool uninstall hirocli 2>/dev/null || true
uv tool uninstall hirogate 2>/dev/null || true
uv tool uninstall hirogateway 2>/dev/null || true   # legacy package name
uv tool uninstall hiro-channel-devices 2>/dev/null || true
uv tool uninstall hiro-channel-whatsapp 2>/dev/null || true
uv tool uninstall hiro-channel-echo 2>/dev/null || true
```

Example for a machine that currently lists `hirogate`, `hirogateway`, and the
channel tools (no `hirocli` / `hiroleague`):

```bash
uv tool uninstall hirogate hirogateway hiro-channel-devices hiro-channel-whatsapp
```

Nuclear option (removes **all** uv tools on the machine, not only Hiro):

```bash
# uv tool uninstall --all
```

Re-check: `uv tool list` should no longer show any `hiro*` tools.
### B. `uv pip uninstall` — packages inside a venv

Use this for installs done with `uv pip install`, `pip install`, or a local
wheel into an activated / project env (e.g. `.smoke-runtime`):

```bash
uv pip uninstall \
  hiroleague \
  hirocli \
  hirogate \
  hiro-commons \
  hiro-channel-sdk \
  hiro-channel-devices \
  hiro-channel-whatsapp \
  hiro-channel-echo
```

Point at a specific interpreter if needed:

```bash
uv pip uninstall --python .smoke-runtime/Scripts/python.exe \
  hiroleague hirocli hirogate hiro-commons hiro-channel-sdk \
  hiro-channel-devices hiro-channel-whatsapp hiro-channel-echo
```

Optional: drop cached wheels so a reinstall cannot pick a stale build:

```bash
uv cache clean hiroleague hirocli hirogate hiro-commons \
  hiro-channel-sdk hiro-channel-devices hiro-channel-whatsapp hiro-channel-echo
```

Repeat `uv pip uninstall` for **each** disposable venv, or delete the venv
entirely (next section).

## 4. Uninstall pipx apps (if any)

Only needed if `pipx list` showed Hiro packages:

```bash
pipx uninstall hiroleague 2>/dev/null || true
pipx uninstall hirocli 2>/dev/null || true
pipx uninstall hirogate 2>/dev/null || true
pipx uninstall hiro-channel-devices 2>/dev/null || true
pipx uninstall hiro-channel-whatsapp 2>/dev/null || true
pipx uninstall hiro-channel-echo 2>/dev/null || true
```

## 5. Optional: delete disposable test venvs

If you created a one-off env for wheel smoke tests, remove it instead of
uninstalling package-by-package:

```bash
# from repo root — example from local-package-smoke-test.md
deactivate 2>/dev/null || true
rm -rf .smoke-runtime
```

Do **not** delete `hiroserver/.venv` unless you intentionally want a full
workspace re-sync (`uv sync` / `./dev-sync.sh`).

## 6. Leftover CLI shims on PATH

After uninstall, confirm no stale scripts remain:

```bash
command -v hiro || echo "hiro: clean"
command -v hirogate || echo "hirogate: clean"
command -v hiro-channel-devices || echo "hiro-channel-devices: clean"
command -v hiro-channel-whatsapp || echo "hiro-channel-whatsapp: clean"

where.exe hiro 2>/dev/null || true
where.exe hirogate 2>/dev/null || true
```

Typical leftover locations:

- uv tools: `~/.local/bin/` (and uv’s tool envs under its data dir)
- Windows user Scripts: `%APPDATA%\Python\Python3x\Scripts\` or a venv’s `Scripts\`
- pipx: pipx’s bin directory

If `where.exe` / `command -v` still finds a shim after uninstall, delete that
orphan file manually (or reinstall over it with `--force` when you install the
new test package).

## 7. Verify clean

```bash
uv tool list | grep -i hiro || echo "uv tools: no hiro*"
uv pip list 2>/dev/null | grep -iE '^hiro' || echo "uv pip: no hiro*"
pipx list 2>/dev/null | grep -i hiro || echo "pipx: no hiro*"
```

You are clean when those checks print no Hiro packages and the CLIs above are
missing (or only resolve to something you still intend to keep, e.g. a fresh
editable `uv tool install` from the repo).

## Next step

Rebuild and install into a disposable env — see
[local-package-smoke-test.md](./local-package-smoke-test.md).
