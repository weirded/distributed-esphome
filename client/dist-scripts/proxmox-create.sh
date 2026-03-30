#!/usr/bin/env bash
# ESPHome Distributed Build Client — Proxmox LXC container setup
#
# Creates a Proxmox LXC container with Docker, loads the client image,
# and starts the build client. Run this on the Proxmox host.
#
# Usage:
#   ./proxmox-create.sh
#
# Required environment variables:
#   SERVER_URL     — e.g. http://192.168.1.100:8765
#   SERVER_TOKEN   — shared auth token
#
# Optional environment variables:
#   CTID           — container ID (default: next available)
#   CT_HOSTNAME    — container hostname (default: esphome-builder)
#   CT_MEMORY      — memory in MB (default: 2048)
#   CT_CORES       — CPU cores (default: 2)
#   CT_DISK        — root disk size (default: 16G)
#   CT_STORAGE     — Proxmox storage for rootfs (default: local-lvm)
#   CT_BRIDGE      — network bridge (default: vmbr0)
#   CT_TEMPLATE    — LXC template (default: auto-detect Debian 12)
#   MAX_PARALLEL_JOBS — concurrent build workers (default: 2)

set -euo pipefail

# ── Validate required env vars ──────────────────────────────────────
if [ -z "${SERVER_URL:-}" ]; then
    echo "ERROR: SERVER_URL is required." >&2
    exit 1
fi
if [ -z "${SERVER_TOKEN:-}" ]; then
    echo "ERROR: SERVER_TOKEN is required." >&2
    exit 1
fi

# ── Configuration ───────────────────────────────────────────────────
CT_HOSTNAME="${CT_HOSTNAME:-esphome-builder}"
CT_MEMORY="${CT_MEMORY:-2048}"
CT_CORES="${CT_CORES:-2}"
CT_DISK="${CT_DISK:-16}"
CT_STORAGE="${CT_STORAGE:-local-lvm}"
CT_BRIDGE="${CT_BRIDGE:-vmbr0}"
MAX_PARALLEL_JOBS="${MAX_PARALLEL_JOBS:-2}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Find next available CTID if not specified ───────────────────────
if [ -z "${CTID:-}" ]; then
    CTID=$(pvesh get /cluster/nextid)
    echo "Using next available CTID: $CTID"
fi

# ── Find Debian 12 template ────────────────────────────────────────
if [ -z "${CT_TEMPLATE:-}" ]; then
    # Try to find a cached Debian 12 template
    CT_TEMPLATE=$(pveam list local 2>/dev/null | grep -i "debian-12" | head -1 | awk '{print $1}' || true)
    if [ -z "$CT_TEMPLATE" ]; then
        echo "==> Downloading Debian 12 template ..."
        pveam update
        CT_TEMPLATE=$(pveam available --section system | grep -i "debian-12-standard" | tail -1 | awk '{print $2}')
        if [ -z "$CT_TEMPLATE" ]; then
            echo "ERROR: Could not find a Debian 12 template. Set CT_TEMPLATE manually." >&2
            exit 1
        fi
        pveam download local "$CT_TEMPLATE"
        CT_TEMPLATE="local:vztmpl/$CT_TEMPLATE"
    fi
    echo "Using template: $CT_TEMPLATE"
fi

# ── Create the container ───────────────────────────────────────────
echo "==> Creating LXC container $CTID ($CT_HOSTNAME) ..."
pct create "$CTID" "$CT_TEMPLATE" \
    --hostname "$CT_HOSTNAME" \
    --memory "$CT_MEMORY" \
    --cores "$CT_CORES" \
    --rootfs "${CT_STORAGE}:${CT_DISK}" \
    --net0 "name=eth0,bridge=${CT_BRIDGE},ip=dhcp" \
    --features "nesting=1,keyctl=1" \
    --unprivileged 1 \
    --onboot 1 \
    --start 0

# ── Start the container ───────────────────────────────────────────
echo "==> Starting container ..."
pct start "$CTID"

# Wait for container to be ready
echo "==> Waiting for container to boot ..."
sleep 5
for i in $(seq 1 30); do
    if pct exec "$CTID" -- test -f /etc/os-release 2>/dev/null; then
        break
    fi
    sleep 1
done

# ── Install Docker inside the container ────────────────────────────
echo "==> Installing Docker in container $CTID ..."
pct exec "$CTID" -- bash -c "
    set -e
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg >/dev/null 2>&1
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo 'deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \$(. /etc/os-release && echo \$VERSION_CODENAME) stable' > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io >/dev/null 2>&1
    systemctl enable docker
    systemctl start docker
    echo 'Docker installed successfully.'
"

# ── Copy and load the client image ─────────────────────────────────
IMAGE_TAR="$SCRIPT_DIR/esphome-dist-client.tar"
if [ ! -f "$IMAGE_TAR" ]; then
    echo "ERROR: $IMAGE_TAR not found. Run this from the extracted client package directory." >&2
    exit 1
fi

echo "==> Copying Docker image to container ..."
pct push "$CTID" "$IMAGE_TAR" /tmp/esphome-dist-client.tar

echo "==> Loading Docker image in container ..."
pct exec "$CTID" -- docker load -i /tmp/esphome-dist-client.tar
pct exec "$CTID" -- rm /tmp/esphome-dist-client.tar

# ── Start the client ──────────────────────────────────────────────
echo "==> Starting ESPHome build client ..."
pct exec "$CTID" -- docker run -d \
    --name esphome-dist-client \
    --restart unless-stopped \
    --hostname "$CT_HOSTNAME" \
    -e "SERVER_URL=$SERVER_URL" \
    -e "SERVER_TOKEN=$SERVER_TOKEN" \
    -e "MAX_PARALLEL_JOBS=$MAX_PARALLEL_JOBS" \
    -e "HOST_PLATFORM=Proxmox LXC (Debian 12)" \
    -v esphome-versions:/esphome-versions \
    esphome-dist-client

echo ""
echo "==> Done! ESPHome build client running in Proxmox container $CTID ($CT_HOSTNAME)"
echo ""
echo "   Container ID:  $CTID"
echo "   Hostname:       $CT_HOSTNAME"
echo "   Server URL:     $SERVER_URL"
echo "   Workers:        $MAX_PARALLEL_JOBS"
echo ""
echo "   Manage:"
echo "     pct exec $CTID -- docker logs -f esphome-dist-client"
echo "     pct exec $CTID -- docker restart esphome-dist-client"
echo "     pct stop $CTID"
echo "     pct destroy $CTID"
