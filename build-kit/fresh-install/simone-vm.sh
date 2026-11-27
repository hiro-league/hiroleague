#!/usr/bin/env bash
# One throwaway virtual machine on Simone, run by fresh.py (`fresh.py simone`): a distribution's official cloud image,
# a person with sudo, the bundle copied in, run-linux.sh run inside, its result copied out, the machine deleted.
#
#     simone-vm.sh <distro> <run> [--keep]
#
# Runs as Michel's account through libvirt (the libvirt group: no sudo). It only ever makes, stops and deletes what it
# names hiro-fresh-*: never another machine (Home Assistant's haos) or volume. One machine at a time, 2 CPUs and 4 GB,
# on libvirt's NAT network (default): the house's LAN never sees it.
set -euo pipefail
DISTRO="$1"
RUN="$2"
KEEP="${3:-}"
ROOT="$HOME/hiro-fresh"
HERE="$ROOT/runs/$RUN"
VM="hiro-fresh-$RUN"
BASE="hiro-fresh-base-$DISTRO"
POOL=images
CONN=qemu:///system
MEMORY_MB=4096
CPUS=2
DISK_GB=40
NAME=hirofresh  # the core's name inside, as run-linux.sh gives it
SSH_OPTS=(-i "$HERE/key" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5)

say() { printf '[simone] %s\n' "$*"; }
v() { virsh -q -c "$CONN" "$@"; }

[[ "$VM" == hiro-fresh-* ]] || { echo "refusing a machine not named hiro-fresh-*: $VM" >&2; exit 2; }

image_url() {
  case "$1" in
    ubuntu-24.04) echo https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img ;;
    ubuntu-22.04) echo https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img ;;
    debian-13) echo https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2 ;;
    fedora-45)
      local base=https://download.fedoraproject.org/pub/fedora/linux/releases/45/Cloud/x86_64/images/
      echo "$base$(curl -fsL "$base" | grep -oE 'Fedora-Cloud-Base-Generic-[^"]+\.qcow2' | head -1)" ;;
    rocky-10) echo https://dl.rockylinux.org/pub/rocky/10/images/x86_64/Rocky-10-GenericCloud-Base.latest.x86_64.qcow2 ;;
    *) echo "unknown distribution: $1 (ubuntu-24.04, ubuntu-22.04, debian-13, fedora-45, rocky-10)" >&2; return 1 ;;
  esac
}

cleanup() {
  if [ "$KEEP" = --keep ]; then
    say "Kept: $VM at ${IP:-?} (ssh ${SSH_OPTS[*]} person@${IP:-?}); remove it: virsh destroy $VM; virsh undefine $VM; virsh vol-delete $VM.qcow2 --pool $POOL; virsh vol-delete $VM-seed.iso --pool $POOL"
    return
  fi
  v destroy "$VM" >/dev/null 2>&1 || true
  v undefine "$VM" >/dev/null 2>&1 || true
  v vol-delete "$VM.qcow2" --pool "$POOL" >/dev/null 2>&1 || true
  v vol-delete "$VM-seed.iso" --pool "$POOL" >/dev/null 2>&1 || true
  rm -f "$HERE/key" "$HERE/key.pub" "$HERE/bundle.tar"
  say "Removed $VM"
}

# The distribution's image, once: downloaded, then a libvirt volume each run's disk starts from
if ! v vol-info "$BASE" --pool "$POOL" >/dev/null 2>&1; then
  mkdir -p "$ROOT/images"
  url="$(image_url "$DISTRO")"
  say "First run of $DISTRO: downloading $url"
  curl -fL --retry 3 -o "$ROOT/images/$DISTRO.part" "$url"
  mv "$ROOT/images/$DISTRO.part" "$ROOT/images/$DISTRO.qcow2"
  v vol-create-as "$POOL" "$BASE" "$(stat -c%s "$ROOT/images/$DISTRO.qcow2")" --format raw >/dev/null
  v vol-upload "$BASE" "$ROOT/images/$DISTRO.qcow2" --pool "$POOL"
  v pool-refresh "$POOL" >/dev/null  # libvirt reads the image's own format (qcow2)
  rm -f "$ROOT/images/$DISTRO.qcow2"
fi

trap cleanup EXIT

