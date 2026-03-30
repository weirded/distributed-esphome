#!/usr/bin/env bash
# ESPHome Distributed Build Client — start script
#
# Usage:
#   ./start.sh              Start and tail logs (Ctrl-C detaches; container keeps running)
#   ./start.sh --background Start detached
#
# {{BUILD_INFO}}

set -euo pipefail

BACKGROUND=false
for arg in "$@"; do
    [ "$arg" = "--background" ] && BACKGROUND=true
done

if [ -z "${SERVER_URL:-}" ]; then
    echo "ERROR: SERVER_URL is not set. Export it before running this script." >&2
    exit 1
fi
if [ -z "${SERVER_TOKEN:-}" ]; then
    echo "ERROR: SERVER_TOKEN is not set. Export it before running this script." >&2
    exit 1
fi

IMAGE="esphome-dist-client"
CONTAINER_NAME="esphome-dist-client"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! docker image inspect "$IMAGE" > /dev/null 2>&1; then
    echo "Loading Docker image..."
    docker load -i "$SCRIPT_DIR/esphome-dist-client.tar"
fi

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
