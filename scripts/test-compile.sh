#!/usr/bin/env bash
# Test ESPHome compilation for all supported platforms.
# Runs inside a Docker container (client or server image) with ESPHome installed.
#
# Usage:
#   # Test with the client Docker image (remote worker):
#   docker run --rm -v "$PWD/tests/fixtures/compile_targets:/config" \
#     ghcr.io/weirded/esphome-dist-client:latest \
#     /bin/bash -c "pip install esphome && /app/scripts/test-compile.sh /config"
#
#   # Or run directly if ESPHome is installed:
#   ./scripts/test-compile.sh tests/fixtures/compile_targets
#
# Exit code: 0 if all compiles succeed, 1 if any fail.

set -euo pipefail

CONFIG_DIR="${1:?Usage: $0 <config-dir>}"
ESPHOME_VERSION="${ESPHOME_VERSION:-}"

if [ -n "$ESPHOME_VERSION" ]; then
  echo "==> Installing ESPHome ${ESPHOME_VERSION}..."
  pip install --no-cache-dir "esphome==${ESPHOME_VERSION}" >/dev/null 2>&1
fi

echo "==> ESPHome version: $(esphome version 2>/dev/null || echo 'not installed')"
echo "==> Config directory: ${CONFIG_DIR}"
echo ""

PASS=0
FAIL=0
FAILED_TARGETS=""

for yaml in "${CONFIG_DIR}"/*.yaml; do
  name=$(basename "$yaml")
  [ "$name" = "secrets.yaml" ] && continue

  echo "--- Compiling: ${name} ---"
  if esphome compile "$yaml" 2>&1 | tail -5; then
    echo "    PASS"
    ((PASS++))
  else
    echo "    FAIL"
    ((FAIL++))
    FAILED_TARGETS="${FAILED_TARGETS} ${name}"
  fi
  echo ""
done

echo "========================================="
echo "Results: ${PASS} passed, ${FAIL} failed"
if [ $FAIL -gt 0 ]; then
  echo "Failed targets:${FAILED_TARGETS}"
  exit 1
fi
echo "All platforms compile successfully."
