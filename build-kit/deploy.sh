#!/usr/bin/env bash
# Every Hiro app's deploy on the server (HomeHiro, NetHiro, TrainHiro, StudyHiro): one copy, here in HiroLeague, which
# each app's deploy.sh runs from its own folder (shared-code plan, step 2). The app's facts (its name, port and start-up
# patience) are in its app.env. The post-receive hook runs the app's deploy.sh after `git push server main`; it can also
# be run by hand in ~/<app> to rebuild. ~/hiroleague is the checkout the core's deploy refreshes, so the core goes first.
#
# The live data is the family's only copy between the nightly backups, so the new version goes live only once it is
# safe (hiro-docs standards/building-and-releasing.md, "The family's data is safe"):
#   1. the running image is kept as <app>:previous, to go back to;
#   2. the new image is built (no checks in it: ./scripts/check.sh before the push is the gate, and
#      deploy/nightly-check.sh runs the full check on this server every night); a failed build stops here;
#   3. the live database is copied (data/deploy-backups, the last 5 kept; HomeHiro's streams.db only when its
#      migrations change, its predeploy.py says why);
#   4. the new migrations run on another copy, and a table gone or with fewer rows stops here, nothing changed
#      (a migration meant to remove rows: ALLOW_ROW_LOSS=<tables> ./deploy.sh);
#   5. the container restarts on the new image, and /api/health must answer;
#   6. if it doesn't: back to the previous image, and to the database as step 3 copied it.
# The steps on the data are the app's `python -m <app>.predeploy snapshot|trial|restore|settled <stamp>` (the backend
# kit's predeploy.py; HomeHiro's own adds streams.db).
set -euo pipefail

[ -r app.env ] || { echo "deploy: no app.env here ($PWD): run it through the app's deploy.sh" >&2; exit 2; }
# shellcheck disable=SC1091
source ./app.env
: "${APP:?app.env sets APP}" "${APP_NAME:?app.env sets APP_NAME}" "${APP_PORT:?app.env sets APP_PORT}"

IMAGE="$APP:local"        # compose.yaml's image
PREVIOUS="$APP:previous"
STAMP="pre-deploy-$(date -u +%Y%m%d-%H%M%SZ)"  # the copies' names (predeploy.py)

# A one-off container of the image <app>:local names, on the same data folder; the running one goes on meanwhile.
once() { docker compose run -T --rm --no-deps "$@"; }
predeploy() { once "$APP" python -m "$APP.predeploy" "$@"; }

# /api/health answers within $1 seconds
healthy() {
  local until=$((SECONDS + $1))
  while [ "$SECONDS" -lt "$until" ]; do
    if curl -fsS "http://127.0.0.1:$APP_PORT/api/health"; then echo; return 0; fi
    sleep 2
  done
  return 1
}

had_previous=false
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker tag "$IMAGE" "$PREVIOUS"
  had_previous=true
fi
# <app>:local back on the image that runs, so a restart of the server never starts the one refused
not_deployed() {
  echo "$APP: not deployed: $1"
  if $had_previous; then docker tag "$PREVIOUS" "$IMAGE"; fi
  docker image prune -f >/dev/null  # the image refused
  exit 1
}

# Docker checks the registries on every build, and the server's internet has brief TLS timeouts:
# retry the build rather than fail the deploy. No provenance record in the image: it only slows the export.
export BUILDX_NO_DEFAULT_ATTESTATIONS=1
for attempt in 1 2 3 4; do
  docker compose build && break
  [ "$attempt" = 4 ] && not_deployed "the build failed"
  echo "$APP: build failed (attempt $attempt), retrying in 10 s"; sleep 10
done

echo "$APP: copying the database before the new version touches it"
predeploy snapshot "$STAMP" || not_deployed "the database couldn't be copied (above)"
echo "$APP: trying the new migrations on a copy"
if ! tried=$(once -e ALLOW_ROW_LOSS="${ALLOW_ROW_LOSS:-}" "$APP" python -m "$APP.predeploy" trial "$STAMP"); then
  echo "$tried"
  predeploy settled "$STAMP" || true  # a copy only the trial needed (HomeHiro's streams.db)
  not_deployed "the new migrations aren't safe on the live data (above)"
fi
echo "$tried"
# The new version migrates on start, before it answers: the app's patience (START_PATIENCE, 30 s unless app.env says
# more), and twice as long as the migrations took on the copy
took=$(sed -n 's/^migrations-seconds=//p' <<<"$tried")
patience=$((${START_PATIENCE:-30} + 2 * ${took:-0}))

docker compose up -d
if healthy "$patience"; then
  predeploy settled "$STAMP" \
    || echo "$APP: the copies of $STAMP only the trial needed (if any) weren't removed: remove them by hand from data/deploy-backups"
  docker image prune -f >/dev/null  # the image before the previous one; <app>:previous stays
  echo "$APP: deployed"
  exit 0
fi

echo "$APP: health check failed"; docker compose logs --tail 30 "$APP"
$had_previous || { echo "$APP: no previous version to go back to"; exit 1; }
echo "$APP: going back to the previous version, and to the database as it was before ($STAMP)"
docker compose stop "$APP"
# Still on the new image, which has predeploy.py (the previous one may not), then the previous image
predeploy restore "$STAMP" \
  || { echo "$APP: the database couldn't be put back: $APP_NAME is stopped, look at it now"; exit 1; }
docker tag "$PREVIOUS" "$IMAGE"
docker compose up -d
if healthy 30; then
  echo "$APP: back on the previous version; the new one was not deployed"
else
  echo "$APP: the previous version doesn't answer either: look at it now"; docker compose logs --tail 30 "$APP"
fi
exit 1
