#!/usr/bin/env bash
# Stop Hiro dev processes that can hold Windows file locks on the uv workspace venv.
# Sourced by dev-sync.sh / dev-sync-fast.sh before uv sync and tool reinstalls.

# Stop one channel plugin by short name (e.g. devices, whatsapp).
# Kills the uv-tool .exe shim and any orphaned python/uv -m process for that plugin.
stop_orphaned_hiro_channel_plugin() {
  local short_name="$1"
  local exe="hiro-channel-${short_name}.exe"
  local module="hiro_channel_${short_name}"

  # Installed uv-tool entry point (PyPI / ~/.local/bin).
  MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM "$exe" 2>/dev/null || true

  if [ "${OS:-}" = "Windows_NT" ]; then
    # Dev workspace spawns use `uv run ... python -m hiro_channel_<name>.main`, not the .exe shim.
    # These survive when `hiro stop` finds no server PID but channel plugins are still running.
    powershell.exe -NoProfile -Command \
      "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='uv.exe'\" | Where-Object { \$_.CommandLine -match '$module' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
      2>/dev/null || true
  fi
}

stop_orphaned_hiro_channel_plugins() {
  stop_orphaned_hiro_channel_plugin devices
  stop_orphaned_hiro_channel_plugin whatsapp
}

# Kept for call sites / docs that still name devices explicitly.
stop_orphaned_hiro_channel_devices() {
  stop_orphaned_hiro_channel_plugin devices
}
