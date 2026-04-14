# Work Items — 1.4.1

Theme: **UI quality + HA native integration.** Harden the frontend (split the DevicesTab god component, close accessibility gaps, clean up the API layer, backfill e2e coverage), and make Distributed ESPHome a first-class HA citizen with native services, update entities, and mDNS discovery.

## UI Cleanup

- [x] ~~**QS.1**~~ WONTFIX *(1.4.1-dev.5 audit)* — `src/lib/utils.ts` exports `cn()` (tailwind-merge + clsx), which is imported by 7 shadcn components (`ui/dialog.tsx`, `ui/badge.tsx`, `ui/button.tsx`, `ui/checkbox.tsx`, `ui/dropdown-menu.tsx`, `ui/select.tsx`, `ui/input.tsx`). The original grep in this item missed the `@/lib/utils` alias path. Keeping the file.
- [x] **QS.2** *(1.4.1-dev.5)* — `aria-label` (+ `aria-pressed` on the toggles) added to the 5 icon-only buttons:
  - App.tsx theme toggle (☀/☾) — `aria-label` + `aria-pressed={theme==='light'}`
  - App.tsx streamer mode (👁/🔒) — `aria-label` + `aria-pressed={streamerMode}`
  - DevicesTab row hamburger (⋮) — already added in QS.16 (`aria-label="More actions"`)
  - DevicesTab column picker (⚙) — `aria-label="Toggle columns"`
  - EsphomeVersionDropdown refresh (↻) — already added during PR #54 review
- [x] **QS.3** *(1.4.1-dev.5)* — Converted `<span onClick>` to `<button type="button">` for Secrets, theme toggle, streamer toggle in App.tsx. SortHeader already landed in QS.21.
- [x] **QS.4** *(1.4.1-dev.5)* — Replaced `data.key!` non-null assertion in `getApiKey()` with an explicit null-check that throws `Error('Server did not return an API key')`. Callers (DeviceContextMenu) now get a meaningful message instead of crashing downstream on `clipboard.writeText(undefined)`.
- [x] **QS.5** *(1.4.1-dev.5)* — Device interface already had `compile_target?: string | null` (the referenced line had moved); added the JSDoc block clarifying the Device-vs-Target distinction and what `compile_target: null` means (unmanaged device, no matching YAML).
- [x] **QS.6** *(1.4.1-dev.5)* — Dropped the custom `JSON.stringify`-based `deepCompare`. SWR's default stable-hash compare already prevents re-renders when polled data is structurally unchanged, and the custom version was O(n) per tick + broke on undefined/circular + hid legitimate key-order differences.
- [x] **QS.7** *(1.4.1-dev.5)* — Replaced the five `onError: () => {}` silent swallows with a `logSwrError(key)` helper that does `console.error('SWR', key, err)`. Each SWR key (`serverInfo`, `versions`, `workers`, `devices`, `queue`) now bubbles errors to the console with its identity attached. Stretch (top-of-page banner when `serverInfo` SWR has an error) not implemented — deferred to WORKITEMS tbd if we actually see errors in the logs.

## API Layer Cleanup

- [x] **QS.8** *(1.4.1-dev.12)* — Added `parseResponse<T>(response, errorTag)` and `expectOk(response, errorTag)` helpers at the top of `api/client.ts`. Both delegate to a shared `_readError` that tries `response.json().error` first, then falls back to `<errorTag> (HTTP <status>)`. ~30 boilerplate blocks (`if (!r.ok) { const data = await r.json().catch(...); throw new Error(...); }`) collapsed into single helper calls. File size unchanged in lines but the redundant pattern is gone — one place to fix the error path if it changes.
- [x] **QS.9** *(1.4.1-dev.12)* — Named response interfaces at the top of `api/client.ts`: `CompileResponse`, `CancelResponse`, `RetryResponse`, `RemoveResponse`, `ClearResponse`, `ScheduleResponse`, `SaveTargetResponse`, `CreateTargetResponse`, `RenameTargetResponse`, `ApiKeyResponse`, `JobLogResponse`, `ValidateResponse`, `SecretKeysResponse`, `EsphomeSchemaResponse`. Replaced inline `as { enqueued: number }` and similar casts. Wire contract is now self-documenting and exported types can be imported by tests/components.
- [x] **QS.10** *(1.4.1-dev.12)* — `getTargets`, `getDevices`, `getWorkers`, `getQueue`, `getServerInfo`, `getEsphomeVersions`, `getTargetContent`, `getJobLog`, `getArchivedConfigs` all now route through `parseResponse<T>` so server-provided `error` strings propagate up instead of being swallowed by a generic `"Failed to fetch X"`. Stretch goal (top-of-page error banner on serverInfo SWR error) deferred — `logSwrError` from QS.7 already lands the error in the console.

