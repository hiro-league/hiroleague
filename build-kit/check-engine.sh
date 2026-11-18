#!/usr/bin/env bash
# The engine of every Hiro repo's one check, ./scripts/check.sh (hiro-docs standards/building-and-releasing.md): one
# copy, here in HiroLeague. A repo's scripts/check.sh says what its parts are and sources this for the rest: when a
# part runs or is skipped, which parts run side by side, and the summary.
#
#   BASE_BRANCH=origin/dev            # where pushed code is (default origin/main); before sourcing
#   source "<hiroleague>/build-kit/check-engine.sh" "$@"
#   part "frontend: npm run check" "frontend @hiroleague:ui-kit/src/lib" bash -c "cd '${REPO_ROOT}/frontend' && ..."
#   check_done
#
#   ./scripts/check.sh            # the parts the change touched
#   ./scripts/check.sh --all      # every part
#   ./scripts/check.sh --serial   # one part at a time (CHECK_JOBS=1)
#   ./scripts/check.sh --dry-run  # which parts would run, and why the others are skipped; runs nothing
#
# (In PowerShell, `bash` is WSL's: run it from Git Bash.)
#
# Which parts run: without --all a part is skipped when the files it reads are
#   - the same as on BASE_BRANCH (where the merge base is): they passed before they were pushed; or
#   - the same as when this part last passed here (remembered in .git/hiro-check-passed).
# A part's files may be in the HiroLeague checkout beside the repo: "@hiroleague:<path>" (the kits, the SDK, the build
# kit). Then a change there starts exactly the app parts that read it; their "same as pushed" also needs the core's
# files to be the same as on the core's origin/dev.
#
# A part can leave a folder out of what it reads: "-<path>" (or "-@hiroleague:<path>") after the path it sits under, e.g.
# "@hiroleague:ui-kit/src/lib -@hiroleague:ui-kit/src/lib/memory" (an app's frontend, when no page imports memory/).
#
# Every repo with a copy list (data.toml: what a copy of its data holds, hiro-docs standards/workflow.md) gets one more
# part, "copy list", queued here: build-kit/work/copylist.py reads and checks it, as hiro-work will, so a list hiro-work
# can't read fails at the commit, not at a later start.
#
# A repo can name lanes that must run alone (CHECK_SOLO_LANES, set before check_done): the core's tests, whose
# onnxruntime sends a phantom Ctrl-C to the whole console that kills a Node check running beside them.
#
# Side by side: the text before a part's ":" is its lane ("frontend", "backend", "hiroserver"...). Parts in one lane
# run in turn (they share a folder); lanes run side by side, at most CHECK_JOBS at once (default 2), and a lane beyond
# the first starts only while the PC has CHECK_MIN_FREE_GB of free memory (default 4). Measured on Michel's PC: two
# lanes are about 12% faster than one at a time; three in the core (its tests on every core beside two Node checks)
# ran it out of memory and Node died with no message. Each part's output is printed in one block when it ends, with
# its time. Every part runs even when another fails; the exit is 1 if any failed, naming them.
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
dry_run=false
max_jobs="${CHECK_JOBS:-2}"
min_free_kb=$(( ${CHECK_MIN_FREE_GB:-4} * 1024 * 1024 ))
for arg in "$@"; do
    case "$arg" in
        --all) all=true ;;
        --serial) max_jobs=1 ;;
        --dry-run) dry_run=true ;;
        *) echo "usage: ./scripts/check.sh [--all] [--serial] [--dry-run]" >&2; exit 2 ;;
    esac
done

# Free memory in kB (Git Bash and Linux expose /proc/meminfo); unknown = plenty
free_kb() {
    awk '/^MemAvailable:/ {print $2; f=1; exit} /^MemFree:/ {m=$2} END {if (!f) print (m ? m : 999999999)}' \
        /proc/meminfo 2>/dev/null || echo 999999999
}

# The files as they are now (committed or not, untracked too, .gitignore respected), as a git tree: a temporary
# copy of the index, so the real one (what is staged) is untouched.
tree_now() {
    local dir="$1" tmp_index tree
    tmp_index="$(mktemp)"
    cp "$(git -C "$dir" rev-parse --path-format=absolute --git-path index)" "$tmp_index"
    # (git's line-ending warnings about the working copy are noise here: only the tree is read)
    GIT_INDEX_FILE="$tmp_index" git -c core.safecrlf=false -C "$dir" add -A . 2>/dev/null
    tree="$(GIT_INDEX_FILE="$tmp_index" git -C "$dir" write-tree)"
    rm -f "$tmp_index"
    echo "$tree"
}
now_tree="$(tree_now "${REPO_ROOT}")"
base="$(git merge-base HEAD "$BASE_BRANCH" 2>/dev/null || true)"
stamp="$(git rev-parse --git-path hiro-check-passed)"
# The core's side, worked out only when a part reads core files from another repo
core_now="" core_base=""
core_trees() {
    [[ -n "$core_now" ]] && return
    core_now="$(tree_now "${HIROLEAGUE}")"
    core_base="$(git -C "${HIROLEAGUE}" merge-base HEAD origin/dev 2>/dev/null || true)"
}

