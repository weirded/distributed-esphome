#!/usr/bin/env bash
#
# provision-vm.sh
# Provision a Home Assistant OS VM on a Proxmox host, non-interactively.
# Counterpart of push-to-hass-4.sh's always-on hass-4 box: this one stands
# up a throwaway clean-HAOS VM so HT.13 can regression-guard the fresh-
# install path (bug #82 — Supervisor's builder-image pull from Docker Hub
# fails on fresh HAOS boxes; IM.1/IM.2 moved us to a prebuilt GHCR image,
# and this VM is how we prove the prebuilt path keeps working).
#
# Scripts in scripts/haos/ are modeled on ha-outback-mate3's scripts/
# directory (same Proxmox qga mechanics, same VMID default) so running
# two projects' test VMs on one Proxmox node means overriding VMID, not
# re-learning the pipeline.
#
# The `qm` invocation mirrors the community-maintained installer at
#   https://community-scripts.github.io/ProxmoxVE/scripts?id=haos-vm
# (github.com/community-scripts/ProxmoxVE vm/haos-vm.sh), minus the
# whiptail UI — every parameter is driven by env var / default.
#
# Run from anywhere that can SSH to the Proxmox host. All settings
# override via environment.
#
# Exit codes:
#   0  success
#   2  not a Proxmox host (qm missing)
#   3  VMID already in use
#   4  couldn't resolve HA OS version
#   5  disk import produced no reference

set -euo pipefail

PVE_HOST="${PVE_HOST:-pve}"
VMID="${VMID:-106}"
VMNAME="${VMNAME:-haos-test}"
STORAGE="${STORAGE:-sata-ssd}"
BRIDGE="${BRIDGE:-vmbr0}"
MEM_MB="${MEM_MB:-3072}"
CORES="${CORES:-2}"
DISK_SIZE="${DISK_SIZE:-32G}"
HAOS_VERSION="${HAOS_VERSION:-}"
IMAGE_CACHE="${IMAGE_CACHE:-/var/lib/vz/template/iso}"
START_AFTER_PROVISION="${START_AFTER_PROVISION:-1}"

# Deterministic MAC derived from VMID so DHCP keeps handing out the same IP
# across re-provisions. `02:` prefix marks it as locally-administered; `AD:DA`
# is a project-scoped tag ("AddON"); last 3 bytes are the VMID in hex.
# Matches ha-outback-mate3's scheme by design — two projects testing on the
# same Proxmox node pick distinct VMIDs, and MACs (and therefore DHCP leases)
# stay stable per-VMID regardless of which project provisioned it.
if [[ -z "${MAC:-}" ]]; then
  printf -v _mac_tail "%06X" "$VMID"
  MAC="02:AD:DA:${_mac_tail:0:2}:${_mac_tail:2:2}:${_mac_tail:4:2}"
fi

log() { printf '[%(%H:%M:%S)T] %s\n' -1 "$*" >&2; }

# Everything below runs on the Proxmox host over SSH.
ssh "$PVE_HOST" \
  VMID="$VMID" VMNAME="$VMNAME" STORAGE="$STORAGE" BRIDGE="$BRIDGE" \
  MEM_MB="$MEM_MB" CORES="$CORES" DISK_SIZE="$DISK_SIZE" \
  HAOS_VERSION="$HAOS_VERSION" IMAGE_CACHE="$IMAGE_CACHE" \
  MAC="$MAC" START_AFTER_PROVISION="$START_AFTER_PROVISION" \
  bash -s <<'REMOTE'
set -euo pipefail

log() { printf '[%(%H:%M:%S)T] %s\n' -1 "$*" >&2; }

command -v qm >/dev/null || { echo "qm not found; this script must run on a Proxmox host" >&2; exit 2; }

if qm status "$VMID" >/dev/null 2>&1; then
  echo "VMID $VMID already exists; pick another VMID or destroy it first." >&2
  exit 3
fi

# --- Resolve HA OS version + URL ------------------------------------------

if [[ -z "$HAOS_VERSION" ]]; then
  log "Resolving latest stable HA OS version"
  HAOS_VERSION=$(
    curl -fsSL https://raw.githubusercontent.com/home-assistant/version/master/stable.json \
      | grep '"ova"' | cut -d '"' -f 4
  )
  [[ -n "$HAOS_VERSION" ]] || { echo "Couldn't resolve HA OS version" >&2; exit 4; }
fi
HAOS_URL="https://github.com/home-assistant/operating-system/releases/download/${HAOS_VERSION}/haos_ova-${HAOS_VERSION}.qcow2.xz"
COMPRESSED_NAME="haos_ova-${HAOS_VERSION}.qcow2.xz"
DECOMPRESSED_NAME="haos_ova-${HAOS_VERSION}.qcow2"
IMAGE_PATH="${IMAGE_CACHE}/${DECOMPRESSED_NAME}"

