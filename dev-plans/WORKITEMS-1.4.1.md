# Work Items — 1.4.1

Theme: **UI quality + HA native integration.** Harden the frontend (split the DevicesTab god component, close accessibility gaps, clean up the API layer, backfill e2e coverage), and make Distributed ESPHome a first-class HA citizen with native services, update entities, and mDNS discovery.

## UI Cleanup

- [ ] **QS.1 Delete dead file `src/lib/utils.ts`** — contains only unused `clsx`/`cn` re-exports (grep confirms zero imports). Scaffold leftover from shadcn.
- [ ] **QS.2 Icon-only buttons: add `aria-label`** — 5 buttons currently read as emoji glyphs or silence to screen readers:
  - `App.tsx:449` theme toggle (☀/☾)
  - `App.tsx:464` streamer mode toggle (👁/🔒)
  - `DevicesTab.tsx:700` row hamburger (⋮)
  - `DevicesTab.tsx:854` column picker (⚙)
  - `EsphomeVersionDropdown.tsx:56` refresh (↻)
- [ ] **QS.3 Convert `<span onClick>` to `<button>`** — 4 violations of the "semantic HTML" design judgment rule:
  - `App.tsx:437` Secrets button
  - `App.tsx:449-463` theme toggle
  - `App.tsx:464-470` streamer mode toggle
  - `DevicesTab.tsx:408` SortHeader (folded into QS.21 below)
- [ ] **QS.4 Fix non-null assertion in `getApiKey()`** — `api/client.ts:237` uses `data.key!` without validation. Crashes at call site with a confusing message if the server omits `key`. Replace with explicit null check + thrown `Error`.
- [ ] **QS.5 Add `compile_target` to `Device` type** — `types/index.ts` Device interface is missing `compile_target?: string | null`, but `DevicesTab.tsx:333` reads it. Document the Device-vs-Target distinction in JSDoc.
- [ ] **QS.6 Remove SWR `deepCompare` using `JSON.stringify`** — `App.tsx:88` serializes the entire response to a string on every 1Hz poll. Remove the custom `compare`, let SWR's default shallow compare handle it.
- [ ] **QS.7 SWR `onError` — log at minimum** — `App.tsx:93,98,108,113,120` all silently swallow errors. At minimum, `console.error('SWR', key, err)`. Stretch: top-of-page banner when `serverInfo` SWR has an error set.

## API Layer Cleanup

- [ ] **QS.8 Extract `parseResponse<T>` helper** — every POST endpoint in `api/client.ts` repeats the same ~3-line error-handling pattern. Extract into a shared helper. Reduces ~150 lines of boilerplate.
- [ ] **QS.9 Define response types at module top** — replace inline `as { enqueued: number }` casts with named interfaces (`CompileResponse`, `CancelResponse`, etc.). Self-documents the wire contract.
- [ ] **QS.10 Propagate server error details in getX() functions** — `getTargets`, `getDevices`, `getWorkers`, `getQueue` currently throw generic `"Failed to fetch X"`, losing server-provided error text.

## Component Hygiene

- [ ] **QS.11 Extract `<Label>` component** — `components/ui/label.tsx`. The same label className pattern appears 10+ times across modals. Extract as a shadcn-style Label with proper `htmlFor`/`id` association.
- [ ] **QS.12 Replace raw `<input>` in RenameModal** — `DevicesTab.tsx:198-204` uses raw `<input>` with inline style object. Swap for `<Input>` wrapper.
- [ ] **QS.13 Add `<ButtonGroup>` component (or `variant="group"`)** — shell toggle in `ConnectWorkerModal` and mode toggle in `ScheduleModal` both use inline style overrides. Extract proper component.
- [ ] **QS.14 Audit and convert inline `style={{ ... }}` to Tailwind** — 25+ instances across `ConnectWorkerModal`, `DeviceLogModal`, `WorkersTab`, `QueueTab`, `EsphomeVersionDropdown`, `StatusDot`.
- [ ] **QS.15 Icon strategy decision + rollout** — currently mixes Lucide, emoji, and HTML entities. Decide and document in CLAUDE.md Design Judgment.

## DevicesTab Split

The current `DevicesTab.tsx` is **1,173 lines with 24 hooks** and an ESLint disable for missing deps. Splitting it unblocks the 1.5 tag/group-by work that touches the same file.

