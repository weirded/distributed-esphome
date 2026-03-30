#!/usr/bin/env bash
# Copy the canonical client/ directory into ha-addon/client/.
# Run this before building the server Docker image or packaging the HA add-on.
# ha-addon/client/ is gitignored — client/ is the single source of truth.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
rsync -a --delete "$REPO/client/" "$REPO/ha-addon/client/"
echo "Synced client/ → ha-addon/client/"
