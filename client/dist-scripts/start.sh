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

# Auto-detect host platform if not explicitly set
if [ -z "${HOST_PLATFORM:-}" ]; then
    _os="$(uname -s)"
    case "$_os" in
        Darwin)
            _ver="$(sw_vers -productVersion 2>/dev/null || true)"
            _cpu="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)"
            HOST_PLATFORM="macOS${_ver:+ $_ver}${_cpu:+ ($_cpu)}"
            ;;
        Linux)
            # Running start.sh directly on a Linux host (not inside Docker)
            if [ -f /etc/os-release ]; then
                # shellcheck disable=SC1091
                . /etc/os-release
                HOST_PLATFORM="${NAME:-Linux}${VERSION_ID:+ $VERSION_ID}"
            else
                HOST_PLATFORM="Linux $(uname -r)"
            fi
            ;;
        *)
            HOST_PLATFORM="$_os $(uname -r)"
            ;;
    esac
fi

IMAGE="esphome-dist-client"
CONTAINER_NAME="esphome-dist-client"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Loading Docker image..."
docker load -i "$SCRIPT_DIR/esphome-dist-client.tar"

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
    ${HOST_PLATFORM:+-e HOST_PLATFORM="$HOST_PLATFORM"} \
    -v esphome-versions:/esphome-versions \
    "$IMAGE"

if [ "$BACKGROUND" = true ]; then
    echo "Started in background. Logs: docker logs -f $CONTAINER_NAME"
else
    echo "Started. Tailing logs (Ctrl-C to detach — container keeps running)..."
    docker logs -f "$CONTAINER_NAME"
fi