mkdir -p "$IMAGE_CACHE"

if [[ ! -f "$IMAGE_PATH" ]]; then
  log "Downloading $HAOS_URL"
  curl -fL --progress-bar "$HAOS_URL" -o "${IMAGE_CACHE}/${COMPRESSED_NAME}"
  log "Decompressing"
  xz -d "${IMAGE_CACHE}/${COMPRESSED_NAME}"
else
  log "Reusing cached $IMAGE_PATH"
fi

# --- Safety net: clean up partial VM on error ------------------------------

cleanup_on_error() {
  local rc=$?
  if (( rc != 0 )) && qm status "$VMID" >/dev/null 2>&1; then
    log "Error (rc=$rc); destroying partial VM $VMID"
    qm stop "$VMID" --skiplock 1 >/dev/null 2>&1 || true
    qm destroy "$VMID" --purge 1 --skiplock 1 >/dev/null 2>&1 || true
  fi
  exit $rc
}
trap cleanup_on_error ERR

# --- Create VM shell -------------------------------------------------------

log "Creating VM $VMID ($VMNAME) on $STORAGE, ${MEM_MB}MB RAM, ${CORES} cores, MAC $MAC, HAOS $HAOS_VERSION"
qm create "$VMID" \
  -machine q35 \
  -bios ovmf \
  -tablet 0 \
  -localtime 1 \
  -agent 1 \
  -cores "$CORES" \
  -memory "$MEM_MB" \
  -name "$VMNAME" \
  -tags "distributed-esphome,test" \
  -net0 "virtio,bridge=${BRIDGE},macaddr=${MAC}" \
  -onboot 0 \
  -ostype l26 \
  -scsihw virtio-scsi-pci \
  -serial0 socket

# --- Import the HAOS disk --------------------------------------------------

log "Importing HA OS disk → $STORAGE"
# Prefer modern `qm disk import` where available, fall back to legacy.
if qm disk import --help >/dev/null 2>&1; then
  IMPORT_CMD=(qm disk import)
else
  IMPORT_CMD=(qm importdisk)
fi
IMPORT_OUT="$("${IMPORT_CMD[@]}" "$VMID" "$IMAGE_PATH" "$STORAGE" --format raw 2>&1 || true)"
DISK_REF="$(printf '%s\n' "$IMPORT_OUT" \
  | sed -n "s/.*successfully imported disk '\([^']\+\)'.*/\1/p" \
  | tr -d "\r\"'")"
if [[ -z "$DISK_REF" ]]; then
  # Fallback: find the disk in storage by VMID
  DISK_REF="$(pvesm list "$STORAGE" \
    | awk -v id="$VMID" '$5 ~ ("vm-"id"-disk-") {print $1":"$5}' \
    | sort | tail -n1)"
fi
if [[ -z "$DISK_REF" ]]; then
  echo "Unable to determine imported disk reference." >&2
  echo "$IMPORT_OUT" >&2
  exit 5
fi
log "Imported: $DISK_REF"

# --- Attach EFI vars disk + root disk in a single qm set ------------------
# NOTE: pre-enrolled-keys is intentionally NOT set. Enabling it turns on
# Secure Boot with Microsoft-signed keys; HA OS isn't signed with those and
# the firmware rejects the boot volume with "Access Denied".

log "Attaching EFI vars + root disk, setting boot order"
qm set "$VMID" \
  --efidisk0 "${STORAGE}:0,efitype=4m" \
  --scsi0 "${DISK_REF},ssd=1,discard=on" \
  --boot order=scsi0

log "Resizing root disk to ${DISK_SIZE}"
qm resize "$VMID" scsi0 "${DISK_SIZE}"

trap - ERR

if [[ "$START_AFTER_PROVISION" == "1" ]]; then
  log "Starting VM $VMID"
  qm start "$VMID"
fi

cat >&2 <<EOF

Done. VM $VMID ($VMNAME) created.

  - Proxmox web UI:  VM $VMID → Console   (first boot takes ~5 min)
  - Home Assistant:  http://homeassistant.local:8123 once booted
                     (or the IP DHCP assigned for MAC $MAC)

Next steps:
  1. Wait for HA to come up (~5 min on first boot).
  2. Run scripts/haos/onboard.sh to complete onboarding + mint a token.
  3. Run push-to-haos.sh for deploy + smoke.

Start over with:   scripts/haos/teardown-vm.sh

EOF
REMOTE
