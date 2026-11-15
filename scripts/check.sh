#!/usr/bin/env bash
# The one check, run before a commit and by a release (scripts/publish-pypi.sh runs it with --all and stops on a
# failure). Every Hiro repo has the same command, run from its root in Git Bash (hiro-docs
# standards/building-and-releasing.md):
#
#   ./scripts/check.sh          # the parts the change touched
#   ./scripts/check.sh --all    # every part (a release)
#
# The engine (when a part runs or is skipped, the summary) is build-kit/check-engine.sh, shared by every Hiro repo; the
# parts are HiroLeague's own, run in turn even when one fails (exits 1 if any did, naming them):
#   - admin_frontend: generated files (preferences types and the features registry, made from hiroserver's code);
#   - admin_frontend: svelte-check;
#   - admin_frontend: unit tests (vitest);
#   - ui-kit: the shared UI kit's own check (svelte-check, ESLint, vitest);
#   - build-kit: the shared build, check and deploy scripts read by bash (`bash -n`: no syntax error reaches a deploy);
#   - hiroserver: the whole pytest suite over the uv workspace, on every core with pytest-xdist (scripts/run-tests.sh:
#     Ctrl-C won't stop it, use Ctrl-Break or close the terminal; a running Hiro server may hold the venv's lock:
#     `hiro stop` first).
#
# Without --all a part is skipped when its files are the same as on GitHub's dev (origin/dev), or as when it last
# passed here. Files nothing here checks (device_apps, docs, *.md outside these folders...) never start a part.
#
# It installs nothing: admin_frontend's and ui-kit's packages come from `npm install` in each (first-time setup); `uv run` keeps the
# Python workspace in sync by itself.

BASE_BRANCH="origin/dev"
# shellcheck source=../build-kit/check-engine.sh
source "$(dirname "${BASH_SOURCE[0]}")/../build-kit/check-engine.sh" "$@"

part "admin_frontend: generated files" "admin_frontend hiroserver" \
    bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run check:prefs-types && npm run check:features"
part "admin_frontend: svelte-check" "admin_frontend" \
    bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run check:svelte"
part "admin_frontend: unit tests" "admin_frontend" \
    bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run test:unit"
# The shared UI kit (@hiroleague/ui): its own svelte-check, ESLint and tests. Every app reads ui-kit/src/lib as source,
# so a change there is checked here before it reaches them.
part "ui-kit: check" "ui-kit" \
    bash -c "cd '${REPO_ROOT}/ui-kit' && npm run check"
# The apps' deploy, nightly check and check engine run from here on the server and the PC: a syntax error would stop
# every app's deploy.
part "build-kit: bash -n" "build-kit" \
    bash -c "cd '${REPO_ROOT}/build-kit' && for f in *.sh; do bash -n \"\$f\" || exit 1; done"
part "hiroserver: pytest" "hiroserver scripts/run-tests.sh" \
    "${REPO_ROOT}/scripts/run-tests.sh" -n auto

check_done