- [ ] **QS.16 Replace hand-rolled context menu with `<DropdownMenu>`** — most visible CLAUDE.md "Default to shadcn/ui" violation. Drop the manual positioning logic entirely.
- [ ] **QS.17 Extract `useDeviceColumns()` hook** — 378-line column definitions into `deviceTableColumns.ts`. Removes the ESLint disable.
- [ ] **QS.18 Extract `DeviceTableActions.tsx`** — bulk actions dropdown, schedule-selected handler, bulk compile.
- [ ] **QS.19 Extract `DeviceTableModals.tsx`** — RenameModal and DeleteModal into their own file.
- [ ] **QS.20 Memoize inline handler props** — wrap `App.tsx` and `DevicesTab` inline arrow functions in `useCallback`.
- [ ] **QS.21 Add `aria-sort` to SortHeader** — fix once, cascades to all 11 sortable columns. Also wraps click target in `<button>`.

## EditorModal + Utils Split

- [ ] **QS.22 Split `EditorModal.tsx` Monaco setup into `editor/` submodule** — extract `monacoSetup.ts`, `completionProvider.ts`, `useYamlValidation.ts`. EditorModal stays as dialog wrapper.
- [ ] **QS.23 Split `src/utils.ts` grab-bag** — into `utils/format.ts`, `utils/jobState.ts`, `utils/cron.ts`.
- [ ] **QS.24 Remove dead `_onRename` parameter in `EditorModal.tsx:232`**.

## Tests and Safety Net

- [ ] **QS.25 Add missing e2e coverage** — mocked Playwright tests for: rename, delete, pin/unpin, upgrade modal, schedule modal, bulk schedule/remove, worker cache clean, column visibility persistence, theme persistence.
- [ ] **QS.26 Add React Error Boundary around `<App />`** — minimal boundary rendering a "Something went wrong — reload" card.
- [ ] **QS.27 Optional polish** — lower-priority items: `ConnectWorkerModal` 8× useState → useReducer, `address_source` union type, `LogModal` setInterval comment, persist sort order, URL query params for deep-linking.

## Playwright Coverage Backfill

### Mocked tests (`ha-addon/ui/e2e/`)

- [ ] **PT.1 `pin-unpin.spec.ts`** — Pin via hamburger → 📌 appears; unpin → 📌 disappears; upgrade modal warning on pinned device; bulk compile request intercepted.
- [ ] **PT.2 `schedule-modal.spec.ts`** — Modal opens in correct mode (Now vs Scheduled); mode switch; create recurring/one-time schedule; pause schedule; edit from Schedules tab.
- [ ] **PT.3 `schedules-tab.spec.ts`** — Table columns/search/filter; checkbox select-all + "Remove Selected"; bulk remove; empty state.
- [ ] **PT.4 `bulk-schedule.spec.ts`** — "Schedule Selected..." and "Remove Schedule from Selected" via Actions dropdown.
- [ ] **PT.5 `queue-extras.spec.ts`** — Triggered column icons; Rerun vs Retry labels; Cancelled badge; Clear doesn't touch cancelled.
- [ ] **PT.6 `modal-sizing.spec.ts`** — Editor/log modal bounding box vs viewport at 1024×768 and 1920×1080.
- [ ] **PT.7 `button-consistency.spec.ts`** — Toolbar button heights equal across all tabs.
- [ ] **PT.8 `cancel-new-device.spec.ts`** — Cancel without saving triggers delete API.

### Prod tests (`ha-addon/ui/e2e-hass-4/`)

- [ ] **PT.9 `schedule-fires.spec.ts`** — One-time schedule fires on real server, auto-clears.
- [ ] **PT.10 `incremental-build.spec.ts`** — Second compile ≥50% faster than first.
- [ ] **PT.11 `pinned-bulk-compile.spec.ts`** — Pinned version honored in bulk compile.

### Fixture updates

- [ ] **PT.12 Update `e2e/fixtures.ts`** — add pinned device, scheduled device, one-time schedule, scheduled queue job, cancelled queue job.

## HA Native Integration

Custom integration that makes Distributed ESPHome a first-class HA citizen: native services callable from automations, `update` entities on the HA dashboard, and zero-config discovery via mDNS. Auto-installed by the add-on on startup (files copied to `/config/custom_components/`, user confirms via the Integrations UI).

**Auto-install mechanism:** The add-on already maps `homeassistant_config` (for reading ESPHome YAMLs). Change to `read_only: false` so we can write to `/config/custom_components/`. On startup, an s6 script compares the bundled integration version against what's installed and copies if newer. Then calls the Supervisor API to reload custom components. This is the same pattern used by other community add-ons — not an official API, but widely used and stable.

