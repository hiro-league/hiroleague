#!/usr/bin/env bash
# Run the hiroserver pytest suite with SIGINT ignored, from the workspace root.
#
# Usage (args forward to pytest):
#   ./scripts/run-tests.sh                                  # whole workspace
#   ./scripts/run-tests.sh hirocli/src/hirocli/domain -q    # a subtree
#   ./scripts/run-tests.sh -k preferences
#
# Why ignore SIGINT:
#   On Windows, ML native libs pulled in mid-suite by the knowledge tests
#   (onnxruntime via flashrank / fastembed) install a console CTRL handler when
#   their DLLs load. With an interactive console attached (mintty, and notably
#   Chrome Remote Desktop sessions), a stray console event from that handler is
#   delivered to the process as SIGINT, and pytest-asyncio's per-test asyncio
#   Runner converts it into a spurious KeyboardInterrupt that aborts the run
#   ~86% through. Headless / CI never sees it — no console handler fires there.
#   Ignoring SIGINT makes asyncio skip installing its per-test handler, so the
#   stray signal is dropped and the suite completes. The suite itself is healthy;
#   this only neutralizes the phantom console signal.
#
#   Trade-off: Ctrl-C will NOT stop the run. Use Ctrl-Break, or close the
#   terminal, to abort.
#
# Note: uses `uv run` (auto-syncs the workspace). If a Hiro server is holding the
# venv's Scripts/hiro.exe lock, run `hiro stop` first (or append --no-sync once
# the env is already in sync).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/hiroserver"

exec uv run python -c "import signal, sys, pytest; signal.signal(signal.SIGINT, signal.SIG_IGN); sys.exit(pytest.main(sys.argv[1:]))" "$@"
