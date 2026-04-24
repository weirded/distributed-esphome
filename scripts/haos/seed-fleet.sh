#!/usr/bin/env bash
#
# seed-fleet.sh
# Copy a minimal ESPHome fixture fleet from a source HA host (default
# hass-4) into the HAOS test VM's /config/esphome/ directory, so the
# e2e-hass-4 Playwright suite has something to compile against.
#
# HT.13a: without a fleet seeded onto blank HAOS, 4 of the 13 e2e-hass-4
# specs fail because they reference targets (cyd-office-info.yaml,
# garage-door-big.yaml) that don't exist. The specs are already
# HASS4_TARGET-env-overridable, so push-to-haos.sh points them at
# cyd-world-clock.yaml — the "other CYD" on the LAN, chosen so HAOS and
# hass-4 smoke runs don't race on the same physical device.
#
# Transport identical to install-addon.sh: ssh source-host streams a
# tarball, scp to pve, chunked pvesh agent/file-write into the guest,
# tar-extract on guest. SSH multiplexing (ControlMaster) avoids the
# fail2ban lockout we hit during the first HT.13 real-VM run.
#
# Prerequisites:
#   - Test VM provisioned (scripts/haos/provision-vm.sh)
#   - SSH access to both the source host and the Proxmox host
#   - Source files exist at $FLEET_SOURCE_DIR/<each file in FLEET_TARGETS>
#
# Usage:
#   scripts/haos/seed-fleet.sh                          # defaults
#   FLEET_SOURCE=repo scripts/haos/seed-fleet.sh        # use repo-committed
#                                                         scrubbed fixture
#                                                         (HT.13c)
#   FLEET_SOURCE_HOST=other-hass scripts/haos/seed-fleet.sh
#   FLEET_TARGETS='cyd-world-clock.yaml' scripts/haos/seed-fleet.sh  # minimal
#
# Env overrides:
#   PVE_HOST           (default pve)
#   VMID               (default 106)
#   FLEET_SOURCE       (default hass-4)            — 'hass-4' pulls live
#                                                    via ssh; 'repo' uses
#                                                    tests/fixtures/haos-fleet/
#                                                    committed with the repo
#                                                    (HT.13c — no SSH reach
#                                                    to hass-4 required, for
#                                                    CI + contributors)
#   FLEET_SOURCE_HOST  (default hass-4)            — ssh alias of source,
#                                                    only used when
#                                                    FLEET_SOURCE=hass-4
#   FLEET_SOURCE_DIR   (default /usr/share/hassio/homeassistant/esphome)
#   FLEET_TARGETS      (default the four files HT.13a needs)
#   GUEST_ESPHOME_DIR  (default /mnt/data/supervisor/homeassistant/esphome)

set -euo pipefail

PVE_HOST="${PVE_HOST:-pve}"
VMID="${VMID:-106}"
PVE_NODE="${PVE_NODE:-}"
FLEET_SOURCE="${FLEET_SOURCE:-hass-4}"
FLEET_SOURCE_HOST="${FLEET_SOURCE_HOST:-hass-4}"
FLEET_SOURCE_DIR="${FLEET_SOURCE_DIR:-/usr/share/hassio/homeassistant/esphome}"
# Default set pinned to what cyd-office-info.spec.ts + the 4 TARGET_FILENAME
# specs need when HASS4_TARGET=cyd-world-clock.yaml. Extend as specs grow.
FLEET_TARGETS="${FLEET_TARGETS:-cyd-world-clock.yaml garage-door-big.yaml .common.yaml secrets.yaml}"
GUEST_ESPHOME_DIR="${GUEST_ESPHOME_DIR:-/mnt/data/supervisor/homeassistant/esphome}"

if [[ "$FLEET_SOURCE" != "repo" && "$FLEET_SOURCE" != "hass-4" ]]; then
  echo "FLEET_SOURCE must be 'repo' or 'hass-4' (got '$FLEET_SOURCE')" >&2
  exit 2
fi

REPO_FIXTURE_DIR="$(cd "$(dirname "$0")/../.." && pwd)/tests/fixtures/haos-fleet"

command -v python3 >/dev/null || { echo "python3 required locally" >&2; exit 2; }

