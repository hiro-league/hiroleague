#!/usr/bin/env bash
# Deploy HiroLeague on a Linux server where it runs as a systemd service (`hiro service install`).
# Normally run by the post-receive hook after `git push <server> main`; can be run by hand from the
# checkout (~/hiroleague/deploy/deploy.sh) to redeploy the same commit.
#
# Follows the build standard (hiro-docs standards/building-and-releasing.md):
#   1. checks first: ./scripts/check.sh; a failure stops here with nothing changed;
#   2. builds the admin UI and installs this commit with uv into a new release folder
#      $HIRO_HOME/releases/<time>-<commit>; the service runs $HIRO_HOME/current/bin/hiro, a link;
#   3. stops the service, copies the workspace databases (hiro-db-snapshot, as root: SQLite through
#      its backup, the Kuzu graph as files, which only works while the server is stopped);
#   4. points `current` at the new release, starts the service, polls its /status;
#   5. if it doesn't answer: puts the copied databases back, points `current` at the previous
#      release and starts that again.
#
# Settings (environment variables, defaults in brackets):
#   HIRO_HOME           [/opt/hiroleague] where releases are installed; readable by the service's user
#   HIRO_SERVICE        [hiro] the systemd service (hiro.service)
#   HIRO_HEALTH_URL     [http://127.0.0.1:18080/status] the server's /status (first workspace's port)
#   HIRO_HEALTH_TIMEOUT [240] seconds to wait for it after a start
#   HIRO_PYTHON         [3.12] Python version uv installs into
#   HIRO_KEEP_RELEASES  [3] releases kept on disk (the current one included)
#
# Needs: uv, node + npm, curl; the sudoers line and the root helper from the deploy guide
#   (hiro-docs mintdocs/build/local-build/server-deploy.mdx).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HIRO_HOME="${HIRO_HOME:-/opt/hiroleague}"
HIRO_SERVICE="${HIRO_SERVICE:-hiro}"
HIRO_HEALTH_URL="${HIRO_HEALTH_URL:-http://127.0.0.1:18080/status}"
HIRO_HEALTH_TIMEOUT="${HIRO_HEALTH_TIMEOUT:-240}"
HIRO_PYTHON="${HIRO_PYTHON:-3.12}"
HIRO_KEEP_RELEASES="${HIRO_KEEP_RELEASES:-3}"

UNIT="${HIRO_SERVICE}.service"
SYSTEMCTL=/usr/bin/systemctl
SNAPSHOT_HELPER=/usr/local/sbin/hiro-db-snapshot
CURRENT="${HIRO_HOME}/current"

say() { echo "hiroleague: $*"; }
die() { say "$*"; exit 1; }

# --- 0. What this needs -----------------------------------------------------------------------
for cmd in uv npm curl git; do
  command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' is not installed or not on PATH; see the deploy guide (hiro-docs mintdocs/build/local-build/server-deploy.mdx, Server prerequisites)."
done
[ -d "$HIRO_HOME" ] && [ -w "$HIRO_HOME" ] \
  || die "$HIRO_HOME is missing or not writable by $(id -un); see the deploy guide (hiro-docs mintdocs/build/local-build/server-deploy.mdx, First-time setup)."

cd "$REPO_ROOT"
# The server's checkout is a work tree of the bare repo (~/hiroleague.git), with no .git of its own,
# and the checks compare generated files with `git diff`: point git at the bare repo, whether the
# hook or a person runs this (found on the first deploy, 2026-11-06).
if [ ! -e "$REPO_ROOT/.git" ] && [ -d "$HOME/hiroleague.git" ]; then
  export GIT_DIR="$HOME/hiroleague.git" GIT_WORK_TREE="$REPO_ROOT"
fi
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-${COMMIT}"
RELEASE_DIR="${HIRO_HOME}/releases/${RELEASE_ID}"
say "deploying ${COMMIT} as release ${RELEASE_ID}"

