# Distributed ESPHome

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-orange?logo=buy-me-a-coffee&logoColor=white)](https://buymeacoffee.com/weirded)

A modern web UI for managing large fleets of ESPHome devices — with distributed compilation that offloads firmware builds to faster remote machines.

The stock ESPHome dashboard works fine for a handful of devices, but becomes unwieldy as your fleet grows. This project provides a feature-rich management interface with bulk operations, live device logs, an inline Monaco YAML editor with schema autocomplete, and a distributed build system that lets you point compilation at faster hardware. Even without remote workers, the built-in local worker and modern UI make this a powerful upgrade.

![Distributed ESPHome — Devices tab](docs/screenshot.png)

## How It Works

The add-on runs on your Home Assistant instance and manages everything — device discovery, the job queue, and the web UI. One or more **build workers** (lightweight Docker containers) run on any machine on your network and do the actual compiling. Workers poll for jobs, build the firmware, and push it directly to your ESP devices via OTA.

```
                              ┌──────────────┐
                         ┌───►│   Worker 1   ├───► ESP devices
  Home Assistant         │    └──────────────┘
┌──────────────────┐     │    ┌──────────────┐
│  ESPH Distributed├─────┼───►│   Worker 2   ├───► ESP devices
│  (this add-on)   │     │    └──────────────┘
└──────────────────┘     │    ┌──────────────┐
                         └───►│   Worker N   ├───► ESP devices
                              └──────────────┘
```

A built-in local worker is included (starts paused). Increase its slot count in the Workers tab to start compiling immediately — no external setup required.

## Installation

### HA Add-on

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fweirded%2Fdistributed-esphome)

Or manually: **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → add `https://github.com/weirded/distributed-esphome`.

Then install **ESPHome Distributed Build Server** from the store.

### Standalone Server (Docker)

```bash
docker run -d \
  --name distributed-esphome-server \
  --network host \
  -v /path/to/esphome/configs:/config/esphome \
  -v esphome-dist-data:/data \
  -e SERVER_TOKEN=your-secret-token \
  ghcr.io/weirded/esphome-dist-server:latest
```

The web UI is available at `http://your-host:8765`. Use `--network host` for mDNS device discovery.

To test pre-release builds from the `develop` branch, use the `:develop` tag instead of `:latest`. The tag is updated on every push to `develop`.

## Web UI

Access via the HA sidebar (**ESPH Distributed**) or directly at `http://your-ha-host:8765`.

- **Devices** — all ESPHome configs with online/offline status, firmware version, config-changed indicator, and HA integration status. Compile individual, all, or only outdated devices. Inline Monaco YAML editor with ESPHome schema autocomplete and validation. Rename, delete, restart devices, copy API keys, view live logs. Search/filter, configurable columns, bulk operations.
- **Queue** — live job status with build logs. Retry failed jobs, cancel in-progress ones. Auto-prunes after one hour.
- **Workers** — connected build workers with system info (CPU, memory, disk, ESPHome version). Adjust slot count (0 = paused), clean per-worker or all build caches, remove offline workers. **+ Connect Worker** provides a ready-to-run `docker run` command. Workers running an out-of-date Docker image are flagged with a clickable "image stale" badge.

Dark/light theme toggle in the header.

## License

This project is licensed under the [MIT License](LICENSE).

## Support

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-orange?logo=buy-me-a-coffee&logoColor=white&style=for-the-badge)](https://buymeacoffee.com/weirded)
