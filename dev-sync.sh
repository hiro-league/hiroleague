#!/usr/bin/env bash
# Run from the repo root after every git pull or when switching environments: ./dev-sync.sh
# Keeps workspace dependencies and all installed tool binaries in sync.
#   --channels   also install the channel-plugin binaries (devices + whatsapp + any future
#                plugin in CHANNEL_PLUGINS). Off by default; pass it when you need channels.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/stop-hiro-dev-processes.sh
source "$SCRIPT_DIR/scripts/stop-hiro-dev-processes.sh"

export HIRO_ENV="${HIRO_ENV:-dev}"

# Flags: --channels installs the channel-plugin tool binaries (off by default).
INSTALL_CHANNELS=0
for arg in "$@"; do
  case "$arg" in
    --channels) INSTALL_CHANNELS=1 ;;
    *) echo "==> Unknown flag '$arg' (supported: --channels)" >&2; exit 2 ;;
  esac
done

# Channel plugins installed when --channels is passed. Add future plugins here as
# "<tool-name> <path-relative-to-hiroserver>" entries.
CHANNEL_PLUGINS=(
  "hiro-channel-devices channels/hiro-channel-devices"
  "hiro-channel-whatsapp channels/hiro-channel-whatsapp"
)

# Graph deep-trace sidecars are now a workspace preference, not an env var: set
# Settings → Graph engine → Graph observability = "Trace" (or graph.observability="trace" in
# preferences.json). Replaces the former HIRO_GRAPH_TRACE_RETRIEVAL / HIRO_GRAPH_TRACE_INGEST.

# Some endpoint-security / TLS-inspection tools inject SSLKEYLOGFILE pointing at an
# unwritable virtual file (e.g. \\?\Volume{GUID}\virtual_file.log). Python's
# ssl.create_default_context() then raises PermissionError as soon as any TLS client
# is imported (ollama -> httpx), crashing the server on start. Drop the var for the
# launched dev processes when its target is not writable.
if [ -n "${SSLKEYLOGFILE:-}" ] && ! ( : >> "$SSLKEYLOGFILE" ) 2>/dev/null; then
  echo "==> SSLKEYLOGFILE points at an unwritable path ('$SSLKEYLOGFILE'); clearing it for this run."
  unset SSLKEYLOGFILE
fi

# Stop the server if running so Windows releases the file lock on hiro.exe
echo "==> Stopping Hiro server (if running)..."
hiro stop 2>/dev/null || true
hirocli stop 2>/dev/null || true

echo "==> Stopping channel plugins (if running)..."
stop_orphaned_hiro_channel_plugins

echo "==> Stopping hirogate (if running)..."
# Stop via CLI / PID file (same idea as hiro stop), not image-wide taskkill, so Windows releases the lock on hirogate.exe before reinstalling.
hirogate stop 2>/dev/null || true
# Remove pre-rename dev binaries that can otherwise hold Windows file locks.
MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM hirogate.exe 2>/dev/null || true

if [ -f admin_frontend/package.json ]; then
  echo "==> Syncing Svelte admin frontend dependencies..."
  npm --prefix admin_frontend install

  echo "==> Building Svelte admin static assets..."
  npm --prefix admin_frontend run package:python
fi

echo "==> Syncing hiroserver workspace dependencies..."
cd hiroserver
uv sync

echo "==> Updating Hiro tool binary..."
# --upgrade refreshes packages in-place without deleting the venv (avoids Windows file-lock errors on Scripts/).
# --force overwrites the entry-point script in ~/.local/bin (needed when the script was left behind by a prior failed install).
# Each top-level binary is installed separately because hirocli no longer bundles hiro-channel-devices
# (the channel is its own distributable package, and the meta-package `hiroleague` is only used by end users).
# Also clean up any older `hiroleague` editable tool install left over from before the package split.
# Pin tool installs to the project Python (matches dev-sync-fast.sh and hiroserver/.python-version).
# Unlike `uv sync`, `uv tool install` ignores .python-version and would otherwise grab uv's default
# managed interpreter (e.g. 3.14), for which kuzu has no prebuilt wheel — forcing a from-source build
# that needs cmake/make. Override with HIRO_UV_PYTHON if needed.
HIRO_UV_PYTHON="${HIRO_UV_PYTHON:-3.12}"
uv tool uninstall hiroleague 2>/dev/null || true
uv tool uninstall hirocli 2>/dev/null || true
uv tool install --editable hirocli --upgrade --force --python "$HIRO_UV_PYTHON"

if [ "$INSTALL_CHANNELS" = "1" ]; then
  for entry in "${CHANNEL_PLUGINS[@]}"; do
    # entry is "<tool-name> <path>" (relative to hiroserver, this script's cwd here).
    read -r tool_name tool_path <<< "$entry"
    echo "==> Updating $tool_name tool binary..."
    uv tool uninstall "$tool_name" 2>/dev/null || true
    uv tool install --editable "$tool_path" --upgrade --force --python "$HIRO_UV_PYTHON"
  done
else
  echo "==> --channels not passed: skipping channel-plugin installs (devices/whatsapp/…)"
fi

echo "==> Updating hirogate tool binary..."
uv tool uninstall hirogate 2>/dev/null || true
uv tool install --editable gateway --upgrade --force --python "$HIRO_UV_PYTHON"

echo ""
echo "Done. All tool binaries are up to date."
echo "  hiro                 -> run: hiro --help"
if [ "$INSTALL_CHANNELS" = "1" ]; then
  echo "  hiro-channel-devices -> run: hiro-channel-devices --help"
  echo "  hiro-channel-whatsapp (installed via --channels)"
fi
echo "  hirogate             -> run: hirogate --help"

# Foreground gateway in a shell background job so Hiro can keep the terminal (both use -f).
hirogate start -f &
hiro start --admin -f
