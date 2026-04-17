# ESPHome Fleet

Manage a fleet of ESPHome devices from one place, inside Home Assistant — bulk compiles, scheduled OTA upgrades, per-device version pinning, an inline YAML editor, a job queue you can actually see, and optional distributed compilation so a slow HA host doesn't become a bottleneck.

## Getting Started

Start the add-on, then open the web UI via the **ESPHome Fleet** entry in the HA sidebar.

### First steps

1. Your existing ESPHome configs in `/config/esphome/` are picked up automatically — you should see them on the **Devices** tab.
2. The add-on includes a **built-in local worker** that runs inside the HA host. It starts paused. Go to **Workers**, find the `local-worker` row, and use the `+`/`-` slot buttons to set its parallel-build capacity (1 or 2 is a reasonable default on a Pi; 4+ on a fast host). The moment slot count is above zero, the worker starts claiming jobs.
3. To offload compilation to a faster machine, click **+ Connect Worker** in the Workers tab. Pick **Bash**, **PowerShell**, or **Docker Compose**, copy the generated snippet, and run it on whatever machine you want to compile on. The snippet includes your actual server URL and token, so there's nothing to edit.
4. Home Assistant will pop an "ESPHome Fleet discovered" notification a few seconds after the add-on is running. Accept it to get all the devices, workers, and the add-on itself as real HA devices with entities.

Add-on configuration options (token, job / OTA timeouts, polling intervals, auth knob) live in the add-on's **Configuration** tab in Home Assistant.

## What's on the Web UI

**Devices.** Every ESPHome config in one place. Columns for online status, current firmware version, HA entity link, IP address, WiFi vs Ethernet, network details, schedule, and ESPHome version. Click Upgrade on any row to compile + OTA that device. The row menu (⋮) exposes live logs, restart, rename, duplicate, pin, delete, and copy-api-key (for devices with a native-API encryption key).

**Queue.** Every compile job — pending, running, succeeded, failed. Live build logs. Retry or cancel a job, clear finished jobs in bulk, or download the compiled `.bin` file (for jobs run in "download only" mode).

**Workers.** Every connected worker — local and remote — with platform info, slot count, cache size, current job, and uptime. Workers running an outdated Docker image are flagged with an "image stale" badge so you know to `docker pull && docker restart` them.

**Schedules.** Every scheduled upgrade in one view. Recurring (daily/weekly/monthly or full cron) and one-time future schedules. Schedules live in the device YAML itself so they travel with your config and respect each device's pinned ESPHome version.

**Header** has a dark/light theme toggle, a "streamer mode" that blurs tokens and secrets (for screen-sharing demos), the currently-selected ESPHome version (changes for all new compiles unless overridden per-device via pinning), a shortcut to edit `secrets.yaml`, and a link to [ESPHome Web](https://web.esphome.io/) for browser-based initial flashing.

## Verifying what you're running

Every server and client image on GHCR is signed with [cosign](https://docs.sigstore.dev/) using GitHub's keyless OIDC flow (no long-lived keys anywhere). You can verify that the image you pulled is the one this repo built:

```bash
# Server image
cosign verify \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-server\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/weirded/esphome-dist-server:latest

# Worker image
cosign verify \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-client\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/weirded/esphome-dist-client:latest
```

A successful verification prints the OIDC claims (workflow ref, run ID, commit SHA). Run this once before you trust an image in production, or wire it into your container-pull automation.

### Checking the software bill of materials

Every 1.5.0+ image also carries a CycloneDX SBOM as a cosign attestation — the full list of Python packages, OS libraries, and their pinned versions that went into the image. Handy for CVE audits.

```bash
# Server image — download + print the SBOM
cosign verify-attestation \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-server\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --type cyclonedx \
  ghcr.io/weirded/esphome-dist-server:latest \
  | jq -r '.payload | @base64d | fromjson | .predicate' \
  > esphome-dist-server.sbom.json

# Worker image
cosign verify-attestation \
  --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-client\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --type cyclonedx \
  ghcr.io/weirded/esphome-dist-client:latest \
  | jq -r '.payload | @base64d | fromjson | .predicate' \
  > esphome-dist-client.sbom.json
```

## Support

If this add-on has saved you time or frustration, you can support continued development:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-orange?logo=buy-me-a-coffee&logoColor=white&style=for-the-badge)](https://buymeacoffee.com/weirded)
