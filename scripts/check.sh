#!/usr/bin/env bash
# The one check: every check this repo has, run before a commit and by a release (scripts/publish-pypi.sh runs it
# first and stops on a failure). Every Hiro repo has the same command, run from its root in Git Bash
# (hiro-docs standards/building-and-releasing.md):
#
#   ./scripts/check.sh
#
# It runs, in turn, even when one fails, and exits 1 if any did:
#   - admin_frontend: `npm run check` (generated types, features registry, svelte-check) and `npm run test:unit`;
#   - hiroserver: the whole pytest suite over the uv workspace (scripts/run-tests.sh: Ctrl-C won't stop it, use
#     Ctrl-Break or close the terminal; a running Hiro server may hold the venv's lock: `hiro stop` first).
#
# It installs nothing: admin_frontend's packages come from `npm install` (first-time setup); `uv run` keeps the
# Python workspace in sync by itself.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
failed=()

step() {
    local name="$1"; shift
    echo ""
    echo "==> ${name}"
    if ! "$@"; then
        failed+=("${name}")
    fi
}

step "admin_frontend: npm run check" bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run check"
step "admin_frontend: npm run test:unit" bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run test:unit"
step "hiroserver: pytest (scripts/run-tests.sh)" "${REPO_ROOT}/scripts/run-tests.sh"

echo ""
if [[ ${#failed[@]} -gt 0 ]]; then
    echo "check: FAILED:"
    printf '  - %s\n' "${failed[@]}"
    exit 1
fi
echo "check: all passed"
