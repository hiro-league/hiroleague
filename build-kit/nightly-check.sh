#!/usr/bin/env bash
# Every Hiro app's nightly full check on the server: one copy, here in HiroLeague, which each app's
# deploy/nightly-check.sh runs from the app's folder (shared-code plan, step 2). It builds the shared Dockerfile's
# `fullcheck` target, in Linux, on the deployed code (~/<app>) and HiroLeague's kits beside it (~/hiroleague): the UI's
# svelte-check, ESLint and vitest, and the backend checks app.env lists (BACKEND_CHECKS). A deploy doesn't run them
# (./scripts/check.sh on the PC is the gate before the push), so this is the Linux safety net: a failure shows on
# NetHiro's System health the next morning.
#
# Run by a timer in aicam (host/, <app>-nightly-check.timer), as michelhabib. Reports to NetHiro's System health
# (127.0.0.1:8130) as the job "nightly-check-<app>"; its key file (~/.config/<app>-check/job.key) holds that job's key in
# NetHiro (Settings → System health → Jobs). Without the key file the run still happens and is logged, just not
# reported. The key goes to curl on stdin, never the command line.
set -uo pipefail

[ -r app.env ] || { echo "nightly-check: no app.env here ($PWD): run it through the app's deploy/nightly-check.sh" >&2; exit 2; }
# shellcheck disable=SC1091
source ./app.env
: "${APP:?app.env sets APP}"

HERE="$PWD"                                                        # ~/<app>
HIROLEAGUE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"      # ~/hiroleague (the image takes the kits from there)
JOB="http://127.0.0.1:8130/api/service-status/jobs/nightly-check-$APP/ran"  # NetHiro's System health
KEY="$HOME/.config/$APP-check/job.key"
LOGDIR="$HOME/.local/state/$APP-check"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/last.log"

log() { echo "$(date '+%F %T') $*"; }

report() {  # ok (true|false), note
  [ -r "$KEY" ] || { log "System health not told: no $KEY"; return 0; }
  body=$(python3 -c 'import json,sys; print(json.dumps({"ok": sys.argv[1] == "true", "note": sys.argv[2][:500]}))' "$1" "$2")
  printf 'header = "Authorization: Bearer %s"\n' "$(cat "$KEY")" \
    | curl -fsS -m 10 -o /dev/null --config - -X POST "$JOB" -H "Content-Type: application/json" -d "$body" \
    || log "WARNING: System health not told (NetHiro may be down)"
}

started=$SECONDS
log "nightly check of $(git -C "$HERE" log --oneline -1 2>/dev/null || echo "$HERE")"
# --no-cache-filter: the two checks always run, even when nothing changed since last night (the point is to run them).
if BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker buildx build --target fullcheck \
     --file "$HIROLEAGUE/build-kit/Dockerfile" --build-context hiroleague="$HIROLEAGUE" \
     --build-arg BACKEND_CHECKS="${BACKEND_CHECKS:-ruff pytest}" --no-cache-filter check,ui-check \
     --progress plain -t "$APP:fullcheck" "$HERE" > "$LOG" 2>&1; then
  passed=$(grep -oE '[0-9]+ passed' "$LOG" | head -2 | paste -sd ', ' -)
  log "passed in $((SECONDS - started))s ($passed)"
  report true "All checks passed in $((SECONDS - started)) s: $passed."
else
  what=$(grep -E '== (svelte-check|eslint|vitest) failed|[0-9]+ failed|Found [0-9]+ error' "$LOG" | head -3 | paste -sd '; ' -)
  log "FAILED after $((SECONDS - started))s: ${what:-see $LOG}"
  report false "Failed: ${what:-the build stopped} (log: $LOG on the server)."
  exit 1
fi
