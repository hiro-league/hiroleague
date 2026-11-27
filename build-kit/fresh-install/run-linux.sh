#!/usr/bin/env bash
# A person's whole path on a fresh Linux, run inside a fresh WSL Ubuntu by fresh.py (never on a machine anyone uses):
# uv, the core, `hiro service install`, Hello's install, its three upgrades and its removal, WhatsApp's install,
# upgrade and removal, the phones' channel refused, the core's LAN name, and the service's own log read for problems.
#
#     run-linux.sh <bundle folder> <results folder>
#
# The bundle is fresh.py's (hiroleague/, hello/). Each step's output goes to <results>/logs/NN-<step>.log; the
# result is <results>/result.md and result.json. The person has sudo without a password (the only shortcut).
set -u
BUNDLE="$1"
RESULTS="$2"
NAME="hirofresh"  # the core's own name: hirofresh.local (never hiro: Simone owns it)
mkdir -p "$RESULTS/logs"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONIOENCODING=utf-8 COLUMNS=160 NO_COLOR=1
N=0
STEPS=()   # name|ok|seconds|detail|log

record() {  # name ok seconds detail log
  STEPS+=("$1|$2|$3|${4//|//}|$5")
  printf '%s %-34s %s\n' "$([ "$2" = yes ] && echo PASS || echo FAIL)" "$1" "$4"
}

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

# hello_is <version>: the core's installs list says Hello runs at that version
hello_is() {
  hiro extension list --json 2>/dev/null | python3 -c '
import json, sys
rows = [r for r in json.load(sys.stdin)["installs"] if r["key"] == "example.hello"]
want = sys.argv[1]
ok = (not rows) if want == "gone" else bool(rows) and rows[0]["version"] == want and rows[0]["running"] is True
print(rows)
sys.exit(0 if ok else 1)' "$1"
}

check() {  # name command...: a check, not a step of the person's
  N=$((N + 1))
  local name="$1"; shift
  local log; log="$RESULTS/logs/$(printf '%02d' "$N")-${name// /-}.log"
  if "$@" </dev/null >"$log" 2>&1; then record "$name" yes 0 "as expected" "logs/$(basename "$log")"
  else record "$name" no 0 "see its log" "logs/$(basename "$log")"; fi
}

HELLO="$BUNDLE/hello"
# The package cache (fresh.py, unless --fresh): uv's machine-wide settings, which every uv here obeys (the person's,
# the service's, the core's own for apps), point at Simone's cache. The only difference from a person's machine.
if [ -f "$BUNDLE/CACHE" ]; then
  read -r CACHE_INDEX CACHE_PYTHONS < <(tr -d '\r' <"$BUNDLE/CACHE")  # never a \r into uv's settings
  sudo mkdir -p /etc/uv
  printf 'python-install-mirror = "%s"\n\n[[index]]\nurl = "%s"\ndefault = true\n' "$CACHE_PYTHONS" "$CACHE_INDEX" \
    | sudo tee /etc/uv/uv.toml >/dev/null
fi
# The pinned downloads (fresh.py, unless --fresh): Caddy, in the machine's downloads folder, where the core looks first
if [ -d "$BUNDLE/downloads" ]; then
  sudo mkdir -p /opt/hiroleague/cache/downloads
  sudo cp "$BUNDLE"/downloads/* /opt/hiroleague/cache/downloads/
fi
run "uv" ok "" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
# The documented Linux install: the processor-only torch (uv's torch backend), never PyPI's with NVIDIA's ~2 GB
run "core (uv tool install)" ok "" uv tool install --python 3.12 --torch-backend cpu "$BUNDLE/hiroleague/hiroserver/hiroleague"
check "torch is the processor-only build" sh -c '"$(uv tool dir)/hiroleague/bin/python" -c "import torch, sys; sys.exit(not torch.__version__.endswith(\"+cpu\"))" && ! ls -d "$(uv tool dir)"/hiroleague/lib/python3.12/site-packages/nvidia* >/dev/null 2>&1'
# As a person does: `hiro service install` says to run it again through sudo, with its full path
run "service install (asks for sudo)" fails "needs root" hiro service install --name "$NAME"
run "service install" ok "" sudo "$(command -v hiro)" service install --name "$NAME"
sleep 60  # a service that fails at start restarts in this time
check "service still runs after 60 s" sh -c 'systemctl is-active hiro && [ "$(systemctl show hiro -p NRestarts --value)" = 0 ]'

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
# The service's channels live in the Hiro home, never as the service account's own uv tools
check "WhatsApp is in the Hiro home" sh -c 'test -x /opt/hiroleague/channels/bin/hiro-channel-whatsapp && ! test -e "$(uv tool dir)/hiro-channel-whatsapp"'
run "WhatsApp upgrade" ok "Upgraded" hiro extension upgrade whatsapp
run "WhatsApp remove" ok "Removed" hiro extension remove whatsapp
check "WhatsApp left the Hiro home" sh -c '! test -e /opt/hiroleague/channels/tools/hiro-channel-whatsapp'
run "devices refused" fails "comes with the core" hiro extension install devices

check "core announces its address" sh -c 'hiro logs search "announcing on" --json | grep -m1 "announcing on"'
# avahi's own resolver asks the LAN as any other machine would (getent would need nss-mdns, which the core never uses)
check "$NAME.local resolves" sh -c "command -v avahi-resolve >/dev/null || { echo 'avahi isn'\''t installed: nothing announces the name'; exit 1; }; avahi-resolve -4 -n $NAME.local | grep ."
check "front door answers $NAME.local" sh -c "curl -s -o /dev/null -w '%{http_code}' --resolve $NAME.local:80:127.0.0.1 http://$NAME.local/ | grep -E '^[23]'"
check "problems in the logs" sh -c "hiro logs problems --since 2h --json | python3 '$BUNDLE/read_logs.py' problems"
check "service log has no error" sh -c "sudo journalctl -u hiro --no-pager | python3 '$BUNDLE/read_logs.py' service"

# The result
{
  echo "# Fresh install: Linux ($(. /etc/os-release; echo "$PRETTY_NAME"), ${FRESH_MACHINE:-WSL})"
  echo
  echo "$(date '+%a, %b %-d, %-I:%M %p') · core $(cat "$BUNDLE/COMMIT" 2>/dev/null)"
  echo
  echo "| | Step | Took | Detail | Log |"
  echo "|---|---|---|---|---|"
  for s in "${STEPS[@]}"; do
    IFS='|' read -r name ok took detail log <<<"$s"
    echo "| $([ "$ok" = yes ] && echo PASS || echo '**FAIL**') | $name | ${took} s | $detail | [log]($log) |"
  done
} >"$RESULTS/result.md"
printf '%s\n' "${STEPS[@]}" | python3 -c '
import json, sys
rows = [dict(zip(("step", "ok", "seconds", "detail", "log"), line.rstrip("\n").split("|"))) for line in sys.stdin]
for r in rows:
    r["ok"], r["seconds"] = r["ok"] == "yes", int(r["seconds"])
json.dump({"system": "linux", "passed": all(r["ok"] for r in rows), "steps": rows}, sys.stdout, indent=2)' \
  >"$RESULTS/result.json"
echo "done" >"$RESULTS/finished"
