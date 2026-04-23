#!/usr/bin/env bash
# Deploy the add-on to a throwaway HAOS VM and run the e2e-hass-4 smoke
# suite against it. Counterpart to push-to-hass-4.sh — that one targets
# the always-on hass-4 box; this one targets a clean VM provisioned by
# scripts/haos/provision-vm.sh.
#
# Purpose: HT.13 regression guard. push-to-hass-4.sh proves the add-on
# runs on a warm, long-lived HA install (happy-path dev loop). This script
# proves it runs on a freshly provisioned HAOS box, and in INSTALL_MODE=ghcr
# it proves the bug-#82 prebuilt-image install path still works.
#
# Prerequisites:
#   - Test VM provisioned: scripts/haos/provision-vm.sh
#   - VM onboarded (long-lived HA token in token file): scripts/haos/onboard.sh
#   - HAOS_URL set (HA URL for the VM — DHCP-assigned IP, port 8123)
#
# Env:
#   HAOS_URL             required — e.g. http://192.168.224.17:8123
#   HAOS_ADDON_URL       optional — override add-on URL (default http://<haos-host>:8765)
#   HAOS_TOKEN_FILE      HA long-lived token path (default $HOME/.config/distributed-esphome/haos-token)
#   INSTALL_MODE         local (default) or ghcr — see scripts/haos/install-addon.sh
#   SKIP_SMOKE=1         skip the Playwright run
#   SKIP_INSTALL=1       skip the install step (useful to rerun smoke only)
#   PVE_HOST             Proxmox SSH alias (default pve)
#   VMID                 (default 106)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

HAOS_URL="${HAOS_URL:-}"
[[ -n "$HAOS_URL" ]] || { echo "HAOS_URL is required (e.g. HAOS_URL=http://192.168.224.17:8123)" >&2; exit 1; }
HAOS_URL="${HAOS_URL%/}"

HAOS_TOKEN_FILE="${HAOS_TOKEN_FILE:-$HOME/.config/distributed-esphome/haos-token}"
INSTALL_MODE="${INSTALL_MODE:-local}"
PVE_HOST="${PVE_HOST:-pve}"
VMID="${VMID:-106}"

# Derive the add-on's direct-port URL from the HAOS URL if not given
# explicitly. DHCP assigns the VM one IP; Supervisor exposes the add-on on
# its configured host port (8765 in our config.yaml).
if [[ -z "${HAOS_ADDON_URL:-}" ]]; then
  # Strip scheme + port from HAOS_URL to get the host.
  _haos_host=$(echo "$HAOS_URL" | sed -E 's#^https?://##; s#:[0-9]+$##; s#/.*$##')
  HAOS_ADDON_URL="http://${_haos_host}:8765"
fi

VERSION="$(cat "$REPO_ROOT/ha-addon/VERSION")"

echo "==> Target HAOS:   $HAOS_URL"
echo "==> Add-on URL:    $HAOS_ADDON_URL"
echo "==> VM:            $PVE_HOST → VMID $VMID"
echo "==> Version:       $VERSION (mode: $INSTALL_MODE)"

# ---------------------------------------------------------------------------
# 1. Install (or refresh) the add-on on the VM.
# ---------------------------------------------------------------------------
if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
  echo ""
  echo "==> Installing add-on on VM $VMID (INSTALL_MODE=$INSTALL_MODE) ..."
  PVE_HOST="$PVE_HOST" VMID="$VMID" INSTALL_MODE="$INSTALL_MODE" \
    "$REPO_ROOT/scripts/haos/install-addon.sh"
else
  echo "==> SKIP_INSTALL=1 — skipping add-on install"
fi

# ---------------------------------------------------------------------------
# 2. Read the add-on's auth token from the VM for the HTTP smoke suite.
#    Same `/data/settings.json` lookup as push-to-hass-4.sh; falls back to
#    Supervisor API / filesystem scan for pre-1.6 installs.
# ---------------------------------------------------------------------------

# Ensure we have an HA long-lived token — needed for the Supervisor-API
# fallback and for potential future HA-services smoke coverage.
if [[ ! -f "$HAOS_TOKEN_FILE" ]]; then
  echo "Missing HA long-lived token at $HAOS_TOKEN_FILE" >&2
  echo "  Run: HA_PASSWORD=... scripts/haos/onboard.sh $HAOS_URL" >&2
  exit 2
fi
HAOS_HA_TOKEN=$(cat "$HAOS_TOKEN_FILE")

