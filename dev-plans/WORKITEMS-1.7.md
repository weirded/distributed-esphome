# Work Items — 1.7.0

Theme: **ESPHome dashboard parity.** Every feature the stock ESPHome UI has, this has too. Create devices, flash over serial, tail logs after OTA, adopt discovered devices. Also: remote compilation for cloud-based build workers.

## Create Device

- [ ] **2.1a Create device: empty template** — wizard modal with name, platform, board, WiFi from secrets
- [ ] **2.1b Create device: clone existing** — duplicate a config with new name

## Web Serial Flashing

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

## Remote Compilation

Allow compiling on VPS servers not on the local network. Builds on 1.4's firmware download infrastructure — the remote worker compiles and sends firmware back to the server, then a local agent (the HA add-on itself or a local worker) handles OTA separately.

- [ ] **RC.1 Compile-only worker mode** — worker compiles and POSTs firmware binary to server instead of OTA-flashing; reuses 1.4's firmware storage
- [ ] **RC.2 Server-side OTA** — server runs `esphome upload` or OTA protocol against local devices using stored firmware
- [ ] **RC.3 Two-phase job lifecycle** — new job states for compile-complete-awaiting-OTA; UI shows firmware ready + OTA trigger button
- [ ] **RC.4 GitHub Actions integration** — optional: trigger builds via GitHub Actions workflow

## Open Bugs & Tweaks

