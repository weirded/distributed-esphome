# ESPHome Distributed Build Server

Offload ESPHome firmware compilation to remote machines. This add-on coordinates the job queue and serves the web UI; one or more lightweight Docker containers running on other hosts do the actual compiling and push firmware to your devices via OTA.

This is useful if Home Assistant runs on a Raspberry Pi or other low-power hardware where ESPHome compilation is slow. Build workers can run on any faster x86 or ARM machine on your network — including Apple Silicon Macs.

## Installation

If you are reading this, the add-on is already installed. Start the add-on, then open the web UI via the **ESPH Distributed** entry in the HA sidebar.

The add-on will work without any external build workers: it manages the queue and discovers your devices, and the web UI is fully functional. You add build workers separately (see below).

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `token` | `""` | Shared secret used to authenticate build workers. Leave empty to auto-generate a token on first start. The token is shown in the web UI under **Workers → Connect Worker**. |
| `job_timeout` | `600` | How long (seconds) a build worker has to complete a compile job before it is considered timed out and re-queued. |
| `ota_timeout` | `120` | How long (seconds) the OTA upload step is allowed to take before it is treated as a failure. |
| `worker_offline_threshold` | `30` | Seconds since the last heartbeat before a connected worker is shown as offline in the UI. |
| `device_poll_interval` | `60` | How often (seconds) the add-on polls your ESP devices via the native API to read their running firmware version. |

If you change `token` after build workers are already running, you must update `SERVER_TOKEN` on each worker and restart them.

## Adding Build Workers

Build workers run as Docker containers on any machine that has network access to both this add-on (port 8765) and your ESP devices (OTA port 3232).

### Quick start — docker run

Open the web UI, go to the **Workers** tab, and click **+ Connect Worker**. A pre-filled `docker run` command is shown with your server URL and token already substituted. Copy and run it on any Docker host.

```bash
docker run -d --restart unless-stopped \
  -e SERVER_URL=http://homeassistant.local:8765 \
  -e SERVER_TOKEN=your-token \
  -v esphome-versions:/esphome-versions \
  ghcr.io/weirded/esphome-dist-client:latest
```

The `esphome-versions` volume persists the ESPHome virtualenv cache so reinstalls are not needed after a container restart.

### Packaged archive (start.sh / stop.sh)

For machines where you prefer not to type a long `docker run` command, use the packaging script from the project repository to build a self-contained archive:

```bash
# On a machine with the repo checked out:
./package-client.sh http://homeassistant.local:8765 your-token

# Copy the archive to the build host:
scp dist/esphome-dist-client-*.tar.gz user@build-host:/tmp/

# On the build host:
cd /tmp && tar -xzf esphome-dist-client-*.tar.gz
SERVER_URL=http://homeassistant.local:8765 SERVER_TOKEN=your-token ./start.sh
```

Use `./start.sh --background` to detach after startup. `./stop.sh` stops and removes the container. `./uninstall.sh` removes the container and image.

### Worker environment variables

The most commonly needed variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_URL` | required | Full URL to this add-on, e.g. `http://homeassistant.local:8765` |
| `SERVER_TOKEN` | required | Must match the `token` option configured above |
| `MAX_PARALLEL_JOBS` | `2` | How many compile jobs to run simultaneously on this worker |
| `ESPHOME_SEED_VERSION` | — | Pre-install this ESPHome version at startup so the first job does not wait |
| `HOST_PLATFORM` | — | Override the OS string shown in the UI, useful on macOS Docker hosts |

## How It Works

1. The add-on scans `/config/esphome/*.yaml` for compilable targets and re-scans every 30 seconds.
2. When you trigger a compile (single device, all, or outdated only), jobs are added to the queue.
3. Connected build workers poll the server every 5 seconds. When a worker claims a job it receives the full ESPHome config directory — including `secrets.yaml` — as a compressed archive.
4. The worker ensures the required ESPHome version is installed (up to 3 versions cached on disk via LRU), runs `esphome compile`, then pushes the firmware directly to the device via OTA.
5. The result — compile log and OTA outcome — is posted back to the server.
6. The device poller picks up the newly running firmware version via mDNS within the next poll cycle.