# --- 1. Checks (stop on failure, nothing changed) ---------------------------------------------
# check.sh installs nothing: the dev setup does, and here the deploy is the dev setup.
# `npm ci` installs exactly package-lock.json (as the PyPI release build does).
say "installing the admin UI's packages (npm ci)"
(cd admin_frontend && npm ci --no-audit --no-fund) || die "npm ci failed: nothing was changed."
say "running the checks (scripts/check.sh)"
./scripts/check.sh || die "checks failed: nothing was changed."

# --- 2. Build and install the new release (the running service is untouched) ------------------
say "building the admin UI"
(cd admin_frontend && npm run package:python) || die "admin UI build failed: nothing was changed."

cleanup_release() { rm -rf "$RELEASE_DIR"; }

say "installing into ${RELEASE_DIR}"
mkdir -p "${RELEASE_DIR}"
CONSTRAINTS="${RELEASE_DIR}/constraints.txt"
# uv tool install resolves afresh; pin it to uv.lock, the versions check.sh just tested.
if ! (cd hiroserver && uv export --frozen --no-emit-workspace --no-dev --no-hashes \
        --package hiroleague -o "$CONSTRAINTS" >/dev/null); then
  cleanup_release; die "could not export uv.lock: nothing was changed."
fi
# Rebuild HiroLeague's own packages from this checkout every time. uv caches a build of a local
# package by its version and pyproject.toml, so without this a release whose code changed but whose
# version didn't (0.2.0) would install the OLD cached code, and checks pass on the checkout regardless
# (seen 2026-11-06: Phase 3's extension socket missing from the release). Other packages stay cached.
REFRESH=()
for member in hiroserver/hiroleague hiroserver/hirocli hiroserver/gateway hiroserver/hiro-channel-sdk \
              hiroserver/hiro-commons hiroserver/channels/*; do
  name=$(sed -n 's/^name = "\(.*\)"/\1/p' "$member/pyproject.toml" 2>/dev/null | head -n 1)
  [ -n "$name" ] && REFRESH+=(--refresh-package "$name")
done
# Each release gets its own tool and command folders, so the previous one stays installed and
# going back is moving a link. Python goes in a folder under HIRO_HOME too: anything uv puts in
# the deploy user's home would not be readable by a dedicated service user.
if ! UV_TOOL_DIR="${RELEASE_DIR}/tools" UV_TOOL_BIN_DIR="${RELEASE_DIR}/bin" \
     UV_PYTHON_INSTALL_DIR="${HIRO_HOME}/python" \
     uv tool install --python "$HIRO_PYTHON" --constraints "$CONSTRAINTS" "${REFRESH[@]}" ./hiroserver/hiroleague; then
  cleanup_release; die "install failed: nothing was changed."
fi
"${RELEASE_DIR}/bin/hiro" --help >/dev/null 2>&1 \
  || { cleanup_release; die "the new release's 'hiro' does not run: nothing was changed."; }
chmod -R a+rX "$RELEASE_DIR" "${HIRO_HOME}/python" 2>/dev/null || true

switch_current() {  # $1 = release folder; atomic: a new link renamed over the old one
  ln -sfn "$1" "${CURRENT}.new"
  mv -Tf "${CURRENT}.new" "$CURRENT"
}

# --- First deploy: no service yet -------------------------------------------------------------
if ! "$SYSTEMCTL" cat "$UNIT" >/dev/null 2>&1; then
  switch_current "$RELEASE_DIR"
  say "installed ${RELEASE_ID}. The service is not installed yet; install it once (as root):"
  say "  sudo ${CURRENT}/bin/hiro service install --user <user it runs as>"
  say "then finish the steps in the deploy guide (hiro-docs mintdocs/build/local-build/server-deploy.mdx, First-time setup)."
  exit 0
fi

# --- Before touching the service: everything the deploy relies on is in place ---------------
EXEC_START="$("$SYSTEMCTL" show -p ExecStart --value "$UNIT" 2>/dev/null || true)"
case "$EXEC_START" in
  *"${CURRENT}/bin/hiro "*) ;;
  *) cleanup_release
     die "${UNIT} does not run ${CURRENT}/bin/hiro, so a deploy would not change what runs. Reinstall it: sudo ${CURRENT}/bin/hiro service install --user <user>" ;;
esac
if ! cmp -s "${REPO_ROOT}/deploy/hiro-db-snapshot" "$SNAPSHOT_HELPER"; then
  cleanup_release
  die "${SNAPSHOT_HELPER} is missing or differs from deploy/hiro-db-snapshot; install it (as root): sudo install -o root -g root -m 0755 ${REPO_ROOT}/deploy/hiro-db-snapshot ${SNAPSHOT_HELPER}"
fi
PREVIOUS="$(readlink "$CURRENT" 2>/dev/null || true)"

healthy() {  # polls /status until it answers "running": true, or the timeout
  local deadline=$((SECONDS + HIRO_HEALTH_TIMEOUT))
  local body
  while [ "$SECONDS" -lt "$deadline" ]; do
    # Body read whole first: with pipefail, `curl | grep -q` can fail on curl's broken pipe.
    body="$(curl -fsS --max-time 5 "$HIRO_HEALTH_URL" 2>/dev/null || true)"
    if [[ "$body" =~ \"running\":\ *true ]]; then
      return 0
    fi
    sleep 3
  done
  return 1
}

show_logs() {  # the journal is readable by members of the adm / systemd-journal groups
  journalctl -u "$UNIT" -n 40 --no-pager 2>/dev/null || say "(can't read the journal: add $(id -un) to the adm group to see it here)"
}

# --- 3. Stop, copy the databases --------------------------------------------------------------
say "stopping ${UNIT}"
sudo -n "$SYSTEMCTL" stop "$UNIT" \
  || { cleanup_release; die "could not stop ${UNIT} (is the sudoers line from the deploy guide in place?): nothing was changed."; }
say "copying the databases"
if ! sudo -n "$SNAPSHOT_HELPER" save "$UNIT"; then
  say "database copy failed: starting the current version again"
  sudo -n "$SYSTEMCTL" start "$UNIT" || true
  cleanup_release
  die "deploy stopped before any change (the databases were not copied)."
fi

# --- 4. Switch and start ----------------------------------------------------------------------
switch_current "$RELEASE_DIR"
say "starting ${RELEASE_ID}"
sudo -n "$SYSTEMCTL" start "$UNIT" || say "start failed"
if healthy; then
  # Keep the newest HIRO_KEEP_RELEASES releases (names sort by time); never the current one.
  current_target="$(readlink "$CURRENT")"
  find "${HIRO_HOME}/releases" -mindepth 1 -maxdepth 1 -type d | sort -r \
    | tail -n +"$((HIRO_KEEP_RELEASES + 1))" | while read -r old; do
        [ "$old" = "$current_target" ] || rm -rf "$old"
      done
  say "deployed ${RELEASE_ID}: ${HIRO_HEALTH_URL} answers."
  exit 0
fi

# --- 5. Go back -------------------------------------------------------------------------------
say "${RELEASE_ID} did not answer ${HIRO_HEALTH_URL} within ${HIRO_HEALTH_TIMEOUT} s. Its last log lines:"
show_logs
say "going back: stopping it, putting the copied databases back"
sudo -n "$SYSTEMCTL" stop "$UNIT" || say "stop failed"
if ! sudo -n "$SNAPSHOT_HELPER" restore "$UNIT"; then
  die "ROLLBACK INCOMPLETE: the databases could not be put back. The service is stopped; the copy is in /var/backups/hiro/${UNIT}."
fi
if [ -z "$PREVIOUS" ] || [ ! -d "$PREVIOUS" ]; then
  die "ROLLBACK INCOMPLETE: no previous release to go back to. Databases restored; the service is stopped."
fi
switch_current "$PREVIOUS"
say "starting the previous release ($(basename "$PREVIOUS"))"
sudo -n "$SYSTEMCTL" start "$UNIT" || say "start failed"
if healthy; then
  say "rolled back to $(basename "$PREVIOUS"); it answers. The failed release stays in ${RELEASE_DIR} for a look."
else
  say "ROLLBACK INCOMPLETE: the previous release does not answer either. Its last log lines:"
  show_logs
fi
exit 1
