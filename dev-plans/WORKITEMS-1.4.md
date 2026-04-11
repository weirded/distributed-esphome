# Work Items — 1.4.0

Theme: **Fleet management and automation.** Novel features you can't get from the stock ESPHome dashboard — controlling many devices at scale, pinning versions, scheduling upgrades, and downloading compiled firmware.

## Version Pinning

Pin individual devices to a specific ESPHome version. Pinned devices compile with their pinned version even during bulk upgrades. The pin is stored in the per-device `# distributed-esphome:` comment block (`pin_version: 2024.11.1`) — invisible to ESPHome's parser, travels with the config through git/backups.

**Foundation landed in 1.4.0-dev.2:** The generic metadata comment system (`read_device_meta()` / `write_device_meta()`) and the `POST /ui/api/targets/{f}/meta` endpoint already support reading/writing `pin_version`. The `/ui/api/targets` response includes `pinned_version`, and `needs_update` respects it. What remains is the UI + compile guards.

- [x] **VP.1 Scanner: read pin** *(1.4.0-dev.2)* — `read_device_meta()` extracts `pin_version` from the comment block; `get_device_metadata()` merges it as `pinned_version` into the metadata dict returned to callers.
- [x] **VP.2 Scanner: write/clear pin** *(1.4.0-dev.2)* — `write_device_meta()` handles arbitrary key-value writes including `pin_version`. The `POST /ui/api/targets/{f}/meta` endpoint wraps it for the UI (set `pin_version` to a value, or `null` to clear).
- [x] **VP.3 API endpoints** *(1.4.0-dev.3)* — `POST /ui/api/targets/{target}/pin` (set pin, body `{version}`) and `DELETE /ui/api/targets/{target}/pin` (clear pin). Dedicated convenience endpoints on top of the generic `/meta`.
- [x] **VP.4 Hamburger menu** *(1.4.0-dev.3)* — "Pin to current version" (pins to the device's running_version) / "Unpin version (X.Y.Z)" (when pinned). Uses `pinTargetVersion` / `unpinTargetVersion` API client functions.
- [x] **VP.5 UpgradeModal** *(1.4.0-dev.5)* — Warning banner when upgrading a pinned device with a different version. Shows the pinned version, the selected compile version, and explains the pin itself won't change (future scheduled/bulk upgrades still use the pinned version). Revised from "keep pinned checkbox" to a simpler informational warning per bug #10 — the pin is never auto-changed by an upgrade.
- [x] **VP.6 Visual indicator** *(1.4.0-dev.2)* — 📌 pin icon next to device name when `pinned_version` is set (with tooltip showing the version).
- [x] **VP.7 Compile guard** *(1.4.0-dev.3)* — when a pinned device is included in bulk "Upgrade All/Outdated", the compile endpoint reads `pin_version` from the device's metadata comment and uses it instead of the global version. An explicit `version_override` from the UpgradeModal still takes precedence.
- [x] **VP.8 Scheduled Upgrades integration** *(1.4.0-dev.2)* — the `schedule_checker()` background task uses `meta.get("pin_version") or get_esphome_version()` as the compile version, so pinned devices respect their pin during scheduled runs.

## Device Organization

Key/value tags (like AWS resource tags), stored in the per-device `# distributed-esphome:` comment block as a `tags:` map. Users can group the Devices table by any tag key (Notion-style table groups) and filter by `key=value`.

Format in the YAML comment block:
```yaml
# distributed-esphome:
#   tags:
#     location: kitchen
#     floor: "1"
#     env: prod
#     owner: stefan
```

The existing `tags` field landed in 1.4.0-dev.2 as a simple list of strings — that needs to migrate to a key/value map. `read_device_meta()` should accept both shapes during the transition (list → coerce to `{tag: ""}` or warn-and-ignore) and `write_device_meta()` always writes the map shape going forward.

- [ ] **DO.1 Tag schema migration** — `read_device_meta()` accepts either list-of-strings (legacy) or string-keyed map; normalizes to map on read. `write_device_meta()` always writes the map. Add a unit test that round-trips both shapes.
- [ ] **DO.2 Tag CRUD endpoints** — `POST /ui/api/targets/{f}/tags` (set, body `{key, value}`), `DELETE /ui/api/targets/{f}/tags/{key}` (clear). Reuses `read_device_meta()` / `write_device_meta()`. Validates key is non-empty, max 64 chars, no leading/trailing whitespace; value is string, max 256 chars (allow empty for "key present, no value").
- [ ] **DO.3 Tag editor UI** — modal opened from the device hamburger menu ("Edit tags…"). Shows current tags as editable rows: `[key] [value] [×]` plus an "+ Add tag" button. Save persists via `POST /ui/api/targets/{f}/tags` for each changed entry. Datalist autocomplete on `key` from the union of all keys currently in use across the fleet.
- [ ] **DO.4 Tag column** — toggleable "Tags" column on the Devices tab showing each device's tags as compact `key=value` chips (truncated, full set in tooltip). Sortable by string representation.
- [ ] **DO.5 Group-by-tag selector** — top-of-table dropdown: "Group by: [None / location / floor / env / …]". When set, rows are grouped under sticky group headers showing the value (e.g., "location: kitchen — 4 devices"). Devices without that tag key fall into an "— unset —" group at the bottom. Group state persists in localStorage. Like Notion table groups: collapsible group headers, group-level select-all checkbox.
- [ ] **DO.6 Filter by tag** — top-of-table filter chips: click a tag chip in any row to add it as a filter (`location=kitchen`). Multiple chips AND together. Clear-all button. Filter state in URL query string so it survives reloads and is shareable.
- [ ] **DO.7 Bulk tag operations** — extend multi-select on the Devices tab: "Set tag…" (prompts for key+value, applies to all selected via `Promise.all`), "Remove tag…" (prompts for key, removes from all selected). Single summary toast per bulk action.
- [ ] **DO.8 Bulk delete + bulk validate** *(formerly 6.6)* — extend multi-select: bulk delete and bulk validate alongside the existing bulk upgrade.

## Scheduled Upgrades ([#30](https://github.com/weirded/distributed-esphome/issues/30))

Per-device cron scheduler for automatic compile+OTA. Schedule is stored in the device's `# distributed-esphome:` comment block (`schedule: 0 2 * * 0`, `schedule_enabled: true`), not a separate file. The server's `schedule_checker()` background task fires every 60s, computes next run via `croniter`, and enqueues jobs when due. Respects version pinning.

**Core landed in 1.4.0-dev.2.** What shipped:
- Storage is per-device in the YAML comment (not `/data/schedules.json` as originally planned — simpler, no orphan entries, travels with the file).
- `croniter>=1.3` (pure Python) for cron parsing — changed from "stdlib-only" because writing a correct cron parser is more code and more bugs than the 50KB library.
- 7 scheduler unit tests + 11 metadata read/write tests.

- [x] **SU.1 Schedule storage** *(1.4.0-dev.2)* — stored in the per-device `# distributed-esphome:` comment block: `schedule` (5-field cron), `schedule_enabled` (bool), `schedule_last_run` (ISO datetime). Read via `read_device_meta()`, written via `write_device_meta()`. Surfaced in `/ui/api/targets` response.
- [x] **SU.2 Cron parser + scheduler loop** *(1.4.0-dev.2)* — `schedule_checker()` background task in `main.py`, runs every 60s. Uses `croniter` to compute next fire time from last_run. Enqueues compile+OTA via `queue.enqueue()`. Marks jobs with `Job.scheduled = True`. Persists `schedule_last_run` back to the YAML comment after each fire. Lazy-imports croniter so a missing install doesn't crash the server.
- [x] **SU.3 API endpoints** *(1.4.0-dev.2)* — `POST /ui/api/targets/{f}/schedule` (set cron + enable), `DELETE .../schedule` (clear), `POST .../schedule/toggle` (flip enabled). Plus the generic `POST /ui/api/targets/{f}/meta` for arbitrary metadata writes.
- [x] **SU.5 Schedule create modal** *(1.4.0-dev.2)* — `ScheduleModal.tsx`: preset dropdown (Daily 2am, Weekly Sunday 2am, Monthly 1st 2am, Every 6h, Every 12h) + "Custom" raw cron input + enabled toggle + Save/Remove/Cancel. Opened from the device hamburger menu ("Schedule Upgrade...").
- [ ] **SU.4 Schedules overview** — optional: a section somewhere that lists ALL scheduled devices at a glance (currently visible per-device via the 🕐 icon, but no single-page "all schedules" view).
- [ ] **SU.6 History** — last N runs per schedule with success/fail counts linking back to queue entries. (Currently the job's `scheduled: true` flag identifies scheduler runs in the queue, but there's no aggregated history view.)

## Build Operations

- [ ] **5.2 Build cache status** — workers report cache stats, display in UI

## Firmware Download

After a successful compile, extract the firmware binary and make it downloadable from the UI. Foundation for remote compilation in a later release.

- [ ] **3.1a Worker extracts firmware binary** — read .bin after compile, POST to server
- [ ] **3.1b Server stores firmware** — `/data/firmware/<target>/`, metadata endpoint
- [ ] **3.1c Download button on device row** — `GET /ui/api/targets/{f}/firmware`

## Open Bugs & Tweaks

- [x] **#1** *(1.4.0-dev.3)* — Immediate device state refresh after mutations. Currently only post-OTA and mDNS events trigger an immediate `refresh_target()` / SWR mutate. Other actions leave the UI stale for up to 1s (SWR poll) or 60s (device poller). Fix: after each of these actions, invalidate the relevant cached state so the next UI poll sees the change immediately:
  - **File save** — user edits YAML in the editor → `config_modified` flag should flip instantly (scanner cache needs invalidation)
  - **Version pin/unpin** — user pins a device to a version → `pinned_version` in device metadata should appear immediately (scanner cache + SWR mutate)
  - **Schedule create/update/delete** — user modifies a schedule → schedule state should reflect immediately (SWR mutate on the relevant endpoint)

- [x] **2** *(1.4.0-dev.4)* — Richer schedule modal + global schedule button. Rewrote `ScheduleModal.tsx` with a friendly interval picker: "Every [N] [hours/days/weeks] [on DOW] at [HH:MM]" with dropdowns for each field, plus a "Cron" mode toggle for power users. Parses existing cron expressions back into the friendly picker state when possible. Also added "Schedule Selected..." to the bulk actions dropdown — applies the same schedule to all checkbox-selected devices in one operation via `Promise.all(setTargetSchedule(...))`. The modal shows the generated cron expression as a reference preview.

- [x] **3** *(1.4.0-dev.2)* — Cron expression validation. Server-side `croniter(expr)` validates on `set_target_schedule` and returns a 400 with "Invalid cron expression: ..." that the client shows as an error toast.

- [x] **4** *(1.4.0-dev.4)* — All-schedules view. The "Schedule" column is now default-visible on the Devices tab, showing human-readable schedule strings for every device in one place. Sorting by this column groups all scheduled devices together. Combined with the 🕐 clock icon on the name, this gives a complete at-a-glance overview without a separate page.

- [x] **5** *(1.4.0-dev.3)* — Human-readable schedule column. New toggleable "Schedule" column (default off) with `formatCronHuman()` rendering common presets as short strings ("Daily 02:00", "Sun 02:00", "1st 02:00", "Every 6h"). Complex expressions fall back to the raw cron text. Paused schedules show "(paused)" in muted text.

- [x] **6** *(1.4.0-dev.4)* — Pin indicator moved from name column to version column. Shows 📌 + pinned version number next to the running version (e.g., "2026.3.3 📌 2024.11.1").

- [x] **7** *(1.4.0-dev.4)* — Hamburger menu too narrow for "Unpin version (2026.3.3)". Changed from fixed `min-w-[160px]` to `min-w-[200px] w-max max-w-[320px]` so it sizes to content (grows for long text, capped at 320px to prevent viewport overflow).

- [x] **8** *(1.4.0-dev.5)* — Moved "Schedule Selected..." out of the Upgrade dropdown into a new "Actions ▾" dropdown between Upgrade and the column picker gear icon. Cleaner separation: Upgrade dropdown is compile-only, Actions is for bulk metadata operations.

- [x] **9** *(1.4.0-dev.5)* — Pin indicator simplified: just 📌 next to the running version (no repeated version number). The pinned version is in the tooltip and the hamburger menu.

- [x] **10** *(1.4.0-dev.5)* — Pinned-device upgrade warning in UpgradeModal. When the selected compile version differs from the device's pin, an amber warning banner explains: "This device is pinned to X, but this upgrade will compile with Y. The pin itself won't change — future scheduled and bulk upgrades will still use the pinned version." The upgrade honors the modal's selected version without touching the pin (VP.7 already handled the compile guard).

- [x] **11** *(1.4.0-dev.5)* — Refresh button (↻) next to the ESPHome version picker in the top nav. Triggers `mutateEsphomeVersions()` to re-fetch from the server (which queries PyPI). New `onRefresh` prop on `EsphomeVersionDropdown`.