### Job retries and timeouts

Jobs that exceed `job_timeout` are re-queued automatically. After 3 failed attempts a job is permanently marked failed. On add-on restart, any jobs that were in progress reset to pending and are re-queued.

### Worker auto-update

Workers check the server version on every heartbeat. If the server is running a newer worker version the worker downloads the updated code and restarts itself automatically, but only when it is idle (not mid-job).

## Web UI

The UI is accessible via the HA sidebar or directly at `http://your-ha-host:8765`.

**Devices tab** — lists all YAML configs found in your ESPHome config directory. For each device it shows online/offline status, the firmware version currently running on the device, and whether the config has changed since the last compile. You can trigger a compile for individual devices, all devices, or only those running outdated firmware. An inline YAML editor is also available.

**Queue tab** — shows live job status with build logs. Failed jobs can be retried; in-progress jobs can be cancelled. A badge on the tab shows the count of active and failed jobs.

**Workers tab** — lists connected build workers with online/offline status, current job per slot, ESPHome version, and system information (architecture, CPU, memory, OS). Workers can be disabled or removed. The **+ Connect Worker** button provides the pre-filled `docker run` command for adding new workers.

## Security Considerations

This add-on is designed for trusted home networks. Key points to be aware of:

**Single shared token.** All build workers authenticate with one Bearer token. The token is visible in the web UI to anyone who can access it.

**Plaintext HTTP.** Traffic between the server and build workers — including the auth token, your ESPHome configs, and `secrets.yaml` — is unencrypted. On a typical home LAN this is acceptable; on a shared or untrusted network, consider routing traffic through a VPN or a TLS-terminating reverse proxy.

**secrets.yaml is sent to every worker.** The config bundle sent to build workers includes `secrets.yaml` so that ESPHome can resolve substitutions during compilation. Every connected build worker will have access to your Wi-Fi credentials, API keys, and OTA passwords.

**Worker auto-update.** Build workers automatically download and execute updated code from the server. A compromised server or a man-in-the-middle on the HTTP connection could push arbitrary code to all workers.

**UI API relies on HA Ingress authentication.** The web UI endpoints have no independent authentication — they rely on HA's Ingress proxy to authenticate users. If port 8765 is reachable directly (bypassing HA), anyone on the network can manage the queue and read build logs without credentials.

Only connect build workers that you trust and that run on machines you control.

## Troubleshooting

**Worker shows as offline immediately after starting.**
Verify `SERVER_URL` points to the correct host and port (default 8765) and that the host running the worker can reach that address. Check that `SERVER_TOKEN` matches the `token` option in the add-on configuration.

**Jobs stay in PENDING indefinitely.**
No build worker is picking them up. Confirm at least one worker is shown as online in the **Workers** tab. If a worker shows offline, check the container logs for connection errors.

**OTA step fails but compile succeeds.**
The build worker cannot reach the ESP device. The worker must have direct network access to the device on port 3232. If the worker runs on a different VLAN or behind a firewall, OTA traffic must be permitted between the worker host and your ESP devices. Also check that the device is powered and reachable on the network.

**Device shows wrong firmware version or no version.**
The add-on discovers devices via mDNS (`_esphomelib._tcp`) and polls them via the native API. The device must be on the same network segment as the HA host (or mDNS must be forwarded across VLANs). Version updates appear within `device_poll_interval` seconds of a successful OTA.

**Compile fails with ESPHome version errors.**
Check the build log in the **Queue** tab. If an ESPHome version cannot be installed (e.g. network issue on the worker host), the job will retry. You can pre-install a known-good version by setting `ESPHOME_SEED_VERSION` on the worker container.

**"Config changed" indicator does not clear after a successful compile.**
The indicator compares the YAML modification time against the last successful compile timestamp recorded in the queue. If you edit the file between triggering a compile and it completing, the indicator will remain set until the next successful compile.