# One id for what PATHS hold in TREE (a tree or a commit) of the repo in DIR, leaving out the folders in EXCLUDED
# (space-separated; "-<path>" in a part's list). A path with an excluded folder under it is the hash of its files'
# ids and names minus that folder's; a path with none is its tree id, as before.
fingerprint() {
    local dir="$1" tree="$2" excluded="$3" p e; shift 3
    for p in "$@"; do
        local under=""
        for e in $excluded; do [[ "$e" == "$p"/* ]] && under+="${under:+ }$e"; done
        if [[ -z "$under" ]]; then
            git -C "$dir" rev-parse -q --verify "${tree}:${p}" 2>/dev/null || echo "none:${p}"
        else
            git -C "$dir" ls-tree -r "$tree" -- "$p" 2>/dev/null \
                | awk -F'\t' -v under="$under" 'BEGIN { n = split(under, u, " ") }
                    { for (i = 1; i <= n; i++) if (index($2, u[i] "/") == 1) next; print }' \
                | git hash-object --stdin
        fi
    done | git hash-object --stdin
}

failed=()
skipped=()
q_names=()
q_lanes=()
q_cmds=()
q_ids=()

# part NAME "PATHS IT READS" COMMAND...   (decides now whether it runs; check_done runs it)
part() {
    local name="$1" inputs="$2"; shift 2
    local -a paths own=() core=()
    local own_out="" core_out=""
    read -ra paths <<< "$inputs"
    local p
    for p in "${paths[@]}"; do
        # "-<path>" (or "-@hiroleague:<path>"): a folder under a listed path that the part does not read
        if [[ "$p" == -@hiroleague:* ]]; then
            core_out+=" ${p#-@hiroleague:}"
        elif [[ "$p" == -* ]]; then
            own_out+=" ${p#-}"
        elif [[ "$p" == @hiroleague:* ]]; then
            if [[ "${REPO_ROOT}" == "${HIROLEAGUE}" ]]; then own+=("${p#@hiroleague:}"); else core+=("${p#@hiroleague:}"); fi
        else
            own+=("$p")
        fi
    done
    local now same_as_pushed=false
    now="$(fingerprint "${REPO_ROOT}" "$now_tree" "$own_out" "${own[@]}")"
    if [[ -n "$base" && "$now" == "$(fingerprint "${REPO_ROOT}" "$base" "$own_out" "${own[@]}")" ]]; then
        same_as_pushed=true
    fi
    if [[ ${#core[@]} -gt 0 ]]; then
        core_trees
        local core_fp
        core_fp="$(fingerprint "${HIROLEAGUE}" "$core_now" "$core_out" "${core[@]}")"
        if [[ -z "$core_base" || "$core_fp" != "$(fingerprint "${HIROLEAGUE}" "$core_base" "$core_out" "${core[@]}")" ]]; then
            same_as_pushed=false
        fi
        now="$(printf '%s\n%s\n' "$now" "$core_fp" | git hash-object --stdin)"
    fi
    if ! $all; then
        if $same_as_pushed; then
            echo "==> ${name}: skipped, its files are the same as pushed"
            skipped+=("${name}")
            return
        fi
        if grep -qxF "${name}"$'\t'"${now}" "$stamp" 2>/dev/null; then
            echo "==> ${name}: skipped, it already passed on these exact files"
            skipped+=("${name}")
            return
        fi
    fi
    q_names+=("$name")
    q_lanes+=("${name%%:*}")
    q_cmds+=("$(printf '%q ' "$@")")
    q_ids+=("$now")
}

# Each part's start and end as a Work event (build-kit/work/check_events.py: on the PC, under C:\hiro, only); never
# fails the check.
work_event() {
    local helper="${HIROLEAGUE}/build-kit/work/check_events.py"
    [[ -f "$helper" ]] || return 0
    python "$helper" "${REPO_ROOT}" "$@" >/dev/null 2>&1 || true
}
# The running count of each part's tests goes to the Work area only from the PC's environments (C:\hiro\envN)
work_progress=false
shopt -s nocasematch
[[ "${REPO_ROOT}" =~ ^(/c|c:)/hiro/env[0-9]/ ]] && work_progress=true
shopt -u nocasematch

# One lane: its parts in turn, each one's output in its own file, then its exit code and seconds.
run_lane() {
    local lane="$1" dir="$2" i t rc secs
    for i in "${!q_names[@]}"; do
        [[ "${q_lanes[$i]}" == "$lane" ]] || continue
        : > "${dir}/${i}.started"
        work_event start "${q_names[$i]}"
        t=$SECONDS
        ( eval "${q_cmds[$i]}" ) > "${dir}/${i}.log" 2>&1 &
        local pid=$! tick=0
        # While it runs, the tests it has done so far, every 3 s (a count only; under C:\hiro only). It looks every
        # half second, so a short part ends as soon as it is done.
        while kill -0 "$pid" 2>/dev/null; do
            sleep 0.5
            tick=$((tick + 1))
            $work_progress && (( tick % 6 == 0 )) && work_event progress "${q_names[$i]}" "${dir}/${i}.log"
        done
        wait "$pid"
        rc=$?
        secs=$((SECONDS - t))
        work_event end "${q_names[$i]}" "$rc" "$secs" "${dir}/${i}.log"
        echo "$rc $secs" > "${dir}/${i}.rc"
    done
}

# Run what part() queued, lanes side by side; print each part as it ends; the summary and the exit code.
check_done() {
    local count=${#q_names[@]}
    if $dry_run; then
        local n
        for n in "${q_names[@]}"; do echo "==> ${n}: would run"; done
        echo "check: dry run, ${count} part(s) would run, ${#skipped[@]} skipped"
        exit 0
    fi
    # The core's tests make onnxruntime send a phantom Ctrl-C to the whole console (scripts/run-tests.sh ignores it):
    # ignored here too, or it would stop the other lanes. Close the terminal (or Ctrl-Break) to stop a check.
    trap '' INT
    if [[ $count -eq 0 ]]; then
        echo ""
        [[ ${#skipped[@]} -gt 0 ]] && echo "check: skipped (unchanged): ${skipped[*]}"
        echo "check: nothing to check (use --all to run every part)"
        exit 0
    fi
    local dir lanes=() lane i start=$SECONDS
    dir="$(mktemp -d)"
    trap 'kill $(jobs -p) 2>/dev/null; rm -rf "$dir"' TERM
    for lane in "${q_lanes[@]}"; do
        [[ " ${lanes[*]} " == *" ${lane} "* ]] || lanes+=("$lane")
    done
    echo ""
    echo "check: ${count} part(s) in ${#lanes[@]} lane(s), at most ${max_jobs} at once: ${lanes[*]}"
    [[ -n "${CHECK_SOLO_LANES:-}" ]] && echo "       alone: ${CHECK_SOLO_LANES}"
    local -a pending=("${lanes[@]}") printed=() started=()
    local done_count=0 rc secs running next solo_running=""
    while [[ $done_count -lt $count ]]; do
        # Start lanes while there is room: a solo lane only when nothing else runs, nothing beside a solo lane, and
        # a lane beyond the first only with enough free memory
        while [[ ${#pending[@]} -gt 0 ]]; do
            running=$(jobs -rp | wc -l)
            [[ -n "$solo_running" && $running -gt 0 ]] && break
            solo_running=""
            next="${pending[0]}"
            if [[ " ${CHECK_SOLO_LANES:-} " == *" ${next} "* ]]; then
                [[ $running -gt 0 ]] && break
                solo_running="$next"
            elif [[ $running -ge $max_jobs ]] || { [[ $running -gt 0 ]] && [[ $(free_kb) -lt $min_free_kb ]]; }; then
                break
            fi
            run_lane "$next" "$dir" &
            pending=("${pending[@]:1}")
        done
        for i in "${!q_names[@]}"; do
            if [[ -f "${dir}/${i}.started" && -z "${started[$i]:-}" ]]; then
                started[$i]=1
                echo "    started: ${q_names[$i]}"
            fi
            if [[ -f "${dir}/${i}.rc" && -z "${printed[$i]:-}" ]]; then
                printed[$i]=1
                done_count=$((done_count + 1))
                read -r rc secs < "${dir}/${i}.rc"
                echo ""
                echo "==> ${q_names[$i]}"
                cat "${dir}/${i}.log"
                if [[ "$rc" == 0 ]]; then
                    echo "    passed in ${secs} s"
                    # Remember the pass (the last 50, so undoing a change doesn't re-run what passed on that code)
                    { grep -vxF "${q_names[$i]}"$'\t'"${q_ids[$i]}" "$stamp" 2>/dev/null
                      printf '%s\t%s\n' "${q_names[$i]}" "${q_ids[$i]}"; } | tail -n 50 > "${stamp}.tmp"
                    mv "${stamp}.tmp" "$stamp"
                else
                    echo "    FAILED in ${secs} s (exit ${rc})"
                    failed+=("${q_names[$i]}")
                fi
            fi
        done
        [[ $done_count -lt $count ]] && sleep 1
    done
    wait
    rm -rf "$dir"
    echo ""
    [[ ${#skipped[@]} -gt 0 ]] && echo "check: skipped (unchanged): ${skipped[*]}"
    echo "check: ${count} part(s) in $((SECONDS - start)) s"
    if [[ ${#failed[@]} -gt 0 ]]; then
        echo "check: FAILED:"
        printf '  - %s\n' "${failed[@]}"
        exit 1
    fi
    echo "check: all passed"
    exit 0
}

# The copy list's part (above): queued for every repo that has one, before the repo's own parts
if [[ -r "${REPO_ROOT}/data.toml" ]]; then
    COPYLIST_PY="$(command -v python || command -v python3)"  # Windows' python3 is the Store's stub
    part "copy list: data.toml" "data.toml @hiroleague:build-kit/work/copylist.py"         "${COPYLIST_PY}" "${HIROLEAGUE}/build-kit/work/copylist.py" "${REPO_ROOT}"
fi
