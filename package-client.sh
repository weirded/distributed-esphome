#!/usr/bin/env bash
# Package the build client into a self-contained distributable archive.
#
# Usage:
#   ./package-client.sh [SERVER_URL] [SERVER_TOKEN] [PLATFORM]
#
#   PLATFORM defaults to the host architecture:
#     linux/amd64   — x86-64 (Intel/AMD)
#     linux/arm64   — 64-bit ARM (Apple Silicon, Raspberry Pi 4+, AWS Graviton)
#     linux/arm/v7  — 32-bit ARM (Raspberry Pi 3 and older)
#
# Produces: dist/esphome-dist-client-<version>[-<arch>].tar.gz
#   Contains:
#     - esphome-dist-client.tar    Docker image
#     - start.sh                   Load image + docker run
#     - stop.sh                    Stop and remove container
#     - uninstall.sh               Remove container, image, optional volume

set -euo pipefail

SERVER_URL="${1:-http://YOUR_HA_HOST:8765}"
SERVER_TOKEN="${2:-YOUR_TOKEN}"

# Default platform: match host architecture
_HOST_ARCH="$(uname -m)"
case "$_HOST_ARCH" in
  arm64|aarch64) _DEFAULT_PLATFORM="linux/arm64" ;;
  armv7l)        _DEFAULT_PLATFORM="linux/arm/v7" ;;
  *)             _DEFAULT_PLATFORM="linux/amd64" ;;
esac
PLATFORM="${3:-$_DEFAULT_PLATFORM}"

IMAGE="esphome-dist-client"
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(cat "$REPO_ROOT/ha-addon/VERSION" 2>/dev/null || echo "0.0.1")"
SCRIPTS_DIR="$REPO_ROOT/client/dist-scripts"

# Arch suffix (omitted for amd64 to stay backward-compatible)
case "$PLATFORM" in
  linux/arm64|linux/aarch64) _ARCH_SUFFIX="-arm64" ;;
  linux/arm/v7)              _ARCH_SUFFIX="-armv7" ;;
  linux/amd64)               _ARCH_SUFFIX="-x86_64" ;;
  *)                          _ARCH_SUFFIX="-x86_64" ;;
esac

OUT_DIR="$REPO_ROOT/dist"
ARCHIVE="$OUT_DIR/esphome-dist-client-${VERSION}${_ARCH_SUFFIX}.tar.gz"

echo "==> Building Docker image $IMAGE:$VERSION (platform: $PLATFORM) ..."
docker buildx build \
    --platform "$PLATFORM" \
    --load \
    -t "$IMAGE:$VERSION" \
    -t "$IMAGE:latest" \
    "$REPO_ROOT/client/"

echo "==> Saving image to tar ..."
mkdir -p "$OUT_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

docker save "$IMAGE:latest" -o "$TMP_DIR/esphome-dist-client.tar"

echo "==> Copying distribution scripts ..."
# Bash scripts (macOS / Linux)
for script in start.sh stop.sh uninstall.sh; do
    cp "$SCRIPTS_DIR/$script" "$TMP_DIR/$script"
done
chmod +x "$TMP_DIR"/*.sh
# PowerShell scripts (Windows)
for script in start.ps1 stop.ps1 uninstall.ps1; do
    cp "$SCRIPTS_DIR/$script" "$TMP_DIR/$script"
done
# Proxmox script
cp "$SCRIPTS_DIR/proxmox-create.sh" "$TMP_DIR/proxmox-create.sh"
chmod +x "$TMP_DIR/proxmox-create.sh"
echo "$VERSION" > "$TMP_DIR/VERSION"

# Bake build-time SERVER_URL and SERVER_TOKEN as a comment in start.sh / start.ps1
sed -i.bak \
    "s|{{BUILD_INFO}}|Built with: SERVER_URL=$SERVER_URL  SERVER_TOKEN=$SERVER_TOKEN|" \
    "$TMP_DIR/start.sh"
rm -f "$TMP_DIR/start.sh.bak"
sed -i.bak \
    "s|{{BUILD_INFO}}|Built with: SERVER_URL=$SERVER_URL  SERVER_TOKEN=$SERVER_TOKEN|" \
    "$TMP_DIR/start.ps1"
rm -f "$TMP_DIR/start.ps1.bak"

echo "==> Creating archive $ARCHIVE ..."
tar -czf "$ARCHIVE" -C "$TMP_DIR" VERSION esphome-dist-client.tar \
    start.sh stop.sh uninstall.sh \
    start.ps1 stop.ps1 uninstall.ps1 \
    proxmox-create.sh

echo ""
echo "Done: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo ""
echo "To deploy (macOS/Linux):"
echo "  scp $ARCHIVE user@host:/tmp/"
echo "  ssh user@host 'cd /tmp && tar -xzf $(basename "$ARCHIVE") && SERVER_URL=$SERVER_URL SERVER_TOKEN=$SERVER_TOKEN ./start.sh'"
echo ""
echo "To deploy (Windows PowerShell):"
echo "  # Extract the archive, then:"
echo "  \$env:SERVER_URL='$SERVER_URL'; \$env:SERVER_TOKEN='$SERVER_TOKEN'; .\\start.ps1"
echo ""
echo "To deploy (Proxmox — run on the Proxmox host):"
echo "  # Extract the archive, then:"
echo "  SERVER_URL=$SERVER_URL SERVER_TOKEN=$SERVER_TOKEN ./proxmox-create.sh"
