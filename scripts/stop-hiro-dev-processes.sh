#!/usr/bin/env bash
# Stop Hiro dev processes that can hold Windows file locks on the uv workspace venv.
# Sourced by dev-sync.sh / dev-sync-fast.sh before uv sync and tool reinstalls.

stop_orphaned_hiro_channel_devices() {
  # Installed uv-tool entry point (PyPI / ~/.local/bin).
  MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM hiro-channel-devices.exe 2>/dev/null || true

  if [ "${OS:-}" = "Windows_NT" ]; then
    # Dev workspace spawns use `uv run ... python -m hiro_channel_devices.main`, not the .exe shim.
    # These survive when `hiro stop` finds no server PID but channel plugins are still running.
    powershell.exe -NoProfile -Command \
      "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='uv.exe'\" | Where-Object { \$_.CommandLine -match 'hiro_channel_devices' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
      2>/dev/null || true
  fi
}
