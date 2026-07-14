#!/usr/bin/env bash
# Faster variant of dev-sync.sh: skips npm install / Svelte build / uv tool installs
# when their inputs (package manifests, source trees, pyproject.toml, etc.) are unchanged.
# Run from the repo root: ./dev-sync-fast.sh
#   --force / -f    bypass all fingerprint caches and reinstall everything.
#   --no-gateway    skip the gateway entirely (no stop / reinstall / start) — server only.
#   --external-ui   skip building the Svelte UI into the server; serve it from a separately
#                   started vite dev server on http://127.0.0.1:5173 (start it yourself).
#   --channels      install the channel-plugin binaries (devices + whatsapp + any future).
#                   Off by default so the fast loop skips them; pass it when you need channels.
# Flags combine, e.g. `./dev-sync-fast.sh --no-gateway --external-ui` for the fastest server-only loop.
# If anything looks off, fall back to ./dev-sync.sh which always does a full rebuild.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/stop-hiro-dev-processes.sh
source "$SCRIPT_DIR/scripts/stop-hiro-dev-processes.sh"

# Knowledge hybrid deps (fastembed → py-rust-stemmers) have cp312 wheels; 3.14 forces a Rust source build on Windows.
HIRO_UV_PYTHON="${HIRO_UV_PYTHON:-3.12}"

export HIRO_ENV="${HIRO_ENV:-dev}"

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

# Flags (any order):
#   --force / -f     bypass all fingerprint caches and reinstall everything.
#   --no-gateway     don't touch the gateway at all (skip its stop / reinstall / start).
#                    Use when you're iterating on the server only and the gateway is
#                    already running (or you don't need it).
#   --external-ui    don't npm-install or build/package the Svelte admin UI into the
#                    server. Instead the UI is served by a separately-started vite dev
#                    server on http://127.0.0.1:5173 (NOT managed by this script — start it
#                    yourself via `npm --prefix admin_frontend run dev`). Sets
#                    HIRO_ADMIN_UI_EXTERNAL=1 so the server serves only /api.
#   --channels       install the channel-plugin tool binaries (devices + whatsapp + any
#                    future plugin listed in CHANNEL_PLUGINS below). Off by default so the
#                    fast loop skips channel installs entirely; the UI's "Install a channel"
#                    button remains the other way to provision a channel on demand.
FORCE_SYNC=0
MANAGE_GATEWAY=1
PACKAGE_UI=1
INSTALL_CHANNELS=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE_SYNC=1 ;;
    --no-gateway) MANAGE_GATEWAY=0 ;;
    --external-ui) PACKAGE_UI=0 ;;
    --channels) INSTALL_CHANNELS=1 ;;
    *) echo "==> Unknown flag '$arg' (supported: --force/-f, --no-gateway, --external-ui, --channels)" >&2; exit 2 ;;
  esac
done

# Channel plugins installed (as editable uv tools) when --channels is passed. Add future
# plugins here as "<tool-name> <path-relative-to-hiroserver>" entries.
CHANNEL_PLUGINS=(
  "hiro-channel-devices channels/hiro-channel-devices"
  "hiro-channel-whatsapp channels/hiro-channel-whatsapp"
)

if [ "$PACKAGE_UI" = "0" ]; then
  export HIRO_ADMIN_UI_EXTERNAL=1
fi

REPO_ROOT="$(pwd)"
CACHE_DIR="$REPO_ROOT/.dev-sync-cache"
mkdir -p "$CACHE_DIR"

# Compute a sha256 fingerprint over a list of files (paths via stdin, NUL-separated).
# Missing files are silently ignored so callers can pass optional inputs.
fingerprint_files() {
  # Sort for deterministic order across filesystems.
  sort -z | xargs -0 -I{} sh -c 'sha256sum "$1" 2>/dev/null' _ {} | sha256sum | awk '{print $1}'
}

# fingerprint_tree DIR [DIR ...] -- hash every regular file under the given dirs.
fingerprint_tree() {
  find "$@" -type f -print0 2>/dev/null | fingerprint_files
}

# cache_check NAME FINGERPRINT -- returns 0 (skip work) when cached value matches.
cache_check() {
  local name="$1" fp="$2"
  [ "$FORCE_SYNC" = "1" ] && return 1
  [ "$(cat "$CACHE_DIR/$name" 2>/dev/null)" = "$fp" ]
}

cache_store() {
  local name="$1" fp="$2"
  echo "$fp" > "$CACHE_DIR/$name"
}

# Stop the server if running so Windows releases the file lock on hiro.exe
echo "==> Stopping Hiro server (if running)..."
hiro stop 2>/dev/null || true
hirocli stop 2>/dev/null || true

echo "==> Stopping channel plugins (if running)..."
stop_orphaned_hiro_channel_plugins

if [ "$MANAGE_GATEWAY" = "1" ]; then
  echo "==> Stopping hirogate (if running)..."
  # Stop via CLI / PID file (same idea as hiro stop), not image-wide taskkill, so Windows releases the lock on hirogate.exe before reinstalling.
  hirogate stop 2>/dev/null || true
  # Remove pre-rename dev binaries that can otherwise hold Windows file locks.
  MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM hirogate.exe 2>/dev/null || true
else
  echo "==> --no-gateway: leaving hirogate untouched"
