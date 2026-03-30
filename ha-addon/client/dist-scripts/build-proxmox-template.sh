#!/usr/bin/env bash
# Build a Proxmox LXC template with Docker + ESPHome build client baked in.
#
# Run this ON a Proxmox host. It creates a temporary container, installs
# Docker, loads the client image, adds a systemd service for auto-start,
# then converts the container to a reusable template.
#
# Usage:
#   ./build-proxmox-template.sh
#
# Output: /var/lib/vz/template/cache/esphome-dist-client-<version>.tar.zst
#
# To deploy from the template:
#   pct create <CTID> local:vztmpl/esphome-dist-client-<version>.tar.zst \
#     --hostname esphome-builder \
#     --memory 2048 --cores 2 \
#     --rootfs local-lvm:16 \
#     --net0 name=eth0,bridge=vmbr0,ip=dhcp \
#     --features nesting=1,keyctl=1 \
#     --unprivileged 1
#   pct set <CTID> -description "SERVER_URL=http://... SERVER_TOKEN=..."
#   # Edit /etc/esphome-dist-client.env inside the container before starting:
#   pct start <CTID>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/VERSION"
IMAGE_TAR="$SCRIPT_DIR/esphome-dist-client.tar"

if [ ! -f "$IMAGE_TAR" ]; then
    echo "ERROR: $IMAGE_TAR not found. Run this from the extracted client package directory." >&2
    exit 1
fi

VERSION="unknown"
[ -f "$VERSION_FILE" ] && VERSION="$(cat "$VERSION_FILE")"

TEMPLATE_NAME="esphome-dist-client-${VERSION}"
TEMPLATE_PATH="/var/lib/vz/template/cache/${TEMPLATE_NAME}.tar.zst"
TEMP_CTID=$(pvesh get /cluster/nextid)
CT_STORAGE="${CT_STORAGE:-local-lvm}"

echo "==> Building Proxmox LXC template v${VERSION} (temp CTID: $TEMP_CTID)"

# ── Find Debian 12 template ────────────────────────────────────────
BASE_TEMPLATE=$(pveam list local 2>/dev/null | grep -i "debian-12" | head -1 | awk '{print $1}' || true)
if [ -z "$BASE_TEMPLATE" ]; then
    echo "==> Downloading Debian 12 template ..."
    pveam update
    TPL_NAME=$(pveam available --section system | grep -i "debian-12-standard" | tail -1 | awk '{print $2}')
    if [ -z "$TPL_NAME" ]; then
        echo "ERROR: Could not find Debian 12 template." >&2
        exit 1
    fi
    pveam download local "$TPL_NAME"
    BASE_TEMPLATE="local:vztmpl/$TPL_NAME"
fi
echo "    Base template: $BASE_TEMPLATE"

# ── Create temp container ──────────────────────────────────────────
echo "==> Creating temporary container ..."
pct create "$TEMP_CTID" "$BASE_TEMPLATE" \
    --hostname "$TEMPLATE_NAME" \
    --memory 2048 \
    --cores 2 \
    --rootfs "${CT_STORAGE}:8" \
    --net0 "name=eth0,bridge=vmbr0,ip=dhcp" \
    --features "nesting=1,keyctl=1" \
    --unprivileged 1

pct start "$TEMP_CTID"
echo "==> Waiting for container to boot ..."
sleep 5
for i in $(seq 1 30); do
    pct exec "$TEMP_CTID" -- test -f /etc/os-release 2>/dev/null && break
    sleep 1
done

# ── Install Docker ─────────────────────────────────────────────────
echo "==> Installing Docker ..."
pct exec "$TEMP_CTID" -- bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg >/dev/null 2>&1
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io >/dev/null 2>&1
    systemctl enable docker
'

# ── Load client image ──────────────────────────────────────────────
echo "==> Loading client Docker image ..."
pct push "$TEMP_CTID" "$IMAGE_TAR" /opt/esphome-dist-client.tar
pct exec "$TEMP_CTID" -- docker load -i /opt/esphome-dist-client.tar
# Keep the tar so the image survives docker prune; systemd service loads it on boot
# Actually remove it to save space — the image is in Docker's storage now
pct exec "$TEMP_CTID" -- rm /opt/esphome-dist-client.tar

# ── Create env file and systemd service ────────────────────────────
echo "==> Creating systemd service ..."
pct exec "$TEMP_CTID" -- bash -c 'cat > /etc/esphome-dist-client.env << "ENVEOF"
# ESPHome Distributed Build Client configuration
# Edit these values, then: systemctl restart esphome-dist-client
SERVER_URL=http://YOUR_HA_HOST:8765
SERVER_TOKEN=YOUR_TOKEN
MAX_PARALLEL_JOBS=2
ENVEOF'

pct exec "$TEMP_CTID" -- bash -c 'cat > /etc/systemd/system/esphome-dist-client.service << "SVCEOF"
[Unit]
Description=ESPHome Distributed Build Client
After=docker.service
Requires=docker.service

[Service]
Type=simple
EnvironmentFile=/etc/esphome-dist-client.env
ExecStartPre=-/usr/bin/docker rm -f esphome-dist-client
ExecStart=/usr/bin/docker run --rm \
    --name esphome-dist-client \
    --hostname %H \
    -e SERVER_URL=${SERVER_URL} \
    -e SERVER_TOKEN=${SERVER_TOKEN} \
    -e MAX_PARALLEL_JOBS=${MAX_PARALLEL_JOBS} \
    -e HOST_PLATFORM=Proxmox LXC (Debian 12) \
    -v esphome-versions:/esphome-versions \
    esphome-dist-client
ExecStop=/usr/bin/docker stop esphome-dist-client
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF'

pct exec "$TEMP_CTID" -- systemctl enable esphome-dist-client

# ── Clean up and convert to template ───────────────────────────────
echo "==> Cleaning up container ..."
pct exec "$TEMP_CTID" -- bash -c '
    apt-get clean
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
    > /var/log/lastlog
    > /var/log/wtmp
'

echo "==> Stopping container ..."
pct stop "$TEMP_CTID"

echo "==> Creating template backup ..."
vzdump "$TEMP_CTID" --dumpdir /var/lib/vz/template/cache --compress zstd --mode stop 2>&1 | tail -3
# Rename to a clean template name
DUMP_FILE=$(ls -t /var/lib/vz/template/cache/vzdump-lxc-${TEMP_CTID}-*.tar.zst 2>/dev/null | head -1)
if [ -n "$DUMP_FILE" ]; then
    mv "$DUMP_FILE" "$TEMPLATE_PATH"
fi

echo "==> Removing temporary container ..."
pct destroy "$TEMP_CTID" --purge

echo ""
echo "==> Template created: $TEMPLATE_PATH"
echo ""
echo "To deploy:"
echo "  pct create <CTID> local:vztmpl/${TEMPLATE_NAME}.tar.zst \\"
echo "    --hostname esphome-builder \\"
echo "    --memory 2048 --cores 2 \\"
echo "    --rootfs local-lvm:16 \\"
echo "    --net0 name=eth0,bridge=vmbr0,ip=dhcp \\"
echo "    --features nesting=1,keyctl=1 \\"
echo "    --unprivileged 1"
echo ""
echo "  # Configure credentials:"
echo "  pct exec <CTID> -- nano /etc/esphome-dist-client.env"
echo ""
echo "  # Start:"
echo "  pct start <CTID>"