**Discovery:** The server advertises `_distributed-esphome._tcp` via mDNS. The integration's `manifest.json` declares a `zeroconf` matcher. HA shows "Distributed ESPHome discovered" → user clicks Configure → one confirmation screen → done. Falls back to manual URL entry if mDNS isn't working.

- [ ] **HI.1 Integration scaffold** — `custom_integration/distributed_esphome/` directory with: `__init__.py`, `manifest.json` (domain, zeroconf discovery, version), `config_flow.py` (mDNS auto-discovery + manual URL fallback), `const.py`, `strings.json`, `translations/en.json`. Integration type: `hub`.
- [ ] **HI.2 Services** — register three HA services:
  - `distributed_esphome.compile` — target (entity/device selector or `"all"`/`"outdated"`), optional `esphome_version`, optional `worker`. Calls `POST /ui/api/compile`.
  - `distributed_esphome.cancel` — job_id or target. Calls `POST /ui/api/queue/cancel`.
  - `distributed_esphome.validate` — target. Calls `POST /ui/api/validate`.
  - Each defined in `services.yaml` with selectors so the HA automation editor gives full autocomplete.
- [ ] **HI.3 Update entities** — one `UpdateEntity` per managed device. `installed_version` from device poller. `latest_version` from global ESPHome version (or pinned version). `async_install()` calls compile API. HA's update card shows "Update available" + "Install" button for free.
- [ ] **HI.4 Sensor entities** — `sensor.distributed_esphome_queue_depth`, per-device firmware version, per-worker active job count.
- [ ] **HI.5 Binary sensor entities** — `binary_sensor.distributed_esphome_<worker>_online` with `device_class: connectivity`.
- [ ] **HI.6 Event firing** — fire `distributed_esphome_compile_complete` event on job terminal state. Data: target, state, duration, version, worker. Automation trigger for "notify me when any compile fails."
- [ ] **HI.7 mDNS advertisement** — server advertises `_distributed-esphome._tcp.local.` with `version` and `base_url` properties.
- [ ] **HI.8 Auto-install on add-on startup** — s6-overlay service script. Compare versions, copy if newer, reload via Supervisor API (`$SUPERVISOR_TOKEN`). Log outcome at INFO.
- [ ] **HI.9 config.yaml change** — `homeassistant_config` mapping to `read_only: false`. Document in `DOCS.md`. PY-4 trigger — bump `IMAGE_VERSION`.
- [ ] **HI.10 Coordinator + polling** — `DataUpdateCoordinator` polls targets/devices/workers/queue every 30s. All entities read from coordinator cache.
- [ ] **HI.11 Device registry** — each managed device registered as an HA device with name, model (board/platform), sw_version, via_device (last worker).
- [ ] **HI.12 Tests** — service call verification, update entity state, config flow mDNS + manual URL, auto-install script.

## Server Performance

- [ ] **SP.1 Enable gzip compression** — add `aiohttp-compress` middleware (or manual `Content-Encoding: gzip`) to the aiohttp app. Currently all JSON responses and static assets are sent uncompressed. A typical 50-device `/ui/api/targets` response (~40-50KB) would compress to ~5-10KB. Apply to all `/ui/api/*` responses and static file serving.
- [ ] **SP.2 Strip job logs from queue list endpoint** — `/ui/api/queue` currently strips `log` from pending/working jobs but includes full logs (up to 512KB each) for finished jobs. 10 finished jobs = ~5MB polled every second. Fix: strip `log` from *all* jobs in the list response. The log modal already fetches logs individually via the existing `/ui/api/jobs/{id}/log` endpoint.
- [ ] **SP.3 Fix version-changed log spam** — `pypi_version_refresher` in `main.py` writes to `app["_rt"]["esphome_detected_version"]` but reads from `app.get("esphome_detected_version")` — key mismatch. Every 30s poll thinks the version "changed" from None → 2026.3.3, logging 3 lines ("changed", "set", "auto-selected") every cycle. Fix the read path to match the write path. Demote steady-state unchanged checks to DEBUG.

## Open Bugs & Tweaks

- [ ] **#56** ([GitHub](https://github.com/weirded/distributed-esphome/issues/56)) — Top bar doesn't scroll on mobile (iOS). The header/nav row is sticky/fixed on narrow viewports, so the ESPHome logo, version dropdown, Secrets/theme toggles, and worker/version chips can't be reached when the viewport is narrower than their combined width. Fix candidates: allow horizontal scroll on the header's flex container at narrow widths, or collapse secondary controls (secrets, theme, streamer) into a kebab menu below a mobile breakpoint. Verify on iOS Safari — the existing `theme-responsive.spec.ts` has narrow-viewport tests but doesn't exercise header scrolling.

