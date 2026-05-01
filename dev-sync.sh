#!/usr/bin/env bash
# Run from the repo root after every git pull or when switching environments: ./dev-sync.sh
# Keeps workspace dependencies and all installed tool binaries in sync.

set -e

export HIRO_ENV="${HIRO_ENV:-dev}"

# Stop the server if running so Windows releases the file lock on hiro.exe
echo "==> Stopping Hiro server (if running)..."
hiro stop 2>/dev/null || true
hirocli stop 2>/dev/null || true

echo "==> Stopping hiro-channel-devices (if running)..."
# Git Bash/MSYS can rewrite /F-style args unless conversion is disabled.
MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM hiro-channel-devices.exe 2>/dev/null || true

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
uv tool uninstall hiroleague 2>/dev/null || true
uv tool uninstall hirocli 2>/dev/null || true
uv tool install --editable hirocli --upgrade --force

echo "==> Updating hiro-channel-devices tool binary..."
uv tool uninstall hiro-channel-devices 2>/dev/null || true
uv tool install --editable channels/hiro-channel-devices --upgrade --force

echo "==> Updating hirogate tool binary..."
uv tool uninstall hirogate 2>/dev/null || true
uv tool install --editable gateway --upgrade --force

echo ""
echo "Done. All tool binaries are up to date."
echo "  hiro                 -> run: hiro --help"
echo "  hiro-channel-devices -> run: hiro-channel-devices --help"
echo "  hirogate             -> run: hirogate --help"

# Foreground gateway in a shell background job so Hiro can keep the terminal (both use -f).
hirogate start -f &
hiro start --admin -f