fi

if [ "$PACKAGE_UI" = "1" ] && [ -f admin_frontend/package.json ]; then
  # npm install: only re-run when manifest/lockfile or node_modules changed.
  npm_fp=$(printf '%s\0' admin_frontend/package.json admin_frontend/package-lock.json | fingerprint_files)
  if cache_check admin_frontend.npm "$npm_fp" && [ -d admin_frontend/node_modules ]; then
    echo "==> admin_frontend deps unchanged, skipping npm install"
  else
    echo "==> Syncing Svelte admin frontend dependencies..."
    npm --prefix admin_frontend install
    cache_store admin_frontend.npm "$npm_fp"
  fi

  # Svelte build: skip when sources + configs unchanged AND output dir exists.
  # Output dir is configured in admin_frontend/svelte.config.js (adapter-static pages).
  SVELTE_OUT_DIR="hiroserver/hirocli/src/hirocli/admin_svelte/static"
  svelte_fp=$( { \
      find admin_frontend/src admin_frontend/static -type f -print0 2>/dev/null; \
      printf '%s\0' \
        admin_frontend/package.json \
        admin_frontend/package-lock.json \
        admin_frontend/svelte.config.js \
        admin_frontend/vite.config.ts \
        admin_frontend/tsconfig.json \
        admin_frontend/components.json; \
    } | fingerprint_files )
  if cache_check admin_frontend.build "$svelte_fp" && [ -d "$SVELTE_OUT_DIR" ] && [ -n "$(ls -A "$SVELTE_OUT_DIR" 2>/dev/null)" ]; then
    echo "==> Svelte admin static assets up to date, skipping build"
  else
    echo "==> Building Svelte admin static assets (fast: no minify / no gzip report)..."
    HIRO_FAST_BUILD=1 npm --prefix admin_frontend run package:python
    cache_store admin_frontend.build "$svelte_fp"
  fi
elif [ "$PACKAGE_UI" = "0" ]; then
  echo "==> --external-ui: skipping npm install + Svelte build; serve UI via vite (npm --prefix admin_frontend run dev) on http://127.0.0.1:5173"
fi

echo "==> Syncing hiroserver workspace dependencies..."
cd hiroserver
uv python install "${HIRO_UV_PYTHON}"   # no-op if already present
uv python pin "${HIRO_UV_PYTHON}"
uv sync

# Always clean up the legacy `hiroleague` meta-tool install (cheap no-op when absent).
uv tool uninstall hiroleague 2>/dev/null || true

# Editable installs only need re-running when the package's pyproject.toml / lockfile
# changes (entry points, deps) or when the launcher shim is missing — Python source
# edits are picked up live thanks to --editable.
# --upgrade refreshes packages in-place without deleting the venv (avoids Windows file-lock errors on Scripts/).
# --force overwrites the entry-point script in ~/.local/bin (needed when the script was left behind by a prior failed install).
# Each top-level binary is installed separately because hirocli no longer bundles hiro-channel-devices
# (the channel is its own distributable package, and the meta-package `hiroleague` is only used by end users).
install_tool_if_changed() {
  local tool_name="$1" tool_path="$2"
  local fp shim cache_key
  cache_key="tool.$tool_name"

  fp=$( { \
      printf '%s\0' "$tool_path/pyproject.toml"; \
      find "$tool_path" -maxdepth 2 -name uv.lock -print0 2>/dev/null; \
    } | fingerprint_files )

  shim="$HOME/.local/bin/$tool_name"
  [ "${OS:-}" = "Windows_NT" ] && shim="$shim.exe"

  if cache_check "$cache_key" "$fp" && [ -e "$shim" ]; then
    echo "==> $tool_name unchanged, skipping reinstall"
    return
  fi

  echo "==> Updating $tool_name tool binary..."
  uv tool uninstall "$tool_name" 2>/dev/null || true
  # uv tool install --editable "$tool_path" --upgrade --force
  uv tool install --editable "$tool_path" --python "${HIRO_UV_PYTHON}" --upgrade --force
  cache_store "$cache_key" "$fp"
}

install_tool_if_changed hirocli hirocli

if [ "$INSTALL_CHANNELS" = "1" ]; then
  for entry in "${CHANNEL_PLUGINS[@]}"; do
    # shellcheck disable=SC2086 # entry is intentionally two space-separated fields
    install_tool_if_changed $entry
  done
else
  echo "==> --channels not passed: skipping channel-plugin installs (devices/whatsapp/…)"
fi

if [ "$MANAGE_GATEWAY" = "1" ]; then
  install_tool_if_changed hirogate gateway
else
  echo "==> --no-gateway: skipping hirogate reinstall"
fi

echo ""
echo "Done. All tool binaries are up to date."
echo "  hiro                 -> run: hiro --help"
if [ "$INSTALL_CHANNELS" = "1" ]; then
  echo "  hiro-channel-devices -> run: hiro-channel-devices --help"
  echo "  hiro-channel-whatsapp (installed via --channels)"
fi
echo "  hirogate             -> run: hirogate --help"

# Foreground gateway in a shell background job so Hiro can keep the terminal (both use -f).
if [ "$MANAGE_GATEWAY" = "1" ]; then
  hirogate start -f &
fi
hiro start --admin -f