## Component Hygiene

- [x] **QS.11** *(1.4.1-dev.13)* — New `components/ui/label.tsx` exporting `<Label>` for the field-label pattern (block, uppercase, tracking-wide, muted). Replaced 10 hand-rolled `<label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">…</label>` instances across `ConnectWorkerModal` (8), `UpgradeModal` (2), and `DeviceTableModals` (1). `htmlFor` prop forwarded for accessibility — wired `htmlFor="rename-device-name"` on the rename modal.
- [x] **QS.12** *(1.4.1-dev.13)* — `RenameModal` now uses the existing `<Input>` wrapper instead of a raw `<input style={{...}}>`. The inline style block (`width: 100%, padding: 8px 12px, background: var(--surface2), border: 1px solid var(--border), borderRadius: var(--radius), color: var(--text), fontSize: 14`) is gone — `Input` already encodes the canonical look. Also swapped the inline-styled `<label>` and `<p>` to use Tailwind utilities for the small typography tweaks.
- [x] **QS.13** *(1.4.1-dev.13)* — New `components/ui/button-group.tsx` exporting `<ButtonGroup>` — a segmented-button wrapper that strips child borders/radii via descendant selectors and re-adds the segment dividers. Replaced the inline `<div style={{ display: 'flex', gap: 0, border: ..., borderRadius: ..., overflow: 'hidden' }}>` with two children that each had `style={{ borderRadius: 0, border: 'none' }}` overrides in `ConnectWorkerModal`'s shell toggle. The `ScheduleModal` mode-toggle the workitem mentioned was already gone (folded into `UpgradeModal`'s radio buttons in 1.4.0); only one current user, but the component is in place for future segmented controls.
- [x] **QS.14** *(1.4.1-dev.17)* — Audit and convert inline `style={{ ... }}` to Tailwind. Migrated ~100 inline styles across the high-leverage tab/column files: `useDeviceColumns.tsx` (32), `WorkersTab.tsx` (21), `QueueTab.tsx` (18), `DevicesTab.tsx` (18), `SchedulesTab.tsx` (13). Common patterns folded: `fontSize: 10/11/12` → `text-[Npx]`, `color: 'var(--…)'` → `text-[var(--…)]`, `display: 'inline-flex', alignItems: 'center', gap: N` → `inline-flex items-center gap-N`, `fontFamily: 'monospace'` → `font-mono`, `cursor: 'pointer'` → `cursor-pointer`, `fontStyle: 'italic'` → `italic`. Only genuinely dynamic styles kept inline (computed colors from runtime state, conditional opacity).
- [x] **QS.15** *(1.4.1-dev.16)* — **Decision: Lucide everywhere.** Documented in CLAUDE.md under Design Judgment: *"All UI icons come from lucide-react. No emoji glyphs (🕐 📅 📌), no HTML entities (`&#8942;`, `&#9881;`), no custom SVGs inline."* Migration touches 10 files. All emoji status indicators become colored Lucide icons (🕐→Clock, 📅→Calendar, 📌→Pin, 🔒/👁→EyeOff/Eye, ☀/☾→Sun/Moon, ✓/✗→Check/X, ●→Circle filled). All HTML entities become Lucide (`⋮`→MoreVertical, `⚙`→Settings2, `↻`→RotateCw, `↓`→Download, `↗`→ExternalLink, `▲/▼`→ChevronUp/Down in the shared SortHeader — cascades to all 11 sortable columns). Each icon-only button retains its `aria-label`; icons that carry semantic meaning beyond decoration (status, pin, trigger kind) wrap in a `<span title="…">` so hover still reveals context. Lucide 1.7.0 was already a dep via shadcn primitives; no new install.

## DevicesTab Split

The current `DevicesTab.tsx` is **1,173 lines with 24 hooks** and an ESLint disable for missing deps. Splitting it unblocks the 1.5 tag/group-by work that touches the same file.

