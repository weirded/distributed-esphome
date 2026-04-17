# ESPHome Fleet

Manage fleets of ESPHome devices from one place — bulk operations, scheduled OTA upgrades, per-device version pinning, distributed compilation, and a fast modern UI.

If Home Assistant runs on a Raspberry Pi or other low-power hardware, ESPHome compilation is painfully slow. ESPHome Fleet lets you point the heavy lifting at any faster machine on your network (x86, ARM, Apple Silicon) while keeping HA as the single source of truth for your device configs. Even without remote workers, the built-in local worker and the modern UI make this a powerful replacement for the stock ESPHome dashboard.

## Getting Started

Start the add-on, then open the web UI via the **ESPHome Fleet** entry in the HA sidebar.

> **First boot takes 1–3 minutes.** The add-on lazy-installs ESPHome into `/data/esphome-versions/` on first launch rather than shipping a pre-baked copy, so your install always picks up the version the HA ESPHome add-on reports. While the install runs, the UI shows an "Installing ESPHome…" banner and features that depend on the ESPHome binary (config validation, autocomplete, compiles) stay disabled. Subsequent restarts are instant because the venv is cached.

The add-on includes a built-in local worker (starts paused with 0 slots). Increase the slot count in the **Workers** tab to start compiling immediately. To offload builds to faster machines, click **+ Connect Worker** for a ready-to-run `docker run` command (or a `docker-compose.yml` snippet).

Configuration options (token, timeouts, polling intervals) are available in the add-on's **Configuration** tab in Home Assistant.

## Web UI

**Devices** — every ESPHome config in one place, with online status, current firmware version, and a one-click link to its Home Assistant page. Compile individual devices, everything that's outdated, or your whole fleet. Create new devices or duplicate existing ones, edit YAML inline with autocomplete and validation, pin individual devices to a specific ESPHome version, and view live device logs.

**Queue** — live job status and build logs. Retry, cancel, or clear jobs individually or in bulk.

**Workers** — connected build workers with their slot count, cache size, and system info. Includes a built-in local worker and a one-click setup command for adding remote workers. Workers running an outdated image are flagged with an "image stale" badge.

**Schedules** — every scheduled upgrade in one view. Set recurring schedules (daily, weekly, monthly, custom cron) or one-time future upgrades from the device hamburger menu. Schedules are stored alongside the YAML so they travel with your config, and respect each device's pinned ESPHome version.

## Troubleshooting

**Worker shows as offline** — verify `SERVER_URL` and `SERVER_TOKEN` match the add-on configuration. Check that the worker host can reach port 8765.

**Jobs stay in PENDING** — no worker is picking them up. Confirm at least one worker is online in the Workers tab.

**OTA fails but compile succeeds** — the worker cannot reach the ESP device on port 3232. Check network/VLAN/firewall rules.

**Wrong firmware version shown** — the device must be on the same network segment as HA (or mDNS must be forwarded). Version updates appear within one poll cycle.

**ESPHome version errors** — check the build log. Pre-install a known-good version with `ESPHOME_SEED_VERSION` on the worker.

## Direct-Port API Access

The add-on's web UI lives behind Home Assistant Ingress and is authenticated by HA itself — no extra step needed to open it from the HA sidebar. Workers connect over the direct port (`:8765`) with a shared `token` from the add-on options.

**Direct-port `/ui/api/*` access requires a Bearer token by default** (add-on option `require_ha_auth`, default `true` since 1.5.0). Two kinds of tokens are accepted:

- **The add-on's shared token** (from the add-on's Configuration tab — also what build workers use on port 8765). Handy for scripts running on machines that already have the token, and the native ESPHome Fleet HA integration uses it automatically.
- **A Home Assistant Long-Lived Access Token** for anything that wants real per-user attribution. Mutations (compile, cancel, pin, schedule, rename, delete, save) log the authenticated user's HA username.

Example:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://homeassistant.local:8765/ui/api/targets
```

Requests without a valid token receive **401 Unauthorized** plus `WWW-Authenticate: Bearer realm="ESPHome Fleet"`. Ingress-tunneled access is unaffected — HA already authenticated the user before forwarding.

If you specifically need the pre-1.4.1 "no auth on port 8765" behavior (for a test harness, say), flip `require_ha_auth` to `false` in the add-on options.

## Verifying Image Signatures

Both the server and client Docker images on GHCR are signed with [cosign](https://docs.sigstore.dev/) using GitHub OIDC keyless signing — no long-lived keys are involved, the signature is anchored to the GitHub Actions workflow's identity. You can verify what you pull matches a build from this repo:

```bash
# Verify the client image
cosign verify \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-client\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/weirded/esphome-dist-client:latest

# Verify the server image
cosign verify \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-server\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/weirded/esphome-dist-server:latest
```

A successful verification prints the signature payload + the OIDC claims (workflow ref, run ID, commit SHA) — confirming the image was built by the official workflow on this repo and hasn't been tampered with in transit. Run this after `docker pull` and before any production deployment.

### Verifying the SBOM

Every image published from 1.5.0 onward also carries a CycloneDX-format SBOM as a cosign attestation. You can fetch and verify it with:

```bash
# Server image — print the attached CycloneDX SBOM
cosign verify-attestation \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-server\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --type cyclonedx \
  ghcr.io/weirded/esphome-dist-server:latest \
  | jq -r '.payload | @base64d | fromjson | .predicate' \
  > esphome-dist-server.sbom.json

# Client image
cosign verify-attestation \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-client\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --type cyclonedx \
  ghcr.io/weirded/esphome-dist-client:latest \
  | jq -r '.payload | @base64d | fromjson | .predicate' \
  > esphome-dist-client.sbom.json
```

The JSON file lists every Python package, OS library, and pinned version baked into the image — handy for CVE auditing, compliance, and supply-chain review.

## Support

If this add-on has saved you time or frustration, you can support continued development:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-orange?logo=buy-me-a-coffee&logoColor=white&style=for-the-badge)](https://buymeacoffee.com/weirded)
