#!/usr/bin/env bash
# An app's backend checks, the same on the PC (scripts/check.sh) and in the nightly check (the shared Dockerfile's
# `check` stage), so the two never drift (shared-code plan, step 2). Run from the app's backend/ folder:
#
#   backend-check.sh [ruff] [pyright] [imports] [pytest]
#
# With no checks named it runs those app.env lists (BACKEND_CHECKS), else ruff and pytest:
#   - ruff:    `ruff check src tests`
#   - pyright: the types, as pyproject.toml's [tool.pyright] sets them up
#   - imports: `lint-imports`, the import rules pyproject.toml's [tool.importlinter] gives
#   - pytest:  the tests (their own temporary database, no network: tests/conftest.py), on every core when the app
#              has pytest-xdist, on the PC and in the image alike (every app has it: testing plan, step 2.1)
# In the image: IN_IMAGE=1 runs them on the environment its `uv sync` made (no second sync), and pytest without its
# cache folder.
set -euo pipefail

checks=("$@")
[ ${#checks[@]} -gt 0 ] || read -ra checks <<< "${BACKEND_CHECKS:-ruff pytest}"
run=(uv run)
pytest_args=(-q)
if [ -n "${IN_IMAGE:-}" ]; then
    run+=(--no-sync)
    pytest_args+=(-p no:cacheprovider)
fi
if [[ " ${checks[*]} " == *" pytest "* ]] && "${run[@]}" python -c "import xdist" 2>/dev/null; then
    pytest_args+=(-n auto)
fi

for check in "${checks[@]}"; do
    echo "== backend: $check"
    case "$check" in
        ruff) "${run[@]}" ruff check src tests ;;
        pyright) "${run[@]}" pyright ;;
        imports) "${run[@]}" lint-imports ;;
        pytest) "${run[@]}" pytest "${pytest_args[@]}" ;;
        *) echo "backend-check: no check named '$check' (ruff, pyright, imports, pytest)" >&2; exit 2 ;;
    esac
done