# SSH multiplexing — one auth, many ops. See install-addon.sh for the
# history of why we don't leave this to bare `ssh` anymore. The source-
# host channel is only opened under FLEET_SOURCE=hass-4; FLEET_SOURCE=repo
# builds the tarball locally and never touches FLEET_SOURCE_HOST.
SSH_CTRL_PVE="$(mktemp -u -t pve-ssh.XXXXXX)"
SSH_CTRL_SRC="$(mktemp -u -t src-ssh.XXXXXX)"
SSH_OPTS_PVE=(-o ControlMaster=auto -o ControlPath="$SSH_CTRL_PVE" -o ControlPersist=60s)
SSH_OPTS_SRC=(-o ControlMaster=auto -o ControlPath="$SSH_CTRL_SRC" -o ControlPersist=60s)
cleanup_ssh() {
  ssh "${SSH_OPTS_PVE[@]}" -O exit "$PVE_HOST" 2>/dev/null || true
  if [[ "$FLEET_SOURCE" == "hass-4" ]]; then
    ssh "${SSH_OPTS_SRC[@]}" -O exit "$FLEET_SOURCE_HOST" 2>/dev/null || true
  fi
  rm -f "$SSH_CTRL_PVE" "$SSH_CTRL_SRC"
}
trap cleanup_ssh EXIT

pve_ssh() { ssh "${SSH_OPTS_PVE[@]}" "$@"; }
pve_scp() { scp "${SSH_OPTS_PVE[@]}" "$@"; }
src_ssh() { ssh "${SSH_OPTS_SRC[@]}" "$@"; }

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

if [[ -z "$PVE_NODE" ]]; then
  PVE_NODE=$(ssh "$PVE_HOST" "pvesh get /nodes --output-format json" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['node'])" 2>/dev/null) \
    || { echo "Couldn't auto-detect PVE_NODE; set PVE_NODE explicitly" >&2; exit 3; }
fi

# Warm the multiplex sockets so later calls don't race. Only the
# source-host channel is conditional — the pve channel is always used.
pve_ssh "$PVE_HOST" true
if [[ "$FLEET_SOURCE" == "hass-4" ]]; then
  src_ssh "$FLEET_SOURCE_HOST" true
fi

# --- 1. Build (or pull) the fleet tarball --------------------------------

TARBALL=$(mktemp -t haos_fleet.XXXXXX).tar
trap 'rm -f "$TARBALL"; cleanup_ssh' EXIT

if [[ "$FLEET_SOURCE" == "repo" ]]; then
  log "Packing fleet from repo fixture at $REPO_FIXTURE_DIR"
  log "  Files: $FLEET_TARGETS"
  if [[ ! -d "$REPO_FIXTURE_DIR" ]]; then
    echo "Repo fixture dir missing: $REPO_FIXTURE_DIR" >&2
    echo "Either check out the tests/fixtures/haos-fleet/ directory from the repo, or rerun with FLEET_SOURCE=hass-4." >&2
    exit 4
  fi
  # Same tar shape as the hass-4 path: explicit file list, dotfiles
  # preserved, no --wildcards dance.
  # shellcheck disable=SC2086  # we WANT word-splitting of FLEET_TARGETS
  tar cf "$TARBALL" -C "$REPO_FIXTURE_DIR" $FLEET_TARGETS
else
  log "Pulling fleet files from $FLEET_SOURCE_HOST:$FLEET_SOURCE_DIR"
  log "  Files: $FLEET_TARGETS"
  # Build the tar on the source host and stream it back. Preserving dot-files
  # (e.g. .common.yaml) is default for explicit file lists — no --wildcards
  # hack needed. --ignore-failed-read gives us a clear error below if a file
  # the test suite expects has been renamed or removed upstream.
  src_ssh "$FLEET_SOURCE_HOST" \
    "tar cf - -C '$FLEET_SOURCE_DIR' $FLEET_TARGETS" > "$TARBALL"
fi

if [[ ! -s "$TARBALL" ]]; then
  echo "Fleet tarball is empty — source=$FLEET_SOURCE, targets='$FLEET_TARGETS'" >&2
  exit 4
fi
log "Tarball size: $(du -h "$TARBALL" | awk '{print $1}')"

# --- 2. Stage on pve -----------------------------------------------------

