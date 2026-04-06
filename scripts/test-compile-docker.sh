#!/usr/bin/env bash
# Test ESPHome compilation in Docker containers.
# Validates that both the client image and server add-on image can compile all platforms.
#
# Usage:
#   ./scripts/test-compile-docker.sh [--client-only|--server-only]
#
# Prerequisites:
#   - Docker running
#   - Client image: build locally with `docker build -t esphome-dist-client ha-addon/client/`
#   - Server image: build locally with `docker build -t esphome-dist-server ha-addon/`

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FIXTURES="$REPO_ROOT/tests/fixtures/compile_targets"
ESPHOME_VERSION="${ESPHOME_VERSION:-2026.3.2}"

MODE="${1:-both}"

run_compile_test() {
  local image="$1"
  local label="$2"

  echo ""
  echo "============================================"
  echo "  Testing: ${label}"
  echo "  Image:   ${image}"
  echo "  ESPHome: ${ESPHOME_VERSION}"
  echo "============================================"
  echo ""

  docker run --rm \
    -v "${FIXTURES}:/config:ro" \
    -v esphome-test-cache:/esphome-versions \
    -e ESPHOME_VERSION="${ESPHOME_VERSION}" \
    "${image}" \
    /bin/bash -c "
      pip install --no-cache-dir 'esphome==${ESPHOME_VERSION}' && \
      cd /config && \
      PASS=0; FAIL=0; FAILED=''; \
      for yaml in *.yaml; do \
        [ \"\$yaml\" = 'secrets.yaml' ] && continue; \
        echo \"--- Compiling: \$yaml ---\"; \
        if esphome compile \"\$yaml\" 2>&1 | tail -3; then \
          echo '    PASS'; PASS=\$((PASS+1)); \
        else \
          echo '    FAIL'; FAIL=\$((FAIL+1)); FAILED=\"\$FAILED \$yaml\"; \
        fi; \
        echo ''; \
      done; \
      echo '========================================='; \
      echo \"Results: \$PASS passed, \$FAIL failed\"; \
      [ \$FAIL -gt 0 ] && echo \"Failed:\$FAILED\" && exit 1; \
      echo 'All platforms compile successfully.';
    "
}

if [ "$MODE" != "--server-only" ]; then
  run_compile_test "esphome-dist-client" "Client Docker Image (remote worker)"
fi

if [ "$MODE" != "--client-only" ]; then
  run_compile_test "esphome-dist-server" "Server Add-on Image (local worker)"
fi

echo ""
echo "All compile tests passed."
