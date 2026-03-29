#!/usr/bin/env bash
# Packages the build client into a self-contained distributable archive.
# Usage: ./package-client.sh [SERVER_URL] [SERVER_TOKEN]
#
# Produces: dist/esphome-dist-client-<version>.tar.gz
#   Contains:
#     - esphome-dist-client.tar    (Docker image)
#     - start.sh                   (load image + docker run; tails logs by default)
#     - stop.sh                    (stop and remove the container)
#     - uninstall.sh               (stop container + remove image)

set -euo pipefail

SERVER_URL="${1:-http://YOUR_HA_HOST:8765}"
SERVER_TOKEN="${2:-YOUR_TOKEN}"
IMAGE="esphome-dist-client"
VERSION="$(cat "$(dirname "$0")/ha-addon/VERSION" 2>/dev/null || echo "0.0.1")"
OUT_DIR="$(dirname "$0")/dist"
ARCHIVE="$OUT_DIR/esphome-dist-client-${VERSION}.tar.gz"

echo "==> Building Docker image $IMAGE:$VERSION ..."
docker build -t "$IMAGE:$VERSION" -t "$IMAGE:latest" "$(dirname "$0")/client/"

echo "==> Saving image to tar ..."
mkdir -p "$OUT_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

docker save "$IMAGE:latest" -o "$TMP_DIR/esphome-dist-client.tar"

# ---------------------------------------------------------------------------
# start.sh
# ---------------------------------------------------------------------------
echo "==> Writing start.sh ..."
cat > "$TMP_DIR/start.sh" << 'STARTEOF'
#!/usr/bin/env bash
# ESPHome Distributed Build Client — start script
#
# Usage:
#   ./start.sh              Start and tail logs (foreground; Ctrl-C detaches, container keeps running)
#   ./start.sh --background Start detached

set -euo pipefail

BACKGROUND=false
for arg in "$@"; do
    [ "$arg" = "--background" ] && BACKGROUND=true
done

# Require SERVER_URL and SERVER_TOKEN
if [ -z "${SERVER_URL:-}" ]; then
    echo "ERROR: SERVER_URL is not set. Export it or edit this script." >&2
    exit 1
fi
if [ -z "${SERVER_TOKEN:-}" ]; then
    echo "ERROR: SERVER_TOKEN is not set. Export it or edit this script." >&2
    exit 1
fi

IMAGE="esphome-dist-client"
CONTAINER_NAME="esphome-dist-client"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load image if not already present
if ! docker image inspect "$IMAGE" > /dev/null 2>&1; then
    echo "Loading Docker image..."
    docker load -i "$SCRIPT_DIR/esphome-dist-client.tar"
fi

# Remove existing container if any
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Removing existing container..."
    docker rm -f "$CONTAINER_NAME"
fi

echo "Starting $CONTAINER_NAME ..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --hostname "$(hostname)" \
    -e SERVER_URL="$SERVER_URL" \
    -e SERVER_TOKEN="$SERVER_TOKEN" \
    ${MAX_PARALLEL_JOBS:+-e MAX_PARALLEL_JOBS="$MAX_PARALLEL_JOBS"} \
    -v esphome-versions:/esphome-versions \
    "$IMAGE"

if [ "$BACKGROUND" = true ]; then
    echo "Started in background. Logs: docker logs -f $CONTAINER_NAME"
else
    echo "Started. Tailing logs (Ctrl-C to detach — container keeps running)..."
    docker logs -f "$CONTAINER_NAME"
fi
STARTEOF
chmod +x "$TMP_DIR/start.sh"

# Bake in default SERVER_URL and SERVER_TOKEN as comments so the user
# knows what values were used when the package was built.
sed -i.bak \
    "s|# Require SERVER_URL and SERVER_TOKEN|# Built with SERVER_URL=$SERVER_URL  SERVER_TOKEN=$SERVER_TOKEN\n# Require SERVER_URL and SERVER_TOKEN|" \
    "$TMP_DIR/start.sh"
rm -f "$TMP_DIR/start.sh.bak"

# ---------------------------------------------------------------------------
# stop.sh
# ---------------------------------------------------------------------------
echo "==> Writing stop.sh ..."
cat > "$TMP_DIR/stop.sh" << 'STOPEOF'
#!/usr/bin/env bash
# ESPHome Distributed Build Client — stop script
set -euo pipefail

CONTAINER_NAME="esphome-dist-client"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping $CONTAINER_NAME ..."
    docker stop "$CONTAINER_NAME"
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Removing $CONTAINER_NAME ..."
    docker rm "$CONTAINER_NAME"
fi

echo "Done."
STOPEOF
chmod +x "$TMP_DIR/stop.sh"

# ---------------------------------------------------------------------------
# uninstall.sh
# ---------------------------------------------------------------------------
echo "==> Writing uninstall.sh ..."
cat > "$TMP_DIR/uninstall.sh" << 'UNINSTEOF'
#!/usr/bin/env bash
# ESPHome Distributed Build Client — uninstall script
# Stops and removes the container, removes the Docker image, and optionally
# removes the esphome-versions volume.
set -euo pipefail

CONTAINER_NAME="esphome-dist-client"
IMAGE="esphome-dist-client"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping $CONTAINER_NAME ..."
    docker stop "$CONTAINER_NAME"
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Removing container $CONTAINER_NAME ..."
    docker rm "$CONTAINER_NAME"
fi

if docker image inspect "$IMAGE" > /dev/null 2>&1; then
    echo "Removing image $IMAGE ..."
    docker rmi "$IMAGE"
fi

echo ""
read -r -p "Also remove the esphome-versions volume (cached ESPHome installs)? [y/N] " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    docker volume rm esphome-versions 2>/dev/null && echo "Volume removed." || echo "Volume not found (already gone)."
fi

echo "Uninstall complete."
UNINSTEOF
chmod +x "$TMP_DIR/uninstall.sh"

# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------
echo "==> Creating archive $ARCHIVE ..."
tar -czf "$ARCHIVE" -C "$TMP_DIR" esphome-dist-client.tar start.sh stop.sh uninstall.sh

echo ""
echo "Done: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo ""
echo "To deploy to another host:"
echo "  scp $ARCHIVE user@host:/tmp/"
echo "  ssh user@host 'cd /tmp && tar -xzf $(basename "$ARCHIVE") && SERVER_URL=http://ha:8765 SERVER_TOKEN=yourtoken ./start.sh'"