REMOTE_STAGE="/tmp/haos_fleet-$$.tar"
log "Copying tarball to $PVE_HOST"
pve_scp -q "$TARBALL" "$PVE_HOST:$REMOTE_STAGE"

# --- 3. Clear stale chunks + chunked push into the guest -----------------

CHUNK_PREFIX="fleet"
log "Clearing any stale chunks on the guest from a previous run"
pve_ssh "$PVE_HOST" "PVE_NODE=$PVE_NODE VMID=$VMID bash -s" <<'REMOTE' >/dev/null
set -euo pipefail
TMPJSON=$(mktemp); trap 'rm -f "$TMPJSON"' EXIT
pvesh create "/nodes/$PVE_NODE/qemu/$VMID/agent/exec" \
  --command /bin/sh --command -c --command 'rm -f /tmp/fleet.*' \
  --output-format json > "$TMPJSON"
PID=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1]))['pid'])" "$TMPJSON")
for _ in $(seq 1 30); do
  pvesh get "/nodes/$PVE_NODE/qemu/$VMID/agent/exec-status" \
    --pid "$PID" --output-format json > "$TMPJSON"
  python3 -c "import sys,json; sys.exit(0 if json.load(open(sys.argv[1])).get('exited') else 1)" "$TMPJSON" && exit 0
  sleep 1
done
exit 124
REMOTE

log "Pushing tarball to VM $VMID via qga file-write (chunked)"
pve_ssh "$PVE_HOST" bash -s "$PVE_NODE" "$VMID" "$REMOTE_STAGE" "$CHUNK_PREFIX" <<'REMOTE'
set -euo pipefail
PVE_NODE="$1"
VMID="$2"
SRC="$3"
PREFIX="$4"
CHUNK_DIR=$(mktemp -d)
trap 'rm -rf "$CHUNK_DIR" "$SRC"' EXIT
split -b 40000 -a 3 -d "$SRC" "$CHUNK_DIR/$PREFIX."
for f in "$CHUNK_DIR/$PREFIX".*; do
  name=$(basename "$f")
  B64=$(base64 -w0 < "$f")
  pvesh create "/nodes/$PVE_NODE/qemu/$VMID/agent/file-write" \
    --encode 0 --file "/tmp/$name" --content "$B64" >/dev/null
done
REMOTE

# --- 4. Reassemble + extract on the guest --------------------------------

log "Extracting into $GUEST_ESPHOME_DIR"
pve_ssh "$PVE_HOST" "PVE_NODE=$PVE_NODE VMID=$VMID GUEST_ESPHOME_DIR=$GUEST_ESPHOME_DIR CHUNK_PREFIX=$CHUNK_PREFIX bash -s" <<'REMOTE' >/dev/null
set -euo pipefail
TMPJSON=$(mktemp); trap 'rm -f "$TMPJSON"' EXIT

SCRIPT="
set -e
mkdir -p $GUEST_ESPHOME_DIR
cat /tmp/${CHUNK_PREFIX}.* > /tmp/${CHUNK_PREFIX}.tar
tar xf /tmp/${CHUNK_PREFIX}.tar -C $GUEST_ESPHOME_DIR
rm -f /tmp/${CHUNK_PREFIX}.* /tmp/${CHUNK_PREFIX}.tar
ls -1 $GUEST_ESPHOME_DIR
"

pvesh create "/nodes/$PVE_NODE/qemu/$VMID/agent/exec" \
  --command /bin/sh --command -c --command "$SCRIPT" \
  --output-format json > "$TMPJSON"
PID=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1]))['pid'])" "$TMPJSON")
for _ in $(seq 1 60); do
  pvesh get "/nodes/$PVE_NODE/qemu/$VMID/agent/exec-status" \
    --pid "$PID" --output-format json > "$TMPJSON"
  if python3 -c "import sys,json; sys.exit(0 if json.load(open(sys.argv[1])).get('exited') else 1)" "$TMPJSON"; then
    python3 - "$TMPJSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
if d.get("out-data"): sys.stdout.write(d["out-data"])
if d.get("err-data"): sys.stderr.write(d["err-data"])
sys.exit(d.get("exitcode", 0))
PY
    exit $?
  fi
  sleep 1
done
exit 124
REMOTE

log "Fleet seeded — $GUEST_ESPHOME_DIR now carries the fixture set"