# The person (sudo without a password: the only shortcut, as in WSL) and this run's own key
ssh-keygen -q -t ed25519 -N "" -C "$VM" -f "$HERE/key"
mkdir -p "$HERE/seed"
cat >"$HERE/seed/user-data" <<EOF
#cloud-config
users:
  - name: person
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat "$HERE/key.pub")
EOF
printf 'instance-id: %s\nlocal-hostname: fresh\n' "$VM" >"$HERE/seed/meta-data"
xorriso -as mkisofs -quiet -o "$HERE/seed.iso" -V cidata -J -r "$HERE/seed/user-data" "$HERE/seed/meta-data"
v vol-create-as "$POOL" "$VM-seed.iso" "$(stat -c%s "$HERE/seed.iso")" --format raw >/dev/null
v vol-upload "$VM-seed.iso" "$HERE/seed.iso" --pool "$POOL"
v vol-create-as "$POOL" "$VM.qcow2" "${DISK_GB}G" --format qcow2 --backing-vol "$BASE" --backing-vol-format qcow2 >/dev/null

say "Starting $VM ($DISTRO, $CPUS CPUs, $((MEMORY_MB / 1024)) GB, libvirt's NAT network)"
virt-install -q --connect "$CONN" --name "$VM" --memory "$MEMORY_MB" --vcpus "$CPUS" \
  --disk "vol=$POOL/$VM.qcow2,bus=virtio" --disk "vol=$POOL/$VM-seed.iso,device=cdrom" \
  --import --osinfo detect=on,require=off --network network=default,model=virtio \
  --graphics none --noautoconsole

IP=""
for _ in $(seq 1 60); do
  IP="$(v domifaddr "$VM" --source lease 2>/dev/null | awk '/ipv4/ {sub("/.*", "", $4); print $4; exit}')"
  [ -n "$IP" ] && break
  sleep 5
done
[ -n "$IP" ] || { say "$VM got no address in 5 min"; exit 1; }
for _ in $(seq 1 60); do ssh "${SSH_OPTS[@]}" "person@$IP" true 2>/dev/null && break; sleep 5; done
ssh "${SSH_OPTS[@]}" "person@$IP" 'cloud-init status --wait >/dev/null; . /etc/os-release; echo "up: $PRETTY_NAME"' \
  | sed 's/^/[simone] /'

scp "${SSH_OPTS[@]}" -q "$HERE/bundle.tar" "person@$IP:bundle.tar"
ssh "${SSH_OPTS[@]}" "person@$IP" 'mkdir -p hiro-test && tar -xf bundle.tar -C hiro-test && rm bundle.tar'
say "The person's path (its output below)"
ssh "${SSH_OPTS[@]}" "person@$IP" "FRESH_MACHINE='a VM on Simone' bash hiro-test/run-linux.sh \$HOME/hiro-test \$HOME/results" \
  </dev/null || true
scp "${SSH_OPTS[@]}" -q -r "person@$IP:results" "$HERE/"

# Another machine asks for the name: Simone itself, on the NAT network the machine announces on
if [ -f "$HERE/results/result.json" ]; then
  if host="$(avahi-resolve -4 -n "$NAME.local" 2>&1)" && [ -n "$host" ]; then ok=yes; else ok=no; fi
  printf '$ avahi-resolve -4 -n %s.local   (on Simone)\n%s\n' "$NAME" "$host" >"$HERE/results/logs/99-another-machine-resolves.log"
  python3 - "$HERE/results" "$ok" "$NAME" <<'PY'
import json, sys
from pathlib import Path
results, ok, name = Path(sys.argv[1]), sys.argv[2] == "yes", sys.argv[3]
step = {"step": f"Simone resolves {name}.local", "ok": ok, "seconds": 0,
        "detail": "as expected" if ok else "see its log", "log": "logs/99-another-machine-resolves.log"}
summary = json.loads((results / "result.json").read_text())
summary["steps"].append(step)
summary["passed"] = all(s["ok"] for s in summary["steps"])
(results / "result.json").write_text(json.dumps(summary, indent=2))
with (results / "result.md").open("a") as f:
    f.write(f"| {'PASS' if ok else '**FAIL**'} | {step['step']} | 0 s | {step['detail']} | [log]({step['log']}) |\n")
PY
  printf '%s %-34s %s\n' "$([ $ok = yes ] && echo PASS || echo FAIL)" "Simone resolves $NAME.local" "$host"
fi
