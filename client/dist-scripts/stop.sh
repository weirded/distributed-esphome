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
