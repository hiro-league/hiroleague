# Hiro League

Desktop server CLI with WebSocket gateway connectivity.

## Installation from PyPI

```bash
pip install hiroleague
```

This installs the `hiro` command.

## Installation from source

```bash
cd hiroserver
uv sync
uv tool install --editable hirocli
```

The workspace member directory is still named `hirocli`, but the installed command is `hiro`.

### After pulling updated code

Run from the repo root every time you pull changes or switch environments:

```bash
./dev-sync.sh
```

`dev-sync.sh` stops the server, syncs dependencies, and reinstalls the editable tool so the `hiro` entry point stays current.

## Quick start

```bash
# If you want a named workspace
hiro workspace create home --set-default
hiro workspace setup home

# One-time setup with auto-created default workspace
hiro workspace setup

# If needed on Windows, request UAC to create an elevated scheduled task
hiro workspace setup --elevated-task

# Manual start / stop
hiro start
hiro stop

# Start in foreground with live log output
hiro start --foreground
hiro start -f

# Check status
hiro status

# Device pairing helpers
hiro device add
hiro device list
hiro device revoke <device_id>

# Cleanup auto-start and running process
hiro workspace teardown

# Full uninstall flow
hiro uninstall
```

## Runtime data

Runtime data is stored in the platform app data directory for `hiro`:

- `config.json` — device id, gateway URL, ports, and logging settings
- `state.json` — live WebSocket connection state
- `hiro.pid` — PID of the running server process
- `master_key.pem` — desktop Ed25519 master key used for gateway authentication
- `pairing_session.json` — current active pairing code and expiry
- `workspace.db` — workspace SQLite data
- `logs/server.log` — server log
- `logs/plugin-<name>.log` — one log file per channel plugin subprocess

## HTTP API

When running, the server exposes a local HTTP API at the configured HTTP port:

- `GET /status` — server and gateway connection status
- `GET /channels` — connected channel plugins
- `GET /tools` — registered tool schemas
- `POST /invoke` — execute a registered tool
