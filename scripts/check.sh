#!/usr/bin/env bash
# The one check, run before a commit and by a release (scripts/publish-pypi.sh runs it with --all and stops on a
# failure). Every Hiro repo has the same command, run from its root in Git Bash (hiro-docs
# standards/building-and-releasing.md):
#
#   ./scripts/check.sh          # the parts the change touched
#   ./scripts/check.sh --all    # every part (a release)
#   ./scripts/check.sh --serial # one part at a time
#
# The engine (when a part runs or is skipped, which run side by side, the summary) is build-kit/check-engine.sh, shared
# by every Hiro repo. The parts are HiroLeague's own, in four lanes that run side by side (the text before ":"; parts
# in one lane run in turn), every part even when one fails (exits 1 if any did, naming them):
#   - admin_frontend: generated files (preferences types and the features registry, made from hiroserver's code);
#   - admin_frontend: svelte-check;
#   - admin_frontend: unit tests (vitest);
#   - ui-kit: the shared UI kit's own check (svelte-check, ESLint, vitest);
#   - build-kit: the shared build, check and deploy scripts read by bash (`bash -n`: no syntax error reaches a deploy);
#   - build-kit: hiro-work's tests (build-kit/work: the environments' commands);
#   - hiroserver: ruff, the lint rules every Hiro League repo follows (build-kit/ruff-rules.toml), on every package;
#   - hiroserver: the pytest suite, one part per area of the uv workspace, each with the packages it depends on (the
#     kit needs the SDK, which needs commons), so a change runs only the areas it reaches. The extension kit, the memory
#     library (hiro-memory) and hirocli run on every core with pytest-xdist (scripts/run-tests.sh: Ctrl-C won't stop
#     it, use Ctrl-Break or close the terminal; a running Hiro server may hold the venv's lock: `hiro stop` first).
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
# hiro-work, the environments' commands (build-kit/work): its choices of ports, reserved repos and environment.
part "build-kit: hiro-work tests" "build-kit/work build-kit/check-engine.sh data.toml" \
    bash -c "cd '${REPO_ROOT}/hiroserver' && uv run python -m pytest ../build-kit/work -q -p no:cacheprovider"
# What every area reads: the workspace's own settings and lock, and the runner
ws="hiroserver/pyproject.toml hiroserver/uv.lock scripts/run-tests.sh"
# The lint every Hiro League repo follows (build-kit/ruff-rules.toml, which each app's pyproject extends too), over
# every package of the core
part "hiroserver: ruff" "hiroserver build-kit/ruff-rules.toml"     bash -c "cd '${REPO_ROOT}/hiroserver' && uv run ruff check"
part "hiroserver: commons and SDK tests" "hiroserver/hiro-commons hiroserver/hiro-channel-sdk ${ws}" \
    "${REPO_ROOT}/scripts/run-tests.sh" -q hiro-commons hiro-channel-sdk
part "hiroserver: extension kit tests" "hiroserver/hiro-extension-kit hiroserver/hiro-channel-sdk hiroserver/hiro-commons ${ws}" \
    "${REPO_ROOT}/scripts/run-tests.sh" -q -n auto hiro-extension-kit
part "hiroserver: memory library tests" "hiroserver/hiro-memory hiroserver/hiro-commons ${ws}"     "${REPO_ROOT}/scripts/run-tests.sh" -q -n auto hiro-memory
part "hiroserver: gateway and channels tests" "hiroserver/gateway hiroserver/channels hiroserver/hiro-channel-sdk hiroserver/hiro-commons ${ws}" \
    "${REPO_ROOT}/scripts/run-tests.sh" -q gateway channels
part "hiroserver: hirocli tests" "hiroserver/hirocli hiroserver/hiroleague hiroserver/knowledge hiroserver/hiro-memory hiroserver/hiro-channel-sdk hiroserver/hiro-commons ${ws}" \
    "${REPO_ROOT}/scripts/run-tests.sh" -q -n auto hirocli

# The core's tests run alone: onnxruntime's phantom Ctrl-C reaches every process in the console, and a Node check
# beside them dies of it (and the tests use every core and much of the memory)
CHECK_SOLO_LANES="hiroserver"
check_done
