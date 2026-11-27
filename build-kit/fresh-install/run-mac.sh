#!/usr/bin/env bash
# A person's whole path on a Mac, run on the macOS test VM by fresh.py (aicam's docs/macos-test-vm.md; never on a Mac
# anyone uses), in two parts with a restart of the Mac between them:
#   run-mac.sh <bundle> <results>           uv, the core, `hiro service install` (a LaunchDaemon), Hello's install, its
#                                           three upgrades and its removal, WhatsApp's install, upgrade and removal,
#                                           the phones' channel refused, the core's LAN name, the logs read for problems
#                                           (an Intel Mac takes three workarounds: INTEL below)
#   run-mac.sh <bundle> <results> restart   after fresh.py restarted the Mac: the core is back by itself, at its name
#
# The bundle is fresh.py's (hiroleague/, hello/). Each step's output goes to <results>/logs/NN-<step>.log; the steps
# are kept in <results>/steps.txt across the restart; the restart part writes result.md and result.json. The person
# has sudo without a password (the only shortcut). macOS's /usr/bin/python3 asks to install Xcode's tools, so the
# checks use uv's Python (PY below).
set -u
BUNDLE="$1"
RESULTS="$2"
PART="${3:-path}"
NAME="hirofresh"  # the core's own name: hirofresh.local (never hiro: Simone owns it)
LABEL="com.hiroleague.hiro"
HOME_DIR="/Library/Application Support/HiroLeague"
SERVICE_LOG="$HOME_DIR/logs/hiro.log"
mkdir -p "$RESULTS/logs"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONIOENCODING=utf-8 COLUMNS=160 NO_COLOR=1
export UV_HTTP_TIMEOUT=1800  # the cache answers a first download only once it has it all
STEPS_FILE="$RESULTS/steps.txt"  # name|ok|seconds|detail|log, one per line
N=$(ls "$RESULTS/logs" | wc -l | tr -d ' ')

PY() { uv run --no-project --python 3.12 python "$@"; }

record() {  # name ok seconds detail log
  printf '%s|%s|%s|%s|%s\n' "$1" "$2" "$3" "${4//|//}" "$5" >>"$STEPS_FILE"
  printf '%s %-34s %s\n' "$([ "$2" = yes ] && echo PASS || echo FAIL)" "$1" "$4"
}

# An Intel Mac (the test VM) isn't a Mac Hiro League supports: torch, onnxruntime and cryptography no longer ship for
# it. The test works around them there, and a Mac with Apple's chips installs everything as a person's does.
INTEL=no
[ "$(uname -m)" = x86_64 ] && INTEL=yes

# run <name> <expect: ok|fails> <pattern or ""> <command...>: the step passes when its exit code is as expected and
# its output holds the pattern
run() {
  local name="$1" expect="$2" pattern="$3"; shift 3
  N=$((N + 1))
  local log; log="$RESULTS/logs/$(printf '%02d' "$N")-${name// /-}.log"
  local start=$SECONDS
  { echo "\$ $*"; "$@"; } </dev/null >"$log" 2>&1  # nothing waits on a question: a step that asks fails
  local code=$?
  local took=$((SECONDS - start)) ok=yes detail="exit $code"
  if [ "$expect" = ok ] && [ $code -ne 0 ]; then ok=no; fi
  if [ "$expect" = fails ] && [ $code -eq 0 ]; then ok=no; fi
  if [ -n "$pattern" ] && ! grep -qiE "$pattern" "$log"; then ok=no; detail="$detail, no \"$pattern\" in its output"; fi
  record "$name" "$ok" "$took" "$detail" "logs/$(basename "$log")"
  [ "$ok" = yes ]
}

check() {  # name command...: a check, not a step of the person's
  N=$((N + 1))
  local name="$1"; shift
  local log; log="$RESULTS/logs/$(printf '%02d' "$N")-${name// /-}.log"
  if "$@" </dev/null >"$log" 2>&1; then record "$name" yes 0 "as expected" "logs/$(basename "$log")"
  else record "$name" no 0 "see its log" "logs/$(basename "$log")"; fi
}

