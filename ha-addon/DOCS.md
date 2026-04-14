# ESPHome Distributed Build Server

A modern web UI for managing large fleets of ESPHome devices — with distributed compilation that offloads firmware builds to faster remote machines.

If Home Assistant runs on a Raspberry Pi or other low-power hardware, ESPHome compilation is painfully slow. This add-on lets you point the heavy lifting at any faster machine on your network (x86, ARM, Apple Silicon) while keeping HA as the single source of truth for your device configs. Even without remote workers, the built-in local worker and the modern UI make this a powerful replacement for the stock ESPHome dashboard.

## Getting Started

Start the add-on, then open the web UI via the **ESPH Distributed** entry in the HA sidebar.

The add-on includes a built-in local worker (starts paused with 0 slots). Increase the slot count in the **Workers** tab to start compiling immediately. To offload builds to faster machines, click **+ Connect Worker** for a ready-to-run `docker run` command.

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

## Support

If this add-on has saved you time or frustration, you can support continued development:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-orange?logo=buy-me-a-coffee&logoColor=white&style=for-the-badge)](https://buymeacoffee.com/weirded)
