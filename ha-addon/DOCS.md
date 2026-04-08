# ESPHome Distributed Build Server

A modern web UI for managing large fleets of ESPHome devices — with distributed compilation that offloads firmware builds to faster remote machines.

If Home Assistant runs on a Raspberry Pi or other low-power hardware, ESPHome compilation is painfully slow. This add-on lets you point the heavy lifting at any faster machine on your network (x86, ARM, Apple Silicon) while keeping HA as the single source of truth for your device configs. Even without remote workers, the built-in local worker and the modern UI make this a powerful replacement for the stock ESPHome dashboard.

## Getting Started

Start the add-on, then open the web UI via the **ESPH Distributed** entry in the HA sidebar.

The add-on includes a built-in local worker (starts paused with 0 slots). Increase the slot count in the **Workers** tab to start compiling immediately. To offload builds to faster machines, click **+ Connect Worker** for a ready-to-run `docker run` command.

Configuration options (token, timeouts, polling intervals) are available in the add-on's **Configuration** tab in Home Assistant.

## Web UI

**Devices** — all discovered ESPHome YAML configs with online/offline status (using HA connectivity where available), firmware version, config-changed indicator, and HA integration status. Compile individual, all, or only outdated devices. Inline Monaco YAML editor with ESPHome schema autocomplete and validation. Rename, delete, restart devices, copy API keys, and view live device logs. Configurable columns and search/filter.

**Queue** — live job status with build logs. Retry failed jobs, cancel in-progress ones. Entries auto-prune after one hour.

**Workers** — connected build workers with online status, current jobs, system info (CPU, memory, disk), and ESPHome version. Adjust slot count per worker (0 = paused), clean per-worker or all build caches, or remove offline workers. Workers running an outdated Docker image are flagged with a clickable "image stale" badge that opens the Connect Worker modal so you can re-run the latest `docker run` command.

## Troubleshooting

**Worker shows as offline** — verify `SERVER_URL` and `SERVER_TOKEN` match the add-on configuration. Check that the worker host can reach port 8765.

**Jobs stay in PENDING** — no worker is picking them up. Confirm at least one worker is online in the Workers tab.

**OTA fails but compile succeeds** — the worker cannot reach the ESP device on port 3232. Check network/VLAN/firewall rules.

**Wrong firmware version shown** — the device must be on the same network segment as HA (or mDNS must be forwarded). Version updates appear within one poll cycle.

**ESPHome version errors** — check the build log. Pre-install a known-good version with `ESPHOME_SEED_VERSION` on the worker.
