#!/usr/bin/env bash
# Run from the repo root after every git pull or when switching environments: ./dev-sync.sh
# Keeps workspace dependencies and all installed tool binaries in sync.

set -e

# Stop the server if running so Windows releases the file lock on hiro.exe
echo "==> Stopping Hiro server (if running)..."
hiro stop 2>/dev/null || true
hirocli stop 2>/dev/null || true

echo "==> Stopping hiro-channel-devices (if running)..."
# Git Bash/MSYS can rewrite /F-style args unless conversion is disabled.
MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM hiro-channel-devices.exe 2>/dev/null || true

echo "==> Stopping hirogateway (if running)..."
# Stop via CLI / PID file (same idea as hiro stop), not image-wide taskkill, so Windows releases the lock on hirogateway.exe before reinstalling.
hirogateway stop 2>/dev/null || true

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
# hiro-channel-devices is bundled as a script in hiroleague's pyproject.toml, so this single install covers both binaries.
uv tool uninstall hirocli 2>/dev/null || true
uv tool install --editable hirocli --upgrade --force

echo "==> Updating hirogateway tool binary..."
uv tool install --editable gateway --upgrade --force

echo ""
echo "Done. All tool binaries are up to date."
echo "  hiro                 -> run: hiro --help"
echo "  hiro-channel-devices -> run: hiro-channel-devices --help  (bundled with hiroleague)"
echo "  hirogateway          -> run: hirogateway --help"

# Foreground gateway in a shell background job so Hiro can keep the terminal (both use -f).
hirogateway start -f &
hiro start --admin -f
