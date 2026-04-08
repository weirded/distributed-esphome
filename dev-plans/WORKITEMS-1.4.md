# Work Items — 1.4.0

Theme: **Full replacement for the stock ESPHome dashboard.** Every feature the built-in UI has, this has too — plus everything we've already added on top. After this release, there's no reason to use the stock dashboard.

## Create Device

- [ ] **2.1a Create device: empty template** — wizard modal with name, platform, board, WiFi from secrets
- [ ] **2.1b Create device: clone existing** — duplicate a config with new name

## Firmware Download & Flashing

- [ ] **3.1a Worker extracts firmware binary** — read .bin after compile, POST to server
- [ ] **3.1b Server stores firmware** — `/data/firmware/<target>/`, metadata endpoint
- [ ] **3.1c Download button on device row** — `GET /ui/api/targets/{f}/firmware`
- [ ] **3.2a Web Serial flashing** — esp-web-tools integration, manifest endpoint
- [ ] **3.2b Server serial flashing** — list ports on HA host, esptool.py flash endpoint

## Web Serial Logs

- [ ] **4.1d Web Serial logs** — browser-side USB serial log viewer (Web Serial API)

## Live Log Tail After Update

- [ ] **4.5 Auto-connect device logs after OTA** — when viewing a job's log modal, automatically connect to the device's native API log stream after OTA completes, like `esphome run` does (compile → upload → tail logs)

## Thread / IPv6 Support

- [ ] **4.6 Thread device IP display** (GitHub #17) — Thread devices use IPv6 and don't show an IP address in the dashboard. Display IPv6 addresses and add a wifi/thread indicator to the device row.

## Device Adoption

- [ ] **2.4 Device adoption/import** — discover unconfigured devices, adopt with project URL

## Open Bugs & Tweaks

