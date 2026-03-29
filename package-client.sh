#!/usr/bin/env bash
# Packages the build client into a self-contained distributable archive.
# Usage: ./package-client.sh [SERVER_URL] [SERVER_TOKEN]
#
# Produces: dist/esphome-dist-client.tar.gz
#   Contains:
#     - esphome-dist-client.tar    (Docker image)
#     - start.sh                   (load image + docker run)

set -euo pipefail

SERVER_URL="${1:-http://YOUR_HA_HOST:8765}"
SERVER_TOKEN="${2:-YOUR_TOKEN}"
IMAGE="esphome-dist-client"
VERSION="$(cat "$(dirname "$0")/ha-addon/VERSION" 2>/dev/null || echo "0.0.1")"
OUT_DIR="$(dirname "$0")/dist"
ARCHIVE="$OUT_DIR/esphome-dist-client.tar.gz"

echo "==> Building Docker image $IMAGE:$VERSION ..."
docker build -t "$IMAGE:$VERSION" -t "$IMAGE:latest" "$(dirname "$0")/client/"

echo "==> Saving image to tar ..."
mkdir -p "$OUT_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

docker save "$IMAGE:latest" -o "$TMP_DIR/esphome-dist-client.tar"

echo "==> Writing start.sh ..."
cat > "$TMP_DIR/start.sh" << EOF
#!/usr/bin/env bash
# ESPHome Distributed Build Client — start script
# Edit SERVER_URL and SERVER_TOKEN before running.

set -euo pipefail

SERVER_URL="\${SERVER_URL:-$SERVER_URL}"
SERVER_TOKEN="\${SERVER_TOKEN:-$SERVER_TOKEN}"
IMAGE="esphome-dist-client"
CONTAINER_NAME="esphome-dist-client"

# Load image if not already present
if ! docker image inspect "\$IMAGE" > /dev/null 2>&1; then
    echo "Loading Docker image..."
    docker load -i "\$(dirname "\$0")/esphome-dist-client.tar"
fi

# Remove existing container if any
if docker ps -a --format '{{.Names}}' | grep -q "^\$CONTAINER_NAME\$"; then
    echo "Removing existing container..."
    docker rm -f "\$CONTAINER_NAME"
fi

echo "Starting \$CONTAINER_NAME ..."
docker run -d \\
    --name "\$CONTAINER_NAME" \\
    --restart unless-stopped \\
    -e SERVER_URL="\$SERVER_URL" \\
    -e SERVER_TOKEN="\$SERVER_TOKEN" \\
    "\$IMAGE"

echo "Started. Logs: docker logs -f \$CONTAINER_NAME"
EOF
chmod +x "$TMP_DIR/start.sh"

echo "==> Creating archive $ARCHIVE ..."
tar -czf "$ARCHIVE" -C "$TMP_DIR" esphome-dist-client.tar start.sh

echo ""
echo "Done: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo ""
echo "To deploy to another host:"
echo "  scp $ARCHIVE user@host:/tmp/"
echo "  ssh user@host 'cd /tmp && tar -xzf esphome-dist-client.tar.gz && ./start.sh'"