- [x] **QS.16** *(1.4.1-dev.2)* — Replaced hand-rolled `DeviceMenu` with shadcn `DropdownMenu`. Dropped the manual positioning logic (`translateX(-100%)`, viewport-flip math, click-catching backdrop). New `components/devices/DeviceContextMenu.tsx`; placement, focus trap, click-outside, Escape, and keyboard nav now come from Radix.
- [x] **QS.17** *(1.4.1-dev.2)* — Extracted the 369-line columns `useMemo` into `components/devices/useDeviceColumns.tsx`. Removed the `// eslint-disable-next-line react-hooks/exhaustive-deps`. DevicesTab.tsx 1,001 → 631 lines.
- [x] **QS.18** *(1.4.1-dev.2)* — Extracted bulk Actions dropdown + bulk schedule modal into `components/devices/DeviceTableActions.tsx`. Owns its own `bulkScheduleOpen` state.
- [x] **QS.19** *(1.4.1-dev.2)* — Moved `RenameModal` + `DeleteModal` to `components/devices/DeviceTableModals.tsx`. RenameModal re-exported so existing App.tsx imports keep working.
- [x] **QS.20** *(1.4.1-dev.2)* — Memoized `handlePin`/`handleUnpin` in DevicesTab and `handleCompile`/`handleOpenUpgradeModal`/`handleDeleteDevice`/`handleRenameDevice`/`switchTab` in App.tsx so `useDeviceColumns`' dep array actually caches across SWR polls.
- [x] **QS.21** *(1.4.1-dev.2)* — Extracted shared `SortHeader` to `components/ui/sort-header.tsx`. Click target is a real `<button>` (semantic HTML); the `<th>` gets `aria-sort` via a `getAriaSort()` helper. Cascaded to all 11 sortable columns across Devices, Queue, Schedules.

## EditorModal + Utils Split

