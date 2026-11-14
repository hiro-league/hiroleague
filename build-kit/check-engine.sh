#!/usr/bin/env bash
# The engine of every Hiro repo's one check, ./scripts/check.sh (hiro-docs standards/building-and-releasing.md): one
# copy, here in HiroLeague (shared-code plan, step 2). A repo's scripts/check.sh says what its parts are and sources
# this for the rest: when a part runs or is skipped, and the summary.
#
#   BASE_BRANCH=origin/dev            # where pushed code is (default origin/main); before sourcing
#   source "<hiroleague>/build-kit/check-engine.sh" "$@"
#   part "frontend: npm run check" "frontend" bash -c "cd '${REPO_ROOT}/frontend' && npm run check"
#   check_done
#
#   ./scripts/check.sh          # the parts the change touched
#   ./scripts/check.sh --all    # every part
#
# (In PowerShell, `bash` is WSL's: run it from Git Bash.) The parts run in turn, even when one fails, and it exits 1 if
# any did, naming them. Without --all a part is skipped when the files it reads are
#   - the same as on BASE_BRANCH (where the merge base is): they passed before they were pushed; or
#   - the same as when this part last passed here (remembered in .git/hiro-check-passed).
# A change in the HiroLeague checkout beside an app (its kits, this folder) doesn't start the app's check. After
# changing a part's command, run it with --all.
#
# What it gives the repo's parts: REPO_ROOT (the repo's root, the current folder), HIROLEAGUE (the HiroLeague checkout
# this file is in) and, when the repo has an app.env, its facts (BACKEND_CHECKS for build-kit/backend-check.sh).
# It installs nothing.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HIROLEAGUE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"
BASE_BRANCH="${BASE_BRANCH:-origin/main}"
if [[ -r app.env ]]; then
    # shellcheck disable=SC1091
    source ./app.env
fi

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

# The summary, and the exit code: 1 if a part failed.
check_done() {
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
    exit 0
}