# hello_is <version>: the core's installs list says Hello runs at that version
hello_is() {
  hiro extension list --json 2>/dev/null | PY -c '
import json, sys
rows = [r for r in json.load(sys.stdin)["installs"] if r["key"] == "example.hello"]
want = sys.argv[1]
ok = (not rows) if want == "gone" else bool(rows) and rows[0]["version"] == want and rows[0]["running"] is True
print(rows)
sys.exit(0 if ok else 1)' "$1"
}

service_pid() { sudo launchctl print "system/$LABEL" | awk '/^\tpid = / {print $3}'; }

service_runs_once() {  # running, and launchd started it once since the Mac booted (no restarts)
  sudo launchctl print "system/$LABEL" | tee /dev/stderr | grep -q "state = running" &&
    [ "$(sudo launchctl print "system/$LABEL" | awk '/^\truns = / {print $3}')" = 1 ]
}

lan_name_checks() {
  # macOS's own resolver asks mDNS for a .local name, as any program on the Mac would
  check "$NAME.local resolves$1" sh -c "dscacheutil -q host -a name $NAME.local | grep ip_address"
  check "front door answers $NAME.local$1" sh -c "curl -s -o /dev/null -w '%{http_code}' --resolve $NAME.local:80:127.0.0.1 http://$NAME.local/ | grep -E '^[23]'"
}

