#!/usr/bin/env bash
#
# teardown-vm.sh
# Stop and destroy the HAOS VM created by scripts/haos/provision-vm.sh.
# Intended for development / test VMs only.
#
# Leaves the cached qcow2 image in /var/lib/vz/template/iso/ on the
# Proxmox host so the next provision run is fast. Remove manually if you
# want the disk back:
#   ssh pve 'rm /var/lib/vz/template/iso/haos_ova-*.qcow2'
#
# Usage:
#   ./scripts/haos/teardown-vm.sh               # VMID=106, PVE_HOST=pve
#   VMID=107 ./scripts/haos/teardown-vm.sh      # different VMID
#   FORCE=1 ./scripts/haos/teardown-vm.sh       # no confirmation

set -euo pipefail

PVE_HOST="${PVE_HOST:-pve}"
VMID="${VMID:-106}"
FORCE="${FORCE:-0}"

# Check that the VM exists; if it doesn't, we're already done.
if ! ssh "$PVE_HOST" "qm status $VMID >/dev/null 2>&1"; then
  echo "VM $VMID does not exist on $PVE_HOST. Nothing to do." >&2
  exit 0
fi

STATUS=$(ssh "$PVE_HOST" "qm config $VMID 2>/dev/null | grep -E '^(name|memory|scsi0):' | head -5")
echo "About to destroy VM $VMID on $PVE_HOST:" >&2
echo "$STATUS" | sed 's/^/  /' >&2

if [[ "$FORCE" != "1" ]]; then
  read -r -p "Type the VMID ($VMID) to confirm destruction: " ack
  if [[ "$ack" != "$VMID" ]]; then
    echo "Aborted." >&2
    exit 1
  fi
fi

ssh "$PVE_HOST" "qm stop $VMID --skiplock 1 >/dev/null 2>&1 || true"
ssh "$PVE_HOST" "qm destroy $VMID --purge 1 --skiplock 1"
echo "Destroyed VM $VMID." >&2
