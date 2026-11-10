#!/usr/bin/env bash
# The one check, run before a commit and by a release (scripts/publish-pypi.sh runs it with --all and stops on a
# failure). Every Hiro repo has the same command, run from its root in Git Bash (hiro-docs
# standards/building-and-releasing.md):
#
#   ./scripts/check.sh          # the parts the change touched
#   ./scripts/check.sh --all    # every part (a release)
#
# The parts, run in turn even when one fails (exits 1 if any did, naming them):
#   - admin_frontend: generated files (preferences types and the features registry, made from hiroserver's code);
#   - admin_frontend: svelte-check;
#   - admin_frontend: unit tests (vitest);
#   - hiroserver: the whole pytest suite over the uv workspace (scripts/run-tests.sh: Ctrl-C won't stop it, use
#     Ctrl-Break or close the terminal; a running Hiro server may hold the venv's lock: `hiro stop` first).
#
# Without --all a part is skipped when the files it reads are
#   - the same as on GitHub's dev (origin/dev, where the merge base is): they passed before they were pushed; or
#   - the same as when this part last passed here (remembered in .git/hiro-check-passed).
# Files nothing here checks (device_apps, docs, *.md outside these folders...) never start a part. After changing a
# part's command in this script, run it with --all.
#
# It installs nothing: admin_frontend's packages come from `npm install` (first-time setup); `uv run` keeps the
# Python workspace in sync by itself.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"
BASE_BRANCH="origin/dev"

all=false
for arg in "$@"; do
    case "$arg" in
        --all) all=true ;;
        *) echo "usage: ./scripts/check.sh [--all]" >&2; exit 2 ;;
    esac
done

# The files as they are now (committed or not, untracked too, .gitignore respected), as a git tree: a temporary
# copy of the index, so the real one (what is staged) is untouched.
tmp_index="$(mktemp)"
cp "$(git rev-parse --git-path index)" "$tmp_index"
GIT_INDEX_FILE="$tmp_index" git add -A .
now_tree="$(GIT_INDEX_FILE="$tmp_index" git write-tree)"
rm -f "$tmp_index"
base="$(git merge-base HEAD "$BASE_BRANCH" 2>/dev/null || true)"
stamp="$(git rev-parse --git-path hiro-check-passed)"

# One id for what PATHS hold in TREE (a tree or a commit).
fingerprint() {
    local tree="$1" p; shift
    for p in "$@"; do
        git rev-parse -q --verify "${tree}:${p}" 2>/dev/null || echo "none:${p}"
    done | git hash-object --stdin
}

failed=()
ran=()
skipped=()

# part NAME "PATHS IT READS" COMMAND...
part() {
    local name="$1" inputs="$2"; shift 2
    local -a paths
    read -ra paths <<< "$inputs"
    local now
    now="$(fingerprint "$now_tree" "${paths[@]}")"
    echo ""
    echo "==> ${name}"
    if ! $all; then
        if [[ -n "$base" && "$now" == "$(fingerprint "$base" "${paths[@]}")" ]]; then
            echo "    skipped: its files are the same as on ${BASE_BRANCH}"
            skipped+=("${name}")
            return
        fi
        if grep -qxF "${name}"$'\t'"${now}" "$stamp" 2>/dev/null; then
            echo "    skipped: it already passed on these exact files"
            skipped+=("${name}")
            return
        fi
    fi
    ran+=("${name}")
    if "$@"; then
        # Remember the pass (the last 50, so undoing a change doesn't re-run what passed on that code).
        { grep -vxF "${name}"$'\t'"${now}" "$stamp" 2>/dev/null; printf '%s\t%s\n' "${name}" "${now}"; } | tail -n 50 > "${stamp}.tmp"
        mv "${stamp}.tmp" "$stamp"
    else
        failed+=("${name}")
    fi
}

part "admin_frontend: generated files" "admin_frontend hiroserver" \
    bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run check:prefs-types && npm run check:features"
part "admin_frontend: svelte-check" "admin_frontend" \
    bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run check:svelte"
part "admin_frontend: unit tests" "admin_frontend" \
    bash -c "cd '${REPO_ROOT}/admin_frontend' && npm run test:unit"
part "hiroserver: pytest" "hiroserver scripts/run-tests.sh" \
    "${REPO_ROOT}/scripts/run-tests.sh"

echo ""
[[ ${#skipped[@]} -gt 0 ]] && echo "check: skipped (unchanged): ${skipped[*]}"
if [[ ${#failed[@]} -gt 0 ]]; then
    echo "check: FAILED:"
    printf '  - %s\n' "${failed[@]}"
    exit 1
fi
if [[ ${#ran[@]} -eq 0 ]]; then
    echo "check: nothing to check (use --all to run every part)"
else
    echo "check: all passed"
fi