if [ "$PART" = path ]; then
  : >"$STEPS_FILE"
  # The package cache (fresh.py, unless --fresh): uv's machine-wide settings, which every uv here obeys (the person's,
  # the service's, the core's own for apps), point at Simone's cache. The only difference from a person's machine.
  if [ -f "$BUNDLE/CACHE" ]; then
    read -r CACHE_INDEX CACHE_PYTHONS < <(tr -d '\r' <"$BUNDLE/CACHE")  # never a \r into uv's settings
    sudo mkdir -p /etc/uv
    printf 'python-install-mirror = "%s"\n\n[[index]]\nurl = "%s"\ndefault = true\n' "$CACHE_PYTHONS" "$CACHE_INDEX" \
      | sudo tee /etc/uv/uv.toml >/dev/null
  fi
  if [ "$INTEL" = yes ]; then
    # cryptography 49 and later: no Intel build, and building one needs Xcode. A channel the core installs resolves
    # its own versions, so every uv here is told never to build cryptography: it takes the last Intel build (48).
    # (Hello pins that one itself: build-kit/test-app.)
    sudo mkdir -p /etc/uv
    { printf 'no-build-package = ["cryptography"]\n'; sudo cat /etc/uv/uv.toml 2>/dev/null; } >"$RESULTS/uv.toml"
    sudo cp "$RESULTS/uv.toml" /etc/uv/uv.toml
  fi
  # The pinned downloads (fresh.py, unless --fresh): Caddy, in the machine's downloads folder, where the core looks first
  if [ -d "$BUNDLE/downloads" ]; then
    sudo mkdir -p "$HOME_DIR/cache/downloads"
    sudo cp "$BUNDLE"/downloads/* "$HOME_DIR/cache/downloads/"
  fi

  HELLO="$BUNDLE/hello"
  run "uv" ok "" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  if [ "$INTEL" = yes ]; then
    # torch and onnxruntime no longer ship for an Intel Mac either: the test takes their last Intel builds (local AI
    # isn't tested here). A Mac with Apple's chips installs the lock as is.
    printf 'torch==2.2.2\nonnxruntime==1.23.2\n' >"$BUNDLE/intel-mac-overrides.txt"
    run "core (uv tool install, Intel overrides)" ok "" uv tool install --python 3.12 \
      --overrides "$BUNDLE/intel-mac-overrides.txt" "$BUNDLE/hiroleague/hiroserver/hiroleague"
  else
    run "core (uv tool install)" ok "" uv tool install --python 3.12 "$BUNDLE/hiroleague/hiroserver/hiroleague"
  fi
  # As a person does: `hiro service install` says to run it again through sudo, with its full path
  run "service install (asks for sudo)" fails "needs root" hiro service install --name "$NAME"
  run "service install" ok "" sudo "$(command -v hiro)" service install --name "$NAME"
  sleep 60  # a service that fails at start restarts in this time
  check "service still runs after 60 s" service_runs_once

  run "Hello 0.1.0 install" ok "it runs and is paired" hiro extension install "$HELLO/example_hello-0.1.0-py3-none-any.whl" --approve
  check "Hello runs 0.1.0" hello_is 0.1.0
  run "Hello 0.1.3 (goes back)" fails "" hiro extension upgrade example.hello "$HELLO/example_hello-0.1.3-py3-none-any.whl"
  check "Hello back on 0.1.0" hello_is 0.1.0
  run "Hello 0.1.2 (stays)" fails "" hiro extension upgrade example.hello "$HELLO/example_hello-0.1.2-py3-none-any.whl"
  check "Hello still on 0.1.0" hello_is 0.1.0
  run "Hello 0.1.1 (upgrades)" ok "" hiro extension upgrade example.hello "$HELLO/example_hello-0.1.1-py3-none-any.whl"
  check "Hello runs 0.1.1" hello_is 0.1.1
  run "Hello remove --purge" ok "Removed" hiro extension remove example.hello --purge --yes
  check "Hello gone" hello_is gone

  run "WhatsApp install" ok "Installed" hiro extension install whatsapp
  run "WhatsApp upgrade" ok "Upgraded" hiro extension upgrade whatsapp
  run "WhatsApp remove" ok "Removed" hiro extension remove whatsapp
  run "devices refused" fails "comes with the core" hiro extension install devices

  check "core announces its address" sh -c 'hiro logs search "announcing on" --json | grep -m1 "announcing on"'
  lan_name_checks ""
  check "problems in the logs" sh -c "hiro logs problems --since 2h --json | uv run --no-project --python 3.12 python '$BUNDLE/read_logs.py' problems"
  check "service log has no error" sh -c "sudo cat '$SERVICE_LOG' | uv run --no-project --python 3.12 python '$BUNDLE/read_logs.py' service"
  service_pid >"$RESULTS/pid-before-restart"
  exit 0
fi

# --- after the restart: launchd started the core by itself (RunAtLoad), as a new process, and it serves its name
sleep 45  # SSH answers before the core has announced its name
core_is_back() {  # running as a new process, started once since the boot
  local before now
  before=$(cat "$RESULTS/pid-before-restart")
  now=$(service_pid)
  echo "pid $now, before the restart $before"
  service_runs_once && [ -n "$now" ] && [ "$now" != "$before" ]
}
check "core back after the restart" core_is_back
lan_name_checks " after the restart"
# From the boot exactly (an ISO time): the first part's problems stay its own step's
BOOT=$(date -u -r "$(sysctl -n kern.boottime | sed -E 's/.*sec = ([0-9]+).*/\1/')" '+%Y-%m-%dT%H:%M:%SZ')
check "no new problems after the restart" sh -c "hiro logs problems --since $BOOT --json | uv run --no-project --python 3.12 python '$BUNDLE/read_logs.py' problems"

# The result
{
  echo "# Fresh install: macOS $(sw_vers -productVersion) ($(uname -m)), the test VM on Simone"
  echo
  echo "$(date '+%a, %b %-d, %-I:%M %p') · core $(cat "$BUNDLE/COMMIT" 2>/dev/null)"
  echo
  echo "| | Step | Took | Detail | Log |"
  echo "|---|---|---|---|---|"
  while IFS='|' read -r name ok took detail log; do
    echo "| $([ "$ok" = yes ] && echo PASS || echo '**FAIL**') | $name | ${took} s | $detail | [log]($log) |"
  done <"$STEPS_FILE"
} >"$RESULTS/result.md"
PY -c '
import json, sys
rows = [dict(zip(("step", "ok", "seconds", "detail", "log"), line.rstrip("\n").split("|"))) for line in open(sys.argv[1])]
for r in rows:
    r["ok"], r["seconds"] = r["ok"] == "yes", int(r["seconds"])
json.dump({"system": "mac", "passed": all(r["ok"] for r in rows), "steps": rows}, sys.stdout, indent=2)' "$STEPS_FILE" \
  >"$RESULTS/result.json"
echo "done" >"$RESULTS/finished"
