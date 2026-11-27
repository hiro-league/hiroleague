#!/usr/bin/env bash
# The fresh-install test's package cache on Simone, started by fresh.py before a run (never a system service):
#   - PyPI through proxpi (port 3141): every package, kept in ~/hiro-fresh/cache/pypi
#   - uv's Pythons through python_mirror.py (port 3142): kept in ~/hiro-fresh/cache/python
# A file is downloaded from the internet the first time a machine asks for it, then served from Simone's disk.
# proxpi lives in its own tool folder (~/hiro-fresh/tools), never among the account's uv tools (the live WhatsApp
# channel's). Nothing needs sudo. Already running: nothing is done.
#
#     cache-start.sh
set -euo pipefail
ROOT="$HOME/hiro-fresh"
CACHE="$ROOT/cache"
PYPI_PORT=3141
PYTHON_PORT=3142
mkdir -p "$CACHE/pypi" "$CACHE/python"

listening() { ss -ltn "( sport = :$1 )" | grep -q LISTEN; }

if ! listening "$PYPI_PORT"; then
  if [ ! -x "$ROOT/bin/gunicorn" ]; then
    UV_TOOL_DIR="$ROOT/tools" UV_TOOL_BIN_DIR="$ROOT/bin" \
      uv tool install --quiet "gunicorn==27.0.1" --with "proxpi==1.3.1" --python 3.12
  fi
  # proxpi's defaults lose the files at a restart (a temporary folder) and keep 5 GB; a first download is waited
  # for (the default sends a machine to PyPI after 0.9 s, so a big file would come from the internet twice)
  PROXPI_CACHE_DIR="$CACHE/pypi" PROXPI_CACHE_SIZE=$((30 * 1024 * 1024 * 1024)) PROXPI_DOWNLOAD_TIMEOUT=1800 \
    nohup "$ROOT/bin/gunicorn" --bind "0.0.0.0:$PYPI_PORT" --threads 8 --timeout 1900 proxpi.server:app \
    >>"$CACHE/pypi.log" 2>&1 &
fi
if ! listening "$PYTHON_PORT"; then
  nohup python3 "$ROOT/python_mirror.py" "$CACHE/python" "$PYTHON_PORT" >>"$CACHE/python.log" 2>&1 &
fi
for _ in $(seq 1 30); do listening "$PYPI_PORT" && listening "$PYTHON_PORT" && break; sleep 1; done
listening "$PYPI_PORT" && listening "$PYTHON_PORT" || { echo "the cache didn't start: see $CACHE/*.log" >&2; exit 1; }
echo "cache: PyPI on :$PYPI_PORT, Pythons on :$PYTHON_PORT ($(du -sh "$CACHE" | cut -f1) kept)"
