# hirocli

The desktop server CLI for Hiro League — installs the `hiro` command.

This is the **server** package. It does not pull in the device channel plugin
(`hiro-channel-devices` ships as a separate package and runs as a subprocess).
End users almost always want the umbrella package `hiroleague` instead, which
bundles the full desktop install.

`hirocli` does pull in `hirogate` transitively — its CLI commands
(`hiro gateway start/stop/setup/...`) call directly into `hirogateway.service`
to manage local gateway instances. VPS-only operators should install `hirogate`
alone, not `hirocli`.

## Install matrix

| Use case | Command |
|---|---|
| Full desktop (recommended) | `pip install hiroleague` |
| Server only (no device channel, gateway still pulled in) | `pip install hirocli` |
| VPS gateway only | `pip install hirogate` |

## Installation from source (workspace dev)

```bash
cd hiroserver
uv sync
uv tool install --editable hirocli
```

The workspace member directory is named `hirocli`, and the installed command
is `hiro`.

### After pulling updated code

Run from the repo root every time you pull changes or switch environments:

```bash
./dev-sync.sh
```

`dev-sync.sh` stops the server, syncs dependencies, and reinstalls the
editable tool binaries (`hiro`, `hiro-channel-devices`, `hirogate`) so all
entry points stay current.

## Quick start

```bash
# If you want a named workspace
hiro workspaces create home --set-default
hiro workspaces setup home

# One-time setup with auto-created default workspace
hiro workspaces setup

# If needed on Windows, request UAC to create an elevated scheduled task
hiro workspaces setup --elevated-task

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
hiro workspaces teardown

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
