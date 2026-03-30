#!/usr/bin/env bash
# ESPHome Distributed Build Client — uninstall script
# Stops container, removes image, optionally removes the esphome-versions volume.
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
    docker volume rm esphome-versions 2>/dev/null && echo "Volume removed." || echo "Volume not found."
fi

echo "Uninstall complete."
