# ESPHome Fleet

Manage a fleet of ESPHome devices from one place, inside Home Assistant — bulk compiles, scheduled OTA upgrades, per-device version pinning, an inline YAML editor, a job queue you can actually see, and optional distributed compilation so a slow HA host doesn't become a bottleneck.

## Getting Started

Start the add-on, then open the web UI via the **ESPHome Fleet** entry in the HA sidebar.

### First steps

1. Your existing ESPHome configs in `/config/esphome/` are picked up automatically — you should see them on the **Devices** tab.
2. The add-on includes a **built-in local worker** that runs inside the HA host. It starts with one build slot — enough to compile any target sequentially. On a fast host you can raise it to 2–4+ via the `+`/`-` buttons next to `local-worker` on the **Workers** tab. Setting slots to 0 pauses the local worker entirely (useful if you've connected remote workers and want the HA host out of the build loop).
3. To offload compilation to a faster machine, click **+ Connect Worker** in the Workers tab. Pick **Bash**, **PowerShell**, or **Docker Compose**, copy the generated snippet, and run it on whatever machine you want to compile on. The snippet includes your actual server URL and token, so there's nothing to edit. Workers poll the add-on over HTTP for jobs (bearer token auth) and push firmware directly to ESP devices; no inbound ports need to be open on the worker machine, but it does need network reach to the ESP devices it'll flash.
4. **Restart Home Assistant** once after the first install. The add-on ships a custom HA integration (`esphome_fleet`) that it auto-installs to `/config/custom_components/` on startup — but Home Assistant only loads integrations at Core startup, so the integration stays dormant until you restart HA. Go to **Settings → System → Restart** and pick *Restart Home Assistant*.
5. After the restart, Home Assistant will pop an "ESPHome Fleet discovered" notification within a few seconds. Accept it to get all the devices, workers, and the add-on itself as real HA devices with entities.

> **Upgrading the add-on later?** If a Fleet release changes the integration (check the changelog — look for the `Integration` heading), you'll need to restart Home Assistant again after the add-on finishes updating. Restarting *the add-on* alone doesn't pick up integration changes, because HA Core only loads Python integrations at boot.

### Add-on configuration

Everything user-facing is configured from the **Settings drawer** inside the web UI — click the gear icon in the top-right of the header. As of 1.6.0 the Supervisor **Configuration** tab is intentionally empty: all the old options (`token`, timeouts, thresholds, `require_ha_auth`) moved into the Settings drawer so edits apply instantly without restarting the add-on. Existing values from pre-1.6 installs are auto-migrated on first boot.

The drawer is split into **Basic** and **Advanced** tabs. Basic holds the settings you'll touch most (versioning, authentication, display). Advanced holds the plumbing knobs (retention, cache, timeouts, polling) that rarely need tweaking after install.

### Basic tab

| Section | Setting | Default | What it does |
|---|---|---|---|
| Config versioning | Enable versioning | *(asks on first login)* | Master toggle for the local git-backed history of `/config/esphome/`. When on, every save is a commit, and the Devices hamburger + Queue tab gain history/diff/rollback affordances. When off, Fleet runs zero git commands. Fresh installs show a one-time onboarding modal that asks your preference; existing git repos auto-enable. |
| Config versioning | Auto-commit on save | on | Every save creates a local git commit in `/config/esphome/`. Turn off if you manage this directory with your own git workflow and only want manual commits through the History panel. |
| Config versioning | Commit author name / email | `HA User` / `ha@distributed-esphome.local` | Identity used on Fleet-created commits. Respects the repo's own `user.name`/`user.email` if you've set one — the Settings values only kick in when the repo has nothing configured. |
| Authentication | Server token | *(auto-generated)* | Shared bearer token workers and direct-port API use. Changing it will disconnect existing workers until their `SERVER_TOKEN` env var is updated. Masked by default — click the eye to reveal, the copy button to grab for a worker snippet. |
| Authentication | Require HA auth on direct port | on | When on, port-8765 requests outside the Ingress tunnel must carry a valid HA bearer token or this server token. Leave on unless you have a specific reason to allow anonymous direct-port access. Ingress access is unaffected either way. |
| Display | Time format | auto | How times render in the Queue, History, and log timestamps. `auto` follows the browser's resolved locale (`Intl.DateTimeFormat` hour12); `12h` / `24h` force the format. |

### Advanced tab

| Section | Setting | Default | What it does |
|---|---|---|---|
| Job history | Retention (days) | 365 | How long to keep per-job compile history. `0` = unlimited. |
| Disk management | Firmware cache size (GB) | 2.0 | Maximum disk space the server will use to cache compiled firmware. |
| Disk management | Job log retention (days) | 30 | How long to keep per-job build logs on disk. `0` = unlimited. |
| Timeouts | Job timeout (seconds) | 600 | Maximum wall-clock seconds a single compile job may run. Bump if you have unusually large configs or a slow worker. |
| Timeouts | OTA timeout (seconds) | 120 | Maximum seconds for the OTA upload after a successful compile. Bump if you have a slow / lossy WiFi link to some devices. |
| Timeouts | Worker offline threshold (seconds) | 30 | Seconds without a heartbeat before a worker is flagged offline in the Workers tab. Don't set below the worker's heartbeat interval (default 10s) — 30s gives three missed beats before the UI flips. |
| Polling | Device poll interval (seconds) | 60 | How often the server polls each ESPHome device over its native API to refresh online status and running-firmware version. |

Settings are stored in `/data/settings.json` inside the add-on and survive updates.

After upgrading to 1.6.0 from an earlier release, your pre-existing `options.json` values (token, timeouts, thresholds, `require_ha_auth`, plus any 1.5 disk/history fields) are one-shot imported into `settings.json` on first boot. From then on, editing values in Supervisor has no effect — edit them in the Settings drawer instead. The Supervisor **Configuration** tab is intentionally empty post-1.6.

## What's on the Web UI

**Devices.** Every ESPHome config in one place. Columns for online status, current firmware version, HA entity link, IP address, WiFi vs Ethernet, network details, schedule, and ESPHome version. Click Upgrade on any row to compile + OTA that device. The row menu (⋮) exposes live logs, restart, rename, duplicate, pin, delete, and copy-api-key (for devices with a native-API encryption key).

**Queue.** Every compile job — pending, running, succeeded, failed. Live build logs. Retry or cancel a job, clear finished jobs in bulk, or download the compiled `.bin` file (for jobs run in "download only" mode).

**Workers.** Every connected worker — local and remote — with platform info, slot count, cache size, current job, and uptime. Workers running an outdated Docker image are flagged with an "image stale" badge so you know to `docker pull && docker restart` them.

**Schedules.** Every scheduled upgrade in one view. Recurring (daily/weekly/monthly or full cron) and one-time future schedules. Schedules live in the device YAML itself so they travel with your config and respect each device's pinned ESPHome version.

**Header** has a dark/light theme toggle, a "streamer mode" that blurs tokens and secrets (for screen-sharing demos), the currently-selected ESPHome version (changes for all new compiles unless overridden per-device via pinning), a shortcut to edit `secrets.yaml`, and a link to [ESPHome Web](https://web.esphome.io/) for browser-based initial flashing.

### Running different ESPHome versions across your fleet

The header dropdown sets the **global** ESPHome version — every new compile uses it unless a device is pinned. To pin a device, open the row menu (⋮) on the **Devices** tab and choose **Pin ESPHome version**. Pinned devices stick to their version regardless of what the global selector says; scheduled upgrades on a pinned device respect its pin.

Typical uses:

- **Beta-test a release** on one low-stakes device (a garage sensor, an outdoor thermometer) while leaving the rest of the fleet on the stable version.
- **Hold a picky device back** on a known-good version indefinitely when a newer ESPHome release breaks a component you depend on.
- **Stage an upgrade** — flip the global version, compile one device, verify, then bulk-upgrade everything outdated.

Workers install whatever ESPHome version each job asks for, on demand, into a local per-version venv and keep a small LRU cache so subsequent jobs using that version start instantly. `MAX_ESPHOME_VERSIONS` on the worker (default 3) controls the cache size.

### Keeping workers up to date

Workers don't auto-update. The built-in local worker upgrades whenever the add-on does, but **remote workers you started with `docker run` stay pinned to the image version you installed them with** until you refresh the container yourself.

**Why it matters.** Worker images carry the protocol client, the ESPHome install lifecycle, and any CVE patches shipped since your install. The server enforces a minimum image version (`MIN_IMAGE_VERSION` in `ha-addon/server/constants.py`) — once a worker falls below that, it keeps heartbeating but refuses new protocol fields and the Workers tab tags it with an orange **Image stale** badge.

**How to tell.** Open the **Workers** tab. Stale workers carry an **Image stale** badge next to the hostname; hover to see the exact refresh command. The per-row version cell also shows the client's baked-in image version.

**Refresh command (Linux / Mac / Windows with Docker CLI):**

```bash
docker pull ghcr.io/weirded/esphome-dist-client:latest
docker restart <your-worker-container-name>
```

The `<your-worker-container-name>` is whatever you passed via `--name` when you first ran the container — `docker ps --format '{{.Names}}'` lists them. The restart reuses the old container's volumes and env vars, so the worker reconnects with the same token and hostname.

**Docker Compose variant:**

```bash
docker compose pull
docker compose up -d
```

(Run it in the directory that has your `docker-compose.yaml`. Compose detects that the image changed and rebuilds the container in-place.)

**Full re-install** (needed when upgrading across a `MIN_IMAGE_VERSION` bump, or when changing host platform, max-parallel-jobs, or token): remove the old container and re-run the snippet from **+ Connect Worker**. The built-in Connect Worker modal always emits a snippet that matches the currently-deployed server.

**Automating refreshes.** We deliberately don't ship an auto-update mechanism — every option adds a dependency (Watchtower, What's Up Docker, Compose + cron, Kubernetes controllers…) we'd then have to support. Pick whatever scheduler you already use on the host and have it run the refresh command on a cadence you're comfortable with. We don't endorse a specific tool.

**Verifying signatures.** Every Fleet server + client image is signed with cosign and carries an SBOM attestation. See the `Verifying what you're running` section below for the verify command before you pull on security-sensitive hosts.


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