# The simplest, most reliable path to the add-on token on HAOS is the same
# one push-to-hass-4.sh uses: exec into the add-on container and read
# /data/settings.json. We reach the container via pvesh + qga (no SSH
# server inside HAOS).
echo ""
echo "==> Fetching add-on token from VM ..."
PVE_NODE="${PVE_NODE:-}"
if [[ -z "$PVE_NODE" ]]; then
  PVE_NODE=$(ssh "$PVE_HOST" "pvesh get /nodes --output-format json" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['node'])" 2>/dev/null) \
    || { echo "Couldn't auto-detect PVE_NODE; set PVE_NODE explicitly" >&2; exit 3; }
fi

# Run a one-shot guest-exec; block up to 30s for the container to be ready.
guest_read_settings() {
  ssh "$PVE_HOST" "PVE_NODE=$PVE_NODE VMID=$VMID bash -s" <<'REMOTE'
set -euo pipefail
TMPJSON=$(mktemp); trap 'rm -f "$TMPJSON"' EXIT
pvesh create "/nodes/$PVE_NODE/qemu/$VMID/agent/exec" \
  --command /bin/sh --command -c --command \
  'docker exec addon_local_esphome_dist_server cat /data/settings.json 2>/dev/null || true' \
  --output-format json > "$TMPJSON"
PID=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1]))['pid'])" "$TMPJSON")
for _ in $(seq 1 30); do
  pvesh get "/nodes/$PVE_NODE/qemu/$VMID/agent/exec-status" \
    --pid "$PID" --output-format json > "$TMPJSON"
  if python3 -c "import sys,json; sys.exit(0 if json.load(open(sys.argv[1])).get('exited') else 1)" "$TMPJSON"; then
    python3 -c "import sys,json; print(json.load(open(sys.argv[1])).get('out-data',''))" "$TMPJSON"
    exit 0
  fi
  sleep 1
done
exit 124
REMOTE
}

SETTINGS_JSON="$(guest_read_settings || true)"
HAOS_ADDON_TOKEN=""
if [[ -n "$SETTINGS_JSON" ]]; then
  HAOS_ADDON_TOKEN=$(python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('server_token',''))" <<<"$SETTINGS_JSON" 2>/dev/null || true)
fi

if [[ -z "$HAOS_ADDON_TOKEN" || "$HAOS_ADDON_TOKEN" == "null" ]]; then
  # Fallback: Supervisor API via the HA long-lived token.
  HAOS_ADDON_TOKEN=$(curl -sf --max-time 5 -H "Authorization: Bearer $HAOS_HA_TOKEN" \
    "$HAOS_URL/api/hassio/addons/local_esphome_dist_server/info" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('options',{}).get('token',''))" 2>/dev/null || true)
fi
if [[ -z "$HAOS_ADDON_TOKEN" || "$HAOS_ADDON_TOKEN" == "null" ]]; then
  echo "    WARNING: couldn't read the add-on token from VM — version probe will 401 under require_ha_auth=true" >&2
  HAOS_ADDON_TOKEN=""
fi

# ---------------------------------------------------------------------------
# 3. Wait for the add-on to report the target version on its HTTP API.
# ---------------------------------------------------------------------------
echo ""
echo "==> Waiting for add-on at $HAOS_ADDON_URL to report v$VERSION ..."
for i in $(seq 1 30); do
  if [[ -n "$HAOS_ADDON_TOKEN" ]]; then
    REPORTED=$(curl -sf --max-time 3 -H "Authorization: Bearer $HAOS_ADDON_TOKEN" \
      "$HAOS_ADDON_URL/ui/api/server-info" 2>/dev/null \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('addon_version',''))" 2>/dev/null || true)
  else
    REPORTED=$(curl -sf --max-time 3 "$HAOS_ADDON_URL/ui/api/server-info" 2>/dev/null \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('addon_version',''))" 2>/dev/null || true)
  fi
  if [[ "$REPORTED" == "$VERSION" ]]; then
    echo "    Server reports v$VERSION — ready."
    break
  fi
  if [[ "$i" -eq 30 ]]; then
    echo "    Timed out waiting for add-on to come up with v$VERSION (last seen: '$REPORTED')" >&2
    exit 1
  fi
  sleep 2
done

# ---------------------------------------------------------------------------
# 4. Run the e2e-hass-4 smoke suite against the HAOS VM.
# ---------------------------------------------------------------------------
if [[ "${SKIP_SMOKE:-0}" == "1" ]]; then
  echo "==> SKIP_SMOKE=1 — skipping Playwright run"
  exit 0
fi

echo ""
echo "==> Running e2e-hass-4 smoke suite against HAOS VM ..."
cd "$REPO_ROOT/ha-addon/ui"
HASS4_URL="$HAOS_ADDON_URL" HASS4_ADDON_TOKEN="$HAOS_ADDON_TOKEN" npm run test:e2e:hass-4
