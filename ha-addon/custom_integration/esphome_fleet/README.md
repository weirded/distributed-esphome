# ESPHome Fleet HA integration

This subtree is the Home Assistant **custom integration** that pairs
with the ESPHome Fleet add-on (the aiohttp server in `ha-addon/server/`).
It turns the add-on into a first-class HA citizen:

- Discovers the add-on via Supervisor or `_esphome-fleet._tcp` mDNS
  (`config_flow.py`).
- Polls `/ui/api/*` every 30 s through a `DataUpdateCoordinator`
  (`coordinator.py`) plus a real-time WebSocket event stream
  (`ws_client.py`) for instant updates.
- Exposes one HA device per target YAML, per build worker, and one "hub"
  device for the add-on itself (`device.py`).
- Ships sensors, binary sensors, update entities, buttons, and numbers
  (`sensor.py`, `binary_sensor.py`, `update.py`, `button.py`, `number.py`).
- Registers three HA services (`esphome_fleet.compile`, `.cancel`,
  `.validate`) in `services.py` backed by `services.yaml`.
- Fires `esphome_fleet_compile_complete` HA events on terminal
  state transitions so automations can react to finished builds.

## How it gets into `/config/custom_components/`

The integration is **not installed via HACS or manually**. The add-on's
`integration_installer` (in `ha-addon/server/integration_installer.py`)
copies this directory into `/config/custom_components/esphome_fleet/`
on every add-on startup, patching `manifest.json`'s `version` field
with the add-on's `VERSION`. The source of truth lives here; the
install target is derived.

When this directory changes, `push-to-hass-4.sh` detects it via a hash
file and restarts HA Core after deploy — `ha core restart` is required
because HA loads integrations once at startup and doesn't hot-reload
Python modules.

## Why `esphome_fleet` when the repo is `distributed_esphome`?

The repo, Docker image names, add-on slug, and internal Python modules
keep their original `distributed_esphome` / `esphome-dist-*` form —
changing those would force a migration on every existing install. The
**user-facing** branding is "ESPHome Fleet" (see `CLAUDE.md`'s Naming
convention section). The integration's `domain: esphome_fleet` picks
the user-facing name so HA users see a clean `esphome_fleet.compile`
service and an `esphome_fleet` integration in their UI, without the
legacy `distributed_` prefix leaking through.

## Single instance

`manifest.json` sets `"single_config_entry": true`. Running more than
one Fleet add-on against the same HA Core would require rethinking the
`_first_coordinator` service-helper contract in `services.py`; we keep
the UX simple and reject a second setup at the HA config-flow layer.