- [x] **QS.22** *(1.4.1-dev.15)* — New `components/editor/` submodule splitting the ~230 lines of Monaco glue out of EditorModal.tsx:
  - `yamlValidation.ts` — `ESPHOME_SCHEMA`, `collectSyntaxMarkers`, `validateYaml`, `validateYamlDebounced`, `loadComponentList`, + the `_componentList` / `_validationTimer` module-level state.
  - `completionProvider.ts` — `getConfigVars`, `findParentComponent`, `currentLineIndent`, `COMMON_SUB_KEYS`, plus `registerEsphomeCompletionProvider` (idempotent — gated on an internal flag so re-mounts don't duplicate) and `setEsphomeVersion` for the async provider to read the current version.
  - `monacoSetup.ts` — orchestrator `setupEsphomeEditor(editor, monaco)` that wires everything. EditorModal's `handleEditorDidMount` shrank to ~10 lines: store refs, call the orchestrator, add the dirty-decoration change listener. EditorModal.tsx 619 → 319 lines (-48%).
- [x] **QS.23** *(1.4.1-dev.15)* — Split `src/utils.ts` into `utils/format.ts` (timeAgo, stripYaml, fmtDuration, haDeepLink), `utils/cron.ts` (formatCronHuman), `utils/jobState.ts` (isJob* + getJobBadge). Old `src/utils.ts` kept as a barrel re-export so existing `from '../utils'` callsites work with zero change; new code should import from the submodule.
- [x] **QS.24** *(1.4.1-dev.15)* — Dropped the unused `onRename` prop from `EditorModal.Props` and the `void _onRename` compat line. Also removed the `onRename={…}` passed from `App.tsx` (the handler it wrapped was never called).

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

- [x] **SP.1** *(1.4.1-dev.7)* — Added `compression_middleware` to the aiohttp app that calls `response.enable_compression()` on any `StreamResponse` that's not a WebSocket and doesn't already have `Content-Encoding`. aiohttp honors the client's `Accept-Encoding` so it's a no-op on clients that don't send gzip, and skips already-compressed responses. Works for every `/ui/api/*` JSON response, static JS/CSS assets, and the INDEX_HTML template — all uncompressed before. On a 50-device `/ui/api/targets` response (~40-50 KB) this is a ~5× shrink, and on the 1 Hz polls for workers/devices/queue it adds up fast over mobile/VPN links.
- [x] **SP.2** *(1.4.1-dev.7)* — `/ui/api/queue` now strips `log` from **every** job in the list response, not just pending/working. Previously terminal jobs carried up to 512 KB of log each in the 1 Hz poll; 10 finished jobs = ~5 MB/s of redundant payload on steady-state (the log modal already fetches individually). Frontend: QueueTab's `hasLog` changed from `job.log || inProgress` to `job.state !== 'pending'` (terminal jobs still show the Log button because the modal lazy-loads via `/ui/api/jobs/{id}/log`). LogModal's terminal-job path now also calls `startPolling(jobId)` instead of writing `currentJob.log` directly — does one full HTTP fetch and stops as soon as `finished: true`.
- [x] **SP.3** *(1.4.1-dev.7, already fixed + small cleanup)* — The referenced `app.get` vs `app["_rt"]` key mismatch was already fixed in 1.4.0 (commit `3ac6ded`). Live `ha addons logs` verification: the repeated INFO messages I saw were all during the push-to-hass-4 restart window (add-on restarts ~10 s apart during deploy); in steady state the logs fire exactly once per startup and then stay silent until the actual HA ESPHome add-on version changes. Small cleanup nonetheless: demoted `scanner.set_esphome_version`'s own INFO log to DEBUG since the three callers (on_startup, pypi_version_refresher, `/ui/api/esphome-version` POST handler) already log their own INFO with better context ("Active ESPHome version: X", "…detected: X", "…changed to X via UI"), and the generic helper was just duplicating the message at startup.

## Dependency Updates

Triage and merge the 8 open Dependabot PRs. Group into low-risk auto-merge, medium-risk CI-verify, and high-risk human review per the v1.3.1 release-checklist pattern.

### Low-risk — merge on green CI

- [ ] **DU.1** [PR #53](https://github.com/weirded/distributed-esphome/pull/53) — `globals` 17.4.0 → 17.5.0 (ui devDep, patch bump, ESLint globals list)
- [ ] **DU.2** [PR #51](https://github.com/weirded/distributed-esphome/pull/51) — `typescript-eslint` 8.58.0 → 8.58.2 (ui devDep, patch bump)
- [ ] **DU.3** [PR #52](https://github.com/weirded/distributed-esphome/pull/52) — `lucide-react` 1.7.0 → 1.8.0 (ui dep, minor; icon library, only affects rendered icons; if QS.15 adopts Lucide universally, bump here first)

### Medium-risk — merge after full Playwright + smoke test

- [ ] **DU.4** [PR #49](https://github.com/weirded/distributed-esphome/pull/49) — `@base-ui/react` 1.3.0 → 1.4.0 (ui dep, minor). Powers every shadcn wrapper (Button, Dialog, DropdownMenu, Select, Checkbox). Run the full 43-test mocked suite + hass-4 prod suite before merging. Watch for changes in focus management, portal positioning, or event bubbling on dialogs/dropdowns.
- [ ] **DU.5** [PR #50](https://github.com/weirded/distributed-esphome/pull/50) — `@types/node` 24.12.0 → 25.6.0 (ui devDep, major). Pure type change, but Node 25 typings may tighten or add new required fields and surface new type errors in `vite.config.ts` or any Node-API usage. Verify `tsc -b` is clean after bump.

### High-risk — human review required

- [ ] **DU.6** [PR #48](https://github.com/weirded/distributed-esphome/pull/48) — `docker/build-push-action` v6 → v7 (actions, major). Read v7 release notes — action inputs or default behaviours may have changed. Affects both `publish-client.yml` and `publish-server.yml`. Test on a dry-run workflow dispatch before merging to main.
- [ ] **DU.7** [PR #47](https://github.com/weirded/distributed-esphome/pull/47) — `docker/login-action` v3 → v4 (actions, major). Usually a stable bump (same `registry`/`username`/`password` inputs), but confirm against v4 release notes. Affects both publish workflows.
- [ ] **DU.8** [PR #46](https://github.com/weirded/distributed-esphome/pull/46) — `actions/checkout` v4 → v6 (actions, major, two versions jumped). v5 and v6 both required Node 24 on the runner; verify our runners have it (ubuntu-latest is fine). Affects `ci.yml`, `compile-test.yml`, and both publish workflows. Read v5 + v6 release notes for any flag renames.

### Process

- [ ] **DU.9** After all 8 merge, rerun `bash scripts/refresh-deps.sh` if any Python `requirements.txt` direct deps end up bumped by transitive resolution. Not expected since all 8 PRs are npm or GitHub Actions, but confirm.
- [ ] **DU.10** If any PR is rebased by Dependabot after merging an earlier one (conflicts in `package-lock.json`), let Dependabot handle the rebase automatically (`@dependabot rebase` comment) rather than merging manually.

## Open Bugs & Tweaks

- [ ] **#1** ([GitHub](https://github.com/weirded/distributed-esphome/issues/56)) — Top bar doesn't scroll on mobile (iOS). The header/nav row is sticky/fixed on narrow viewports, so the ESPHome logo, version dropdown, Secrets/theme toggles, and worker/version chips can't be reached when the viewport is narrower than their combined width. Fix candidates: allow horizontal scroll on the header's flex container at narrow widths, or collapse secondary controls (secrets, theme, streamer) into a kebab menu below a mobile breakpoint. Verify on iOS Safari — the existing `theme-responsive.spec.ts` has narrow-viewport tests but doesn't exercise header scrolling.
- [x] **#2** *(1.4.1-dev.3)* — Hamburger menu closed on every 1Hz SWR poll. Regression from QS.16: the new shadcn `DropdownMenu` lived inside the row's actions cell, where re-mounts (triggered by columns memo invalidation on `activeJobsByTarget` and inline-arrow refs) tore down its internal open state. Fix: lifted open state to DevicesTab as `menuOpenTarget: string | null`, threaded through `useDeviceColumns` to `DeviceContextMenu` as controlled `open` + `onOpenChange` props. The state now survives any number of row remounts because it lives outside the row tree. Also updated two e2e tests to use `getByRole('menuitem')` since Radix's items are correctly typed as menuitems (was `getByRole('button')` matching the old hand-rolled `<button>` elements). 
- [x] **#3** *(1.4.1-dev.4)* — After the #2 fix the menu stayed open but the content visibly flashed on every 1Hz SWR poll. Cause: SWR hands us a fresh `target` object reference each poll (same values, new object), so `DeviceContextMenu` re-rendered unconditionally — Radix's overlay briefly re-mounted/animated each time. Fix: wrapped `DeviceContextMenu` in `React.memo` with a custom `propsEqual` that compares only the `Target` fields actually read in render (`target`, `has_restart_button`, `has_api_key`, `pinned_version`) plus `open`, and treats function props as always-equal (identity changes don't affect behavior because they close over the same underlying handlers). The menu now renders once and stays rendered across polls. Also fixed the `e2e-hass-4/cyd-office-info.spec.ts` live-logs smoke test to use `getByRole('menuitem')` instead of `getByRole('button')` (same Radix-menuitem fix as the two mocked tests in #2). 
- [x] **#4** *(1.4.1-dev.6)* — Even after #3's `React.memo` on `DeviceContextMenu`, the overlay visibly twitched while the menu was open. Likely root cause: the actions-cell body was still an inline arrow inside `useDeviceColumns` that React reconciled on every poll. Even though the memo'd menu itself was skip-rendered, the surrounding `<Button>Upgrade</Button><Button>Edit</Button>` siblings re-evaluated every tick with fresh inline `onClick` closures and a fresh `style={{...}}` object literal, which nudged the trigger's bounding box enough for Base UI's Positioner to re-fire. Fix: extracted the cell body into a dedicated `React.memo`'d `ActionsCell` component (`components/devices/ActionsCell.tsx`) with a tight prop compare (target fields actually read, `inFlight`, `menuOpen`); moved the inline `style` to a module-level const so the `<div>` style prop is referentially stable; added `data-[state=closed]:!animate-none` to the DropdownMenu popup so any residual state cycle is invisible instead of animating. Also updated the four `header span[title*="..."]` selectors in mocked e2e tests (theme + streamer toggles) to `header button[...]` to match the `<span>`→`<button>` conversion landed in QS.3.
- [x] **#5** *(1.4.1-dev.10)* — AssertionError flood from SP.1's compression middleware. Three iterations to get right:
  - **dev.7 (original)** — `response.enable_compression()` called on any non-WebSocket StreamResponse. Tripped `aiohttp/web_response.py:451 assert self._payload_writer is not None` via `FileResponse` (routes.add_static), which has its own Range/cache/compression pipeline incompatible with enable_compression().
  - **dev.8** — narrowed to `type(response) is web.Response` (excludes FileResponse). Moved the assertion to line 818 (`assert self._body is not None`) — fires on `web.Response(status=204)` returned by worker-API deregister/cancel-assignment endpoints.
  - **dev.9** — short-circuit on status 204/304 and None/empty bodies. Cleared the asserts. Replaced by an `UserWarning: Synchronous compression of large response bodies (46306540 bytes)` — the worker job-claim endpoint returns a JobAssignment with a base64-encoded tarball of the entire config dir (~46 MB).
  - **dev.10 (final)** — restricted middleware to `/ui/api/*` paths. Worker tier (`/api/v1/*`) runs worker↔server on a LAN and shouldn't block the event loop gzipping tarballs. UI-tier compression is the actual SP.1 goal anyway. Log now clean.
- [x] **#6** *(already fixed by #2 + #4)* — CI failure monitor's first catches on develop. All four already resolved or superseded:
  - [CI #24408342243](https://github.com/weirded/distributed-esphome/actions/runs/24408342243) failure on `44f8445` (QS.16-21 DevicesTab split bundle rebuild) — 2 mocked Playwright failures in `create-device.spec.ts` ("duplicate device" flow). Old selectors targeted the hand-rolled context menu; fixed in bug #2 which moved tests to `getByRole('menuitem')`.
  - [CI #24410409557](https://github.com/weirded/distributed-esphome/actions/runs/24410409557) failure on `41817f6` (QS.1-QS.7 UI hygiene) — 5 mocked Playwright failures on theme toggle and streamer mode tests. Old selectors matched `header span[title*="..."]`; fixed in bug #4 which updated them to `header button[...]` after the `<span onClick>`→`<button>` conversion from QS.3.
  - [CI #24413471559](https://github.com/weirded/distributed-esphome/actions/runs/24413471559) and [CI #24413738329](https://github.com/weirded/distributed-esphome/actions/runs/24413738329) — two `ESPHome Compile Tests` **cancelled** runs on `adb9348` and `a0703c7` (SP.1-3 server perf). Cancelled by `concurrency.cancel-in-progress` when follow-up commits landed; no real failure to fix.
- [x] **#7** *(1.4.1-dev.11, partial)* — First Supervisor warning (regex mismatch) fixed by fully-qualifying the image path in `ha-addon/build.yaml`: `python:3.11-slim` → `docker.io/library/python:3.11-slim`. Same image, but now satisfies the Supervisor's `^([a-zA-Z\-\.:\d{}]+/)*?([\-\w{}]+)/([\-\w{}]+)(:[\.\-\w{}]+)?$` regex. Also updated `ha-addon/Dockerfile` to `ARG BUILD_FROM=docker.io/library/python:3.11-slim` + `FROM ${BUILD_FROM}` so the build.yaml selection is actually honored (previously the hardcoded `FROM python:3.11-slim` ignored whatever Supervisor injected as `--build-arg`). The second warning (build.yaml deprecated) is **left as-is** — moving fully off build.yaml needs a glibc-based Python base image, and HA's ghcr.io base images are alpine/musl-only for Python. PlatformIO toolchains require glibc. Revisit when HA ships a Debian-Python base, or if we change our PlatformIO install strategy.
- [x] **#8** *(not-a-regression — hass-4 is stale)* — Log monitor flagged `UserWarning: Synchronous compression of large response bodies (46306540 bytes)` on hass-4. This is the SP.1 aiohttp warning from the worker job-claim endpoint gzipping a 46 MB config tarball — already fixed in #5 final (commit `585327f` scopes the compression middleware to `/ui/api/*` only, excluding `/api/v1/*` worker endpoints). The warning appears because `hass-4` is still running **1.4.0-dev.52** (pre-release), not the current `1.4.1-dev.10` develop. Will disappear on next `./push-to-hass-4.sh`.
- [x] **#9** *(1.4.1-dev.11, transient)* — hass-4 Supervisor Docker build cascade at 2026-04-14 10:48. The Supervisor tried to rebuild the add-on image `local/amd64-addon-esphome_dist_server:1.4.0-dev.52` and failed:
  > `ERROR [supervisor.docker.addon] Docker build failed for local/amd64-addon-esphome_dist_server:1.4.0-dev.52 (exit code 1)`
  > `#2 ERROR: failed to authorize: failed to fetch anonymous token: Get "https://auth.docker.io/token?scope=repository%3Alibrary%2Fpython%3Apull&service=registry.docker.io": dial tcp [2a06:98c1:3106::6812:2bb2]:443: connect: network is unreachable`
  > `ERROR [supervisor.addons.addon] Could not build image for app local_esphome_dist_server`
  
  Root cause: hass-4's Docker tried to pull `python:3.11-slim` over IPv6 and IPv6 routing to `auth.docker.io` was broken (or the host didn't have working v6 to that endpoint). Cascaded into `Ingress error: Cannot connect to host 172.30.32.1:8765`.
  
  **Resolved on its own** at 2026-04-14 ~10:59. Manually re-triggered `ha addons update` after the dev.11 push and the build succeeded immediately (Docker daemon retried, network probably fell back to IPv4, auth went through). 1.4.1-dev.11 came up clean. Closing as transient. If it recurs, the `/etc/docker/daemon.json` `{"ipv6": false}` knob is the standard workaround.
- [x] **#10** *(1.4.1-dev.14)* — Dropped `armhf`, `armv7`, `i386` from `config.yaml` `arch:` and from `build.yaml` `build_from:`. ESPHome compilation is effectively 64-bit-only now; no real-world worker users on those archs. Supervisor's "deprecated arch values" warning gone.
- [x] **#11** *(1.4.1-dev.14)* — Both `_log_poll_warning` callsites in `ha_entity_poller` (template API + states API) now pick the hint based on status class:
  - **5xx** → "HA Core may be restarting; will retry on the next poll" (the right remedy — wait for HA to come back)
  - **401/403** → "check homeassistant_api: true in config.yaml" (the original hint, kept where it's actually correct)
  - other → no hint, just the bare HTTP code
  Demote-to-debug behavior from 1.3.1 #5 unchanged.
- [x] **#12** *(transient)* — Supervisor `ERROR [supervisor.addons.manager] Version changed, use Update instead Rebuild` at 2026-04-14 10:58:29. Artifact of a Supervisor `ha app rebuild` call firing while the stored add-on version on disk was different from the Supervisor's cached version for the same slug — typically seen during the `./push-to-hass-4.sh` Reload/Update/Rebuild loop. No action needed; the script already handles this by retrying `ha app update` first, which is what eventually succeeded. Not a code bug.
- [x] **#13** *(transient — Docker Hub)* — `Publish Client Docker Image` workflow failed on `develop` @ `59a8301` ([run 24417779600](https://github.com/weirded/distributed-esphome/actions/runs/24417779600)) — the `Build and push` step's buildx output is dominated by an HTML error page (complete with base64-encoded Docker Hub logo), ending in `##[error]buildx failed with: <html...>`. The previous publish ([run 24417488903](https://github.com/weirded/distributed-esphome/actions/runs/24417488903) on `c61be24`, 6 minutes earlier) and the next run on develop both succeeded. Classic symptom of Docker Hub serving a 503/504 error page during base-image pull (probably `library/python:3.11-slim` — same dep as bug #9's hass-4 failure). The commit itself (`fix: drop deprecated archs (#10) + better 5xx hint (#11)`) didn't touch the Dockerfile, so this is pure transient flake. **Re-run the workflow** from the Actions UI (or it'll get retried naturally on next push) — no code fix. If this becomes a pattern, consider pinning `python:3.11-slim` to a digest or switching to the HA base image (`ghcr.io/home-assistant/...`) which would also close bug #7/#9. Two failures attributable to Docker Hub reliability issues in one day (the earlier hass-4 one at 10:48, this one at 19:06) is noise, not a trend — revisit if we see three in a week.
- [ ] **#14** ([GitHub](https://github.com/weirded/distributed-esphome/issues/58)) — Version selection visibility. The ESPHome version picker in the UpgradeModal is rendered either too low in the dialog or below/behind the list of device entries, partially obscured. Reporter's screenshot shows the dropdown anchored below the visible modal area. Likely causes: (a) the `<Select>` portal is z-indexed below the modal's overlay, or (b) the dropdown anchor position is computed before the modal finishes scrolling/sizing and lands off-screen, or (c) the dropdown opens downward on a tall modal with its content near the bottom edge and overflows the viewport. Fix: verify the portal's z-index is above the Dialog overlay, and/or constrain the Select's `flip`/`shift` middleware so it opens upward when there isn't room below. Repro: open any device's Upgrade modal on a narrower-than-default viewport and click the version dropdown — the dropdown list should be fully visible and interactive.

