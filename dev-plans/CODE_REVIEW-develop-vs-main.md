# Code Review — `develop` → `main` (ESPHome Fleet 1.4.1)

**Reviewer mood:** grumpy. **Scope:** 147 commits, 141 files, +11,854 / −3,025 LOC. **Verdict in one line:** *lots of ambitious, useful work, wrapped in a changelog that hides it, tested with mocks that don't prove the things most likely to break, and shipped with a couple of real bugs plus one structural foot-gun (multi-instance) that nobody will hit until a user files a bug.*

This is not a small release. It ships a brand-new HA custom integration (~2,400 LOC), a WebSocket event bus, an HA user-auth middleware, firmware download, SBOM attestations, lazy ESPHome install, a big UI refactor, and 55 new tests. You cannot ship that in one public CHANGELOG bullet ("Rebrand: now called ESPHome Fleet"). More on that later.

**Methodology:** three parallel exploration passes produced ~120 candidate findings. I then spot-read the cited lines for every Critical/High claim. Several claims were wrong on verification (see §10) — those have been dropped. Everything below cites a real line I personally read.

---

## 🟢 1.5.0 follow-up status (added 2026-04-17)

Nearly every actionable finding from this review was queued as a `CR.*` workitem in `WORKITEMS-1.5.md` and shipped before the 1.5.0 tag. Summary table below; see each section for inline **Status:** lines pointing at the specific CR item and dev-build that closed it.

| Review section | Closed as | Shipped in |
|---|---|---|
| §2.1 dead `TIMED_OUT` write | CR.4 | 1.5.0-dev.77 |
| §2.2 PY-2 violation (scanner version probe) | CR.9 | 1.5.0-dev.77 |
| §2.3 ghost-user on unparseable `/auth` body | CR.8 | 1.5.0-dev.77 |
| §2.4 multi-instance foot-gun | CR.2 (`single_config_entry: true`) | 1.5.0-dev.77 |
| §2.5 integration ↔ add-on unauthenticated | CR.3 (subsumed by AU.7) | 1.5.0-dev.77 |
| §2.6 `__init__.py:76` fire-and-forget unload | CR.12 | 1.5.0-dev.77 |
| §2.7 device-registry work every tick | CR.14 (diff-skip) | 1.5.0-dev.77 |
| §2.8 sequential coordinator GETs | CR.13 (`asyncio.gather`) | 1.5.0-dev.77 |
| §2.9 `api/client.ts` error-swallowers | CR.5 | 1.5.0-dev.77 |
| §2.10 `integration_installer` non-atomic | CR.10 | 1.5.0-dev.77 |
| §3.1 `manifest.json` half-declared | CR.15 | 1.5.0-dev.77 |
| §3.2 integration tests are mocks in disguise | **Deferred** to 1.6 IT.1 / IT.2 / IT.3 | — |
| §3.3 config flow accepts URL w/o probing | CR.16 | 1.5.0-dev.77 |
| §3.4 EsphomeInstallBanner retry not wired | CR.17 (already present; verified) | 1.5.0-dev.76 |
| §3.5 DIAGNOSTIC category on state sensors | CR.7 | 1.5.0-dev.77 |
| §3.6 `_discovery.py` undocumented | CR.18 | 1.5.0-dev.77 |
| §3.7 integration dir missing README | CR.18 | 1.5.0-dev.77 |
| §4 `waitForTimeout` / E2E quality | CR.6 (+ new **E2E-1** invariant) | 1.5.0-dev.77 |
| §4 `pytest-homeassistant-custom-component` | **Deferred** to 1.6 IT.2 | — |
| §5.1 `require_ha_auth` trade-off documented | CR.20 (+ AU.7 made it mandatory) | 1.5.0-dev.77 |
| §5.2–§5.6 SECURITY_AUDIT refresh | CR.11 (folded into the AU.7 audit pass) | 1.5.0-dev.77 |
| §6.1 rewrite CHANGELOG | CR.1 | 1.5.0-dev.78 |
| §6.2 DOCS.md first-boot note | CR.19 | 1.5.0-dev.77 |
| §6.5 GHCR retention policy | CR.28 | **WONTFIX** (storage headroom) |
| §7.1 event_bus loop / SLA docs | CR.22 | 1.5.0-dev.77 |
| §7.2 naming split rationale in CONTRIBUTING | CR.27 | **WONTFIX** (single-dev project) |
| §7.3 document non-goal: multi-instance | CR.2 (manifest declares it) | 1.5.0-dev.77 |
| §7.4 `app_config.py` precedence docs | CR.21 | 1.5.0-dev.77 |
| §8 perf — parallel GETs (only critical item) | CR.13 | 1.5.0-dev.77 |
| §9.1 CODE_OF_CONDUCT.md / CONTRIBUTING.md | CR.27 | **WONTFIX** |
| §9.3 new invariants (UI-6, E2E-1, HA-1) | CR.23 (UI-6 + E2E-1 shipped; HA-1 deferred) | 1.5.0-dev.77 |
| §9.4 verify lockfile regen | CR.24 | 1.5.0-dev.76 |
| §11 punch-list items 1–8 | CR.1 / CR.2 / CR.3 / CR.4 / CR.5 / CR.6 / CR.7 + IT.1 (deferred) | 1.5.0-dev.77/78 |

**What's still open after 1.5.0:**
- **Integration test strategy rewrite** (review §3.2 / §4 / §9.3 PY-10) — the mock-based tests stayed and got renamed; the proper `pytest-homeassistant-custom-component` rewrite is in `WORKITEMS-1.6.md` as IT.1 / IT.2 / IT.3.
- **HA-1 invariant** (review §9.3) — banning `[class*="monaco"]`-style CSS-substring selectors in Playwright specs. Deferred because the only current usage is Monaco's dynamic class names; a proper fix needs `data-*` test-hook wrappers in the editor component.
- **§6.4 pre-release UX sweep** — the checklist item itself is now institutionalized in `RELEASE_CHECKLIST.md` (UX_REVIEW refresh step); no separate workitem.
- **§9.2 issue template enrichment** — not explicitly queued; low-priority.

The rest of this document stays as the original reviewer capture — every observation that got closed above has an inline **Status:** line added at the start of its subsection.

---

## 1. Verdict and Overall Shape

**What's good (so the critique lands fairly):**
- The refactor hygiene is real. `DevicesTab.tsx` going from 821 LOC to ~150 by extracting `devices/*`, `editor/*`, `utils/{cron,format,jobState,persistState}.ts` is the right kind of change. `components/ui/{button-group,label,sort-header}.tsx` puts primitives where they belong.
- `protocol.py` byte-identity between server and client (PY-6) plus pydantic wire models is the best single structural choice in the codebase.
- `check-invariants.sh` encoding project rules as grep-able CI checks is genuinely clever. PY-8/PY-9 (lockfile coverage; no macOS-only transitives) are the kind of invariants most projects only add after they get bitten twice.
- `integration_installer.py` is small, has a careful `return "skipped_no_source"` path for unit tests, and will not crash the add-on on failure. Good defensive instincts.
- Sequencing of SC.1 → SC.4 → revert SC.4 → SBOMs shows the team is willing to back out a mistake (SC.4) rather than plaster over it.

**What I'm grumpy about:** see everything below.

---

## 2. Real Bugs (verified by reading the cited lines)

### 2.1 `ha-addon/server/job_queue.py:604–606` — dead write that masquerades as a state transition

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.4. Dead `job.state = JobState.TIMED_OUT` write removed; inline comment explains the retry path is "abandoned claim; re-enqueue as PENDING." 132 queue/scanner tests still green.

```python
else:
    job.state = JobState.TIMED_OUT
    # Re-enqueue: reset to pending
    job.state = JobState.PENDING
```
Line 604 assigns `TIMED_OUT` and line 606 immediately overwrites it. The comment between them is literally apologising for the dead write. Functionally harmless — the job ends up `PENDING` for retry, which is the intent — but:
- You can never observe `TIMED_OUT` in a live job. Anyone writing a dashboard query, a test assertion, or a log filter for "how many jobs have timed out on this retry" is looking at a state that is impossible in this branch.
- If someone later removes line 606 thinking "line 604 already sets the state" without reading the comment, the retry stops working.
- Either keep `TIMED_OUT` as a real intermediate state (and persist an event for it) or delete line 604. Don't leave a confused ghost.

**Severity:** Low (not a bug today, latent correctness hazard).

### 2.2 `ha-addon/server/scanner.py:207–214` — PY-2 violation, command not logged

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.9. Added `logger.debug("Running: %s", cmd)` before the subprocess call. DEBUG (not INFO) because this fires on every cache miss; grep-able when the user flips the `esphome_fleet` logger to debug. PY-2 grep tightening itself was not rolled in — left as judgment-reviewed for now.

```python
result = subprocess.run(
    [_server_esphome_bin, "version"],
    capture_output=True, text=True, timeout=10, check=True,
)
```
PY-2 says *"the actual command line must be logged before the subprocess runs."* This is a `version` check, so the cost of a regression is small — but PY-2 is an invariant, not a suggestion, and the grep-able floor (module-level logger present) passes here, which means `check-invariants.sh` did not catch this. That means the invariant is actually *"grep hopes the rest is in code review,"* not *"enforced."* A future subprocess added by someone in a hurry will clear the same bar. If PY-2 matters — and #176/#177/#180 say it does — tighten the grep.

**Severity:** Low (this call; structural issue with the invariant).

### 2.3 `ha-addon/server/ha_auth.py:110–120` — 200-OK with unparseable body returns a ghost user

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.8. `ha_auth._validate_ha_user` now returns `None` on unparseable body and logs a WARNING. Audit logs no longer show "action by None."

```python
if resp.status != 200:
    return None
try:
    data = await resp.json()
except Exception:
    return {"name": None, "id": None, "is_admin": None}
```
When Supervisor's `/auth` returns HTTP 200 with a non-JSON body (which shouldn't happen, but the code admits it might by catching it), this function returns `{"name": None, "id": None, "is_admin": None}`. The middleware then happily attaches that as `request["ha_user"]` and every downstream audit log writes `by None`. Prefer `return None` here: a response we can't parse is not a valid auth, period.

**Severity:** Low (edge case; but silently granting "authenticated as nobody" is exactly the kind of thing that bites you six months later when audit logs are evidence).

### 2.4 Integration services single-entry assumption — real multi-instance foot-gun

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.2. `manifest.json` now declares `"single_config_entry": true`; HA refuses a second entry at the config-flow layer. `_first_coordinator` docstring rewritten to spell out "single-entry by contract."

`ha-addon/custom_integration/esphome_fleet/services.py:76–84` plus `128`, `176`, `184`:
```python
def _first_coordinator(hass: HomeAssistant):
    coordinators = list(hass.data.get(DOMAIN, {}).values())
    ...
    return coordinators[0]
```
Services are registered globally, which is fine. But every handler resolves its target via `_first_coordinator` — *the first configured entry*. If a user has two ESPHome Fleet add-ons (multi-site, dev + prod, lab + prod) and both run this integration, `esphome_fleet.compile` always hits the first one. Silently. No warning in docs, no `coordinator` selector on the service call, no picker in `services.yaml`.

This is a *design choice to not support multi-instance*, not a bug per se, but:
- `manifest.json` doesn't declare `single_config_entry: true`, so HA will cheerfully let a user add a second entry.
- `async_register_services` is idempotent on `has_service` (good), but `async_unregister_services` only tears down when `hass.data[DOMAIN]` is empty, so removing one of two entries leaves services pointing at the survivor — also not documented.
- The right fix is either (a) declare single-instance in the manifest, or (b) add a `base_url`/`entry_id` selector to services. Pick one.

**Severity:** High (quiet data-loss shape: user's service call goes to the wrong fleet and *looks like it worked*).

### 2.5 Integration → add-on communication is unauthenticated

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.3, subsumed by AU.7. The integration now sends the add-on's shared worker token as `Authorization: Bearer`; `CONF_TOKEN` is real and captured both via Supervisor discovery and manual config-flow. `require_ha_auth` flipped to **mandatory** on direct port in 1.5 — the previously-dead `CONF_TOKEN` constant became load-bearing.

`ha-addon/custom_integration/esphome_fleet/coordinator.py:133–148`:
```python
async def _get_json(self, path: str) -> Any:
    url = f"{self._base_url}{path}"
    async with self._session.get(url, timeout=...) as resp:
```
No auth header. The add-on has `require_ha_auth` (AU.1–6) which can require a Bearer token — but the integration never sends one, so if a user turns on `require_ha_auth` the whole integration silently breaks. Meanwhile `CONF_TOKEN` is declared in `const.py:7`, never wired anywhere, never surfaced in the config flow, never stored in the entry data. Dead constant implying abandoned work.

This also means: *the default posture is "the integration relies on the server being on a trusted LAN."* That's a reasonable home-lab assumption, but it is not documented in `DOCS.md` and it is not reconciled against `require_ha_auth`. Pick: either the integration passes a Supervisor-minted bearer, or the docs for `require_ha_auth` explicitly say "turning this on breaks the HA integration until the next release." As-is, users will flip the flag and file a confused bug.

**Severity:** High.

### 2.6 `ha-addon/custom_integration/esphome_fleet/__init__.py:76` — fire-and-forget unload

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.12. `entry.async_on_unload(event_stream.stop)` — HA now awaits WS teardown as part of unload, race eliminated.

```python
entry.async_on_unload(lambda: hass.async_create_task(event_stream.stop()))
```
`async_on_unload` accepts a coroutine function directly. Wrapping the `stop()` call in `async_create_task` decouples unload completion from WebSocket teardown — HA will consider the entry unloaded while the WS handshake is still closing. Under rapid reload-add-reload (which happens during development), you can end up with the old WS leaking for a couple of seconds after HA thinks it's gone. Pass the coroutine function directly: `entry.async_on_unload(event_stream.stop)`.

**Severity:** Low (minor leak under a narrow race; easy fix).

### 2.7 Coordinator triggers device-registry work every 30 s

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.14. Extracted `_compute_live_identifiers` and wired a diff-skip check; `_register_devices` only runs when the identifier set actually changed.

`__init__.py:60–65` installs a listener that calls `_register_devices(...)` on every coordinator update. The coordinator polls every 30 s. So regardless of whether anything changed, HA iterates every target and worker, hits `async_get_or_create` per device, and re-walks `async_entries_for_config_entry` for stale-device pruning. `async_get_or_create` is O(1) on an existing device, so the absolute cost is small, but on idle systems this keeps the device-registry hot unnecessarily.

Trivial fix: diff-check on `coordinator.data` (identifier set from previous call) and skip the listener body when identifiers are unchanged. Home-lab-tolerable today; guaranteed to show up in a profiling trace eventually.

**Severity:** Low.

### 2.8 Coordinator does six *sequential* GETs per tick

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.13. The six `/ui/api/*` GETs now run under `asyncio.gather`. Wall-time win is small on-host; halves server-side handler pressure per tick.

`coordinator.py:61–67`:
```python
info    = await self._get_json("/ui/api/server-info")
targets = await self._get_json("/ui/api/targets")
devices = await self._get_json("/ui/api/devices")
workers = await self._get_json("/ui/api/workers")
queue   = await self._get_json("/ui/api/queue")
versions = await self._get_json("/ui/api/esphome-versions")
```
The comment says "HA's DataUpdateCoordinator is happy with anything under a second." That's true, but 6× localhost RTT + 6× aiohttp session overhead + 6× handler cost every 30 s is still lazier than it needs to be. `asyncio.gather` cuts wall time to ~1× and halves server-side handler load. This is the exact "don't pre-compute, but don't be silly either" spot in the CLAUDE.md performance guidance.

**Severity:** Low.

### 2.9 `ha-addon/ui/src/api/client.ts` — three functions sidestep the unified error path

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.5. `validateConfig` wraps `r.json()` in try/catch so non-JSON errors surface cleanly. `getSecretKeys` + `getEsphomeSchema` route through `parseResponse<T>` and throw on `!r.ok`; SWR's `logSwrError` (QS.7) logs the key + error. New **UI-6** invariant in `check-invariants.sh` bans the `return []`-on-not-ok pattern and caught a straggler (`getScheduleHistory`) that had to be fixed too.

The whole point of the QS.8 refactor (`api/client.ts:52–54` `parseResponse<T>`) is that everything funnels through one place. Three holdouts:

- `validateConfig` (lines 307–318) — calls `r.json() as ValidateResponse` *before* checking `r.ok`. If the server or a reverse proxy returns HTML on error (classic nginx 502, Supervisor proxy hiccup), `r.json()` throws an uncaught `SyntaxError` that bubbles past the intended error branch. The comment says "bespoke handling for non-OK with useful `output`" — fine, but you still need a try/catch around the parse.
- `getSecretKeys` (320–325) — `if (!r.ok) return [];`. Silently returning an empty list on 401/500/anything swallows real errors. Autocomplete "quietly stops working" with no toast, no log, no way for the user to know. Same pattern.
- `getEsphomeSchema` (327–331) — identical.

These aren't crashes; they're category-3 bugs (UI appears to work, functionality is silently degraded). The invariant-lint for "no `fetch()` outside `api/`" (UI-1) should be paired with an internal invariant: "no error path that silently returns a default value without logging and toasting." UI-6, anyone?

**Severity:** Medium.

### 2.10 `ha-addon/server/integration_installer.py:137–141` — `shutil.rmtree` + `copytree` is not atomic

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.10. Install path is now atomic: stage to `<destination>.new` (with `ignore_patterns("__pycache__", "*.pyc")`), patch the staging manifest via `tempfile.mkstemp` + `os.replace`, then `os.replace` the current install to `.old`, swap the staging dir into place, remove `.old`. Any crash between steps leaves the previous install intact.

```python
if destination_dir.exists():
    shutil.rmtree(destination_dir)
shutil.copytree(source_dir, destination_dir)
_patch_manifest_version(...)
```
If the add-on crashes or is killed (Supervisor OOM, host reboot) between `rmtree` and `copytree`, the user's `/config/custom_components/esphome_fleet/` is gone until the next successful start. Combine with `_patch_manifest_version` (also non-atomic — open+write, no tempfile+rename) and you have a small-but-real window where HA sees a half-written manifest.json on the next core restart.

Also, `copytree` default is `symlinks=False` (good, follows them), but there's no check that the source tree is entirely regular files. And if a future packaging change puts `__pycache__` in the source dir, the installer happily copies it into `/config/custom_components/`.

Right patterns: (a) copy to `esphome_fleet.new`, atomically rename over the old dir, (b) atomic manifest write via `os.replace`, (c) `ignore=shutil.ignore_patterns("__pycache__", "*.pyc")`.

**Severity:** Medium (infrequent, but a crash here corrupts *user HA config*, not just add-on state).

---

## 3. The Home Assistant Integration Needs Another Pass

I'm making this its own section because it's half the diff and it's what users will perceive *as* 1.4.1.

### 3.1 `manifest.json` is half-declared

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.15 + CR.2. Added `loggers: ["esphome_fleet"]`, `quality_scale: "bronze"`, and `single_config_entry: true`. Kept the hardcoded `version: "0.1.0"` in the checked-in manifest because `integration_installer._patch_manifest_version` rewrites it from `VERSION` on every install — hand-installers are a non-audience for this release.

```json
{
  "domain": "esphome_fleet",
  "version": "0.1.0",
  "codeowners": ["@weirded"],
  "requirements": [],
  ...
}
```
- **`version: "0.1.0"` hardcoded**, patched at install time by `integration_installer._patch_manifest_version`. If a contributor hand-installs the integration from the repo (a totally normal dev flow), they get a permanent `v0.1.0` and HA shows them outdated. The source of truth should be `VERSION` and the installer should be the only thing that writes `manifest.json:version`; or alternatively, adopt the HACS-style "version isn't required for core-bundled integrations" stance and drop the field.
- **No `quality_scale`.** Every HA integration that wants to be taken seriously declares one (even if it's `"bronze"`). Without it, this looks semi-finished.
- **No `loggers`** — users can't trivially enable debug logging for `esphome_fleet` via the UI.
- **`"requirements": []`** is suspect. The integration imports `aiohttp` (bundled with HA, so OK) and `voluptuous` (bundled), but if anything else gets added later, the empty list will silently become wrong.

### 3.2 Tests are mocks pretending to be integration tests

**Status:** 🟡 DEFERRED to 1.6 — CR.26. The 1.5 cycle chose to accept the mock-heavy state and queue the refactor as IT.1 (rename) + IT.2 (pytest-homeassistant-custom-component rewrite) + IT.3 (contract tests) in `WORKITEMS-1.6.md`. The credibility gap this review flagged is still real; 1.6 closes it.

`tests/test_integration_services.py` is representative. Every test does this:
```python
hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
```
That's not a `HomeAssistant`. The tests exercise the *Python logic inside the handlers*, which is useful, but they don't load the integration under HA's test harness, they don't catch schema drift, they don't catch service-registration timing issues, they don't catch `async_on_unload` misuse (see §2.6 — which is exactly the kind of bug an `async_unload_entry` test would catch).

The right tool for HA integrations is `pytest-homeassistant-custom-component`. The claim in the WORKITEMS that HI.12 ships "37 unit tests covering the integration" should be read as "37 tests that exercise the integration's Python functions in isolation." They will *not* catch:
- A bad `async_on_unload` lambda
- A broken config-flow step flow
- A service registered without a valid schema at HA load time
- `_attr_unique_id` collisions between entities
- `device_info` wiring errors that show up in the HA UI as orphan devices

For a project whose README claims "high quality bar," this is the biggest credibility gap in the release.

### 3.3 Config flow accepts a base URL without testing it

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.16. User step now probes `GET /ui/api/server-info` with a 3 s timeout before creating the entry; on failure, returns a `cannot_connect` form error. New string in `strings.json` + `translations/en.json`. Supervisor-discovered flows skip the probe (Supervisor already vetted the URL).

`config_flow.py:62–81` — user types the URL, the flow calls `_normalize_base_url` (which only validates syntax) and creates the entry. The first real probe happens in `__init__.py:53` via `async_config_entry_first_refresh()`, which `UpdateFailed`s if the server isn't reachable. HA does surface that as a setup error — not silent — but the UX is "entry is created, immediately shows red, user can't tell if their URL was wrong or the add-on is just starting." Better: test connectivity *inside* the user step with a 3 s probe and return a form error.

### 3.4 `EsphomeInstallBanner` and `esphome_install_status` state machine has no failure recovery

**Status:** ✅ VERIFIED ALREADY SHIPPED (1.5.0-dev.76) — CR.17. The retry flow was in fact wired: the `failed` branch renders a **Retry** button that POSTs `/ui/api/esphome/reinstall` via `reinstallEsphome()` in `api/client.ts` and flips the banner back to `installing` once the SWR poll picks up the new status. Confirmed present in `EsphomeInstallBanner.tsx` during the CR.17 audit — original review missed it.

`types/index.ts` adds `esphome_install_status?: 'installing' | 'ready' | 'failed'`. `components/EsphomeInstallBanner.tsx` exists, `reinstallEsphome()` (`api/client.ts:114–117`) exists — but the banner doesn't wire the retry button to anything visible in the status flow. The `'failed'` branch is effectively *inform the user of a dead end*. The WORKITEMS claim SE.8 ("UI install banner") closed; what shipped is the banner, not the recovery UX.

### 3.5 Entity category choices don't match user intent

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.7. Promoted queue depth, worker count, total slots, total/online/outdated-devices, and the `WorkerOnline` binary sensor out of `DIAGNOSTIC`. Only the version-string sensors (`SelectedEsphomeVersionSensor`, `FleetVersionSensor`) keep `DIAGNOSTIC` — they're genuinely diagnostic. Dropped the shared `_attr_entity_category = DIAGNOSTIC` from `_HubSensorBase` so subclasses opt in explicitly.

`sensor.py:111`, `binary_sensor.py:58` — "queue depth", "online devices", "worker online" are marked `EntityCategory.DIAGNOSTIC`. In HA, DIAGNOSTIC entities are excluded from the default Lovelace picker and default automation triggers. These are *exactly* the things a user would put on a dashboard: "how many compile jobs are queued," "is my worker online." Demote them to no category (the default, primary).

### 3.6 `_discovery.py` is undocumented

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.18. Module docstring added explaining the #62 closure-set fix it implements. (Turned out the docstring was already present — confirmed during the CR.18 audit.)

A 32-line file with no module docstring, no mention in `__init__.py` or `README`. It's copied from Ardumine's PR #57 per the config_flow comment. For an integration that's going into other people's HA installs, "quietly copied from a PR" is not OK. Either inline it into `config_flow.py` or give it a real docstring explaining what it does.

### 3.7 No README inside the integration

**Status:** ✅ FIXED (1.5.0-dev.77) — CR.18. Added `ha-addon/custom_integration/esphome_fleet/README.md` covering: what the subtree is, how it's installed (via `integration_installer` on add-on startup + `push-to-hass-4.sh`'s HA-Core-restart trigger), the `esphome_fleet` vs `distributed_esphome` naming rationale, and the single-entry contract.

`ha-addon/custom_integration/esphome_fleet/` has no `README.md`. A developer cloning only that subtree (the natural way to hand-inspect a custom integration) sees 17 files and has to reverse-engineer intent. Two-paragraph README would fix it.

---

## 4. Testing: the Invariant-Reality Gap

**Status (1.5.0):** 🟡 PARTIAL.
- `page.waitForTimeout()` removals + new **E2E-1** invariant shipped as CR.6 (1.5.0-dev.77). Both callsites the review called out (`cancel-new-device.spec.ts`, `cyd-office-info.spec.ts` prod smoke) were replaced with deterministic waits.
- `pytest-homeassistant-custom-component` rewrite **deferred** to 1.6 IT.2. The contract-test proposal (the `set(response_keys) == expected` shape check) is 1.6 IT.3.
- PY-10 invariant ("test_integration_* must import `pytest_homeassistant_custom_component`") is queued for 1.6 IT.1 alongside the file renames.

CLAUDE.md QG.1 claims this release shipped passing:
- `pytest tests/` — full suite
- E2E (mocked + hass-4)
- `check-invariants.sh`

Those all run in CI. Good. But reading the test bodies tells a different story about *what is actually tested*:

- **Unit test culture is mock-heavy to the point of tautology.** `test_first_coordinator_raises_when_no_entries` (services tests) builds a `SimpleNamespace`, calls the function, asserts it raises. That's a 3-line function being tested with a 4-line test. You're not exercising HA; you're exercising Python's dict-default handling.
- **E2E suite is mostly mock-driven.** `e2e/fixtures.ts` mocks every endpoint. This is fine — it makes tests fast and deterministic — but it means an API contract change between server and UI *will not break an E2E test*. You only find those in `e2e-hass-4/`, which has ~6 specs.
- **No protocol-level contract tests between `types/index.ts` and the server's JSON shapes.** PY-6 guards server↔worker. There's nothing guarding server↔UI and nothing guarding server↔HA integration. The integration does `coordinator.data.get("targets")` on `dict[str, Any]` — when the server changes a field name, the integration silently stops populating entities.
- **Regression tests for bugs #2, #3, #4** (SWR-poll menu twitching) — the Playwright tests exist, but they test that the menu *stays open*, not that it stays open *specifically because of memoization*. Someone could refactor `ActionsCell` to re-render unnecessarily again and the assertion would still pass.
- **The two `page.waitForTimeout()` uses** (`e2e/cancel-new-device.spec.ts:70`, `e2e-hass-4/cyd-office-info.spec.ts:237`) are the early-warning signs of flake. The second one is in the prod smoke suite — the one that gates every deploy. Replace both with `expect.poll` or deterministic waits on DOM state.

**What would actually move the needle:**
1. Wire `pytest-homeassistant-custom-component` and rewrite `test_integration_*.py` to load the integration under a real `hass` fixture. Delete tests that become redundant.
2. Add a contract test that fetches every `/ui/api/*` endpoint's response from a fake server fixture and `assert set(keys) == expected` for the shape the UI+integration consume. Fail on drift.
3. Ban `waitForTimeout` in `check-invariants.sh`.

---

## 5. Security Posture

**Status (1.5.0):** ✅ Largely FIXED — CR.11 + CR.20 + AU.7 + the SECURITY_AUDIT.md refresh.
- §5.1 `require_ha_auth` trade-off documented in `DOCS.md` (CR.20) and the toggle itself flipped to **mandatory** by AU.7 before tag. The "breaks the HA integration until next release" caveat became moot in the same release because AU.7 also wired the Bearer token into the integration.
- §5.2 Supervisor-IP trust assumption on bare-Docker, §5.3 `integration_installer.py` r/w scope, §5.4 SUPERVISOR_TOKEN log-hygiene audit, §5.5 firmware-upload trust — all folded into `SECURITY_AUDIT.md`'s threat-model section and per-finding entries (F-06, F-07, HI.8 installer notes, F-18 firmware audit). CR.11 notes.
- §5.6 F-03 reassessment — `SECURITY_AUDIT.md` now lists F-03 as FIXED (mandatory `require_ha_auth` via AU.7); no longer "half-fix."

For a home-lab LAN tool, the bar is: "don't make the LAN worse than it was." Mostly met. Specifically:

### 5.1 `require_ha_auth` defaults to `false`

That's the right default for backward compatibility (existing installs would break otherwise), but `DOCS.md` should say "if your add-on port is mapped to the LAN, flip this on, and note it breaks the HA integration until v1.4.2" (see §2.5). Security hardening is dishonest if the user doesn't know the trade-off.

### 5.2 Supervisor-IP trust path

`ha_auth.py:138–147` attaches whatever is in `X-Remote-User-Name` / `X-Remote-User-Id` headers when the peer IP matches `HA_SUPERVISOR_IP`. The trust boundary here is: "Supervisor is running on the same host and sets those headers honestly." That's fine for HA OS. For bare Docker deploys, a user running both containers on a shared network without network isolation can spoof the peer IP from inside the Docker bridge. `SECURITY.md` should call this out explicitly.

### 5.3 `integration_installer.py` writes to `/config/custom_components/`

This gives the add-on r/w access to user HA config. Worth an explicit note in `SECURITY.md` under "trust boundary: the add-on can modify `/config/custom_components/esphome_fleet/`." Not a flaw; just not disclosed.

### 5.4 Token handling in `supervisor_discovery.py`

Carries SUPERVISOR_TOKEN in a Bearer header to post discovery. Don't log request/response at INFO — verify the code paths never include this header in a dump under exception handling.

### 5.5 Firmware upload path is worker-auth only

`api.py` new firmware endpoints (FD.1–9). They check the job state + assigned-worker match. Good. But there's no checksum verification of the uploaded firmware against what the server expects — a malicious worker can submit a bogus file. For a home-lab tool that's acceptable (you trust your own workers), but this should be documented as a trust assumption.

### 5.6 `SECURITY_AUDIT.md` is now a mixed signal

The diff shows +134 lines with several "fixed" claims. I didn't re-audit each one end-to-end. A review of the audit should be a separate task — but a spot-check: the audit can't stay marked "fixed" for F-03 while `require_ha_auth` defaults to false *and* the HA integration breaks when it's true. That's a half-fix, which is a specific category and should be tracked as such.

---

## 6. Documentation and Release Engineering

**Status (1.5.0):** ✅ Largely FIXED. CHANGELOG rewritten (CR.1, dev.78), first-boot note added to DOCS (CR.19), `require_ha_auth` trade-off documented (CR.20). GHCR retention policy (§6.5) → CR.28 **WONTFIX** for this release (storage headroom still ample). Pre-release UX sweep (§6.4) institutionalized in `RELEASE_CHECKLIST.md` as a standing step rather than queued as a workitem.

### 6.1 CHANGELOG.md for 1.4.1 is *one paragraph*, and it's about the rename.

This is the single thing I'm most annoyed about.

```
## 1.4.1 (in development)
**Rebrand: now called ESPHome Fleet.** Same add-on, same Docker images ...
```

One paragraph. For a release that ships:
- A new Home Assistant custom integration (services, entities, device registry integration, config flow, WebSocket event stream)
- Lazy ESPHome install (first-boot changes, ~2-3 min install window, UI banner)
- Firmware compile-and-download flow (FD.1–9)
- HA user authentication middleware (AU.1–6)
- SBOM attestations + SHA-pinned Actions (SC.1, SC.2)
- Server-side real-time WebSocket event stream
- Drops bundled ESPHome from the server image (behaviour change on first boot!)
- A full UI quality sprint (QS.1–27)
- Dozens of bug fixes

CLAUDE.md's own guidance says:
> **90% of the entry should cover things users see and experience** ... **Never say "no new features" when there are user-visible features — scan the WORKITEMS bug list for UI/UX work.**

This changelog *does exactly that failure mode*. A user upgrading from 1.4.0 will see "Rebrand" and think "cosmetic patch." Then they restart the add-on and it hangs for 3 minutes installing ESPHome. That's a release-notes bug waiting to page someone. Rewrite before release.

### 6.2 `DOCS.md` needs a companion entry for first-boot behaviour

SE.1–10 changed the add-on to lazy-install ESPHome at first boot. `DOCS.md` should have a "First boot takes 1-3 minutes — don't panic" note. If it's there already (I saw a diff, didn't verify thoroughly), good; if not, add it.

### 6.3 Bug numbering is global and monotonic — but #s 60/61/62/63 show up in commits, not in the changelog

CLAUDE.md says "Bug numbers are global and monotonic across releases — never reset." Good. But user-facing release notes still need to summarize, not list 50 issue numbers. The risk right now is the opposite — commit logs are dense with `fix(#60, #61)` references and the changelog has *zero*. Pick one coherent abstraction per audience.

### 6.4 `WORKITEMS-1.4.1.md` claims credibility is uneven

With 473 lines added, there's a lot of "[x] done, dev.N" checkboxes. I didn't audit every one against the code, but the pattern where SE.8 is marked done while the retry UX is half-wired (§3.4) suggests someone checked "banner exists" and moved on. A pre-release pass of "open the UI, click every new button, confirm each claimed item actually works end-to-end" is worth doing before tagging.

### 6.5 `-dev.N` bump-every-turn philosophy

It's a personal workflow choice, fine for a single-developer project, but note that every dev.N push triggers GHCR publish workflows. Over 147 commits × N pushes you've generated a LOT of container images in GHCR. `publish-client.yml` / `publish-server.yml` should have a retention policy or a "publish only on tags + `main`" gate to keep that bounded. Otherwise you'll hit GHCR storage limits at some point and be surprised.

---

## 7. Architectural / Design Concerns

**Status (1.5.0):** ✅ Addressed via docs.
- §7.1 event_bus loop assumption + SLA docs — CR.22. `event_bus.broadcast` docstring updated to "must be called on the aiohttp loop"; two-consumer SLA table added (UI ~1s via SWR; integration up to 30s via coordinator poll). `coordinator._last_job_states` pruning verified via existing `test_disappeared_jobs_removed_from_tracker`.
- §7.2 naming-split rationale in CONTRIBUTING.md — CR.27 **WONTFIX** (not a contributor-facing project today; CLAUDE.md carries the rationale for internal reference).
- §7.3 non-goal: multi-instance — CR.2 made it explicit in `manifest.json` (`single_config_entry: true`).
- §7.4 `app_config.py` precedence — CR.21. Module docstring spells out `env var > /data/options.json > defaults`.

### 7.1 Three parallel async-push paths and no unifying model

1. The server's in-process `event_bus.py` (queue-per-subscriber, broadcast on mutation).
2. A WebSocket endpoint at `/ui/api/ws/events` that forwards from the event bus.
3. The HA integration's `EventStreamClient` reconnecting to that WebSocket and kicking coordinator refreshes.

Each piece is fine individually. But:
- `event_bus.broadcast` is callable from sync code (comment: "called from sync or async code — never awaits"). That's true for `put_nowait`, but only if the queue belongs to the same event loop. The code works because everything runs in aiohttp's loop. If anyone later moves mutation into a thread pool, `put_nowait` raises. Worth a one-line "must be called on the aiohttp loop" docstring rather than "from sync or async."
- The HA integration drops bounded subscriber state (job state dict, `_last_job_states`) purely via "still in current queue snapshot" pruning. Under a long-running queue with retained terminal jobs, that dict grows. There's a prune at `coordinator.py:130`; confirm it runs on every tick.
- There's no message-loss detection. The comment "missed event just adds up to 30 s of latency" is OK for the HA integration (coordinator poll fills the gap). It's *not* OK for the UI, which has SWR at 1 Hz — so the UI recovers in 1 s. Document the two SLAs separately.

### 7.2 The naming split is still painful

CLAUDE.md justifies "user-facing = ESPHome Fleet, code = distributed_esphome" as a non-migration. That's defensible but the cost shows up in the HA integration, which uses `esphome_fleet` as the domain, so inside `ha-addon/custom_integration/esphome_fleet/` the whole subtree is on the new name, while everything around it is on the old. A newcomer reading this repo has to hold two mental models. Either write the rationale in a `CONTRIBUTING.md` ("if you're wondering why half the names disagree, here's why") or push harder on making them agree. Don't leave it implicit.

### 7.3 `_first_coordinator` pattern inside the integration is a symptom

See §2.4. More broadly: the integration assumes *one* add-on instance. The add-on assumes *one* HA instance. Both are fine today, but every new surface that gets added (services, `supervisor_discovery.py`, mDNS) silently hardcodes the assumption. Put a one-line "non-goals: multi-instance support" in the integration's docstring so nobody files a bug asking for it and gets a surprise "that's intentional" response.

### 7.4 `app_config.py` is new and tiny

18 lines. Fine. But now server config lives in three places: `/data/options.json`, env vars, and `app_config.py`. The precedence and merging should be documented once, in one place (ideally `app_config.py` itself).

---

## 8. Performance / Idle Efficiency (CLAUDE.md performance section)

**Status (1.5.0):** ✅ Low-priority items closed.
- Parallel coordinator GETs (the one quantifiable win) — CR.13.
- Diff-skip device-registry listener — CR.14.
- Firmware retention audit confirmed no leak path — CR.25.
- SWR visibility-hidden backoff, bigger fleet profiling — not done; not urgent per the original review's own framing.

CLAUDE.md's framing is "idle should be cheap." A brief audit of new idle costs:

- **Server background loops:** timeout checker, HA entity poller, PyPI refresher, now also `mdns_advertiser` and `supervisor_discovery`. Each one sleeps on a sensible interval; nothing here is a tight loop. OK.
- **Integration coordinator:** 6 sequential GETs every 30 s (see §2.8). Not a problem; suboptimal.
- **Integration device-registry churn every 30 s:** (§2.7). Same.
- **UI SWR polls at 1 Hz:** Documented, fine on a LAN, might look noisy on a mobile tether — `CLAUDE.md` acknowledges this. Consider a coarse visibility-hidden backoff (if `document.visibilityState === 'hidden'`, slow polls to 10 s).
- **Firmware storage TTL:** `firmware_storage.py` new; I did not fully audit retention. If firmware files aren't garbage-collected, disk fills up over time. Confirm.
- **WS event bus on idle:** zero subscribers short-circuits. Good.

No critical idle-cost regressions found. Plenty of 10-30% wins available if anyone cares (parallel GETs, diff-skip listener, visibility backoff). None required.

---

## 9. Developer-Experience / Repo Hygiene

**Status (1.5.0):** 🟡 PARTIAL.
- §9.1 `CODE_OF_CONDUCT.md` / `CONTRIBUTING.md` — CR.27 **WONTFIX** for this release. Home-lab single-dev project; CLAUDE.md already encodes the contribution patterns for any drive-by. Revisit if outside contributions start arriving.
- §9.2 Issue template enrichment — not queued as a formal workitem; low-priority.
- §9.3 New invariants — CR.23. **UI-6** (ban `if (!r.ok) return []` pattern in `api/`) shipped + caught a straggler. **E2E-1** (ban `page.waitForTimeout`) shipped. **HA-1** (ban `[class*="monaco"]` CSS-substring Playwright selectors) deferred — current usage is Monaco's dynamic classes and a clean fix needs `data-*` test hooks. **PY-10** (test_integration_* imports `pytest_homeassistant_custom_component`) queued for 1.6 IT.1.
- §9.4 Verify lockfile is Docker-container-sourced — CR.24, done; `grep -E "pyobjc|appnope"` returns empty on both lockfiles.

### 9.1 LICENSE exists. `CODE_OF_CONDUCT.md` and `CONTRIBUTING.md` do not.

For an open-source project inviting PRs, both are table stakes in 2026. `CONTRIBUTING.md` should crib heavily from CLAUDE.md (trim the AI-specific parts) so external contributors learn the invariants before they submit.

### 9.2 Issue template changed slightly (+2 lines)

Not audited. For a project that numbers bugs globally, the template should prompt for: HA version, add-on version, worker version, and whether the user flipped `require_ha_auth`. Otherwise the next AU-related bug report will be missing half the context.

### 9.3 `check-invariants.sh` is 78 lines larger

Good. Consider adding:
- **UI-6**: no `return [] on !r.ok` patterns in `api/client.ts` (catches §2.9).
- **E2E-1**: no `waitForTimeout` in `e2e/*.spec.ts`.
- **HA-1**: no `page.locator('[class*="monaco"]')` in specs (the `[class*="..."]` selector is a flake surface).
- **PY-10**: tests in `test_integration_*.py` must import `pytest_homeassistant_custom_component` (or be renamed to `test_integration_logic_*.py` to reflect what they are).

### 9.4 800-line `requirements.lock` churn

The diff shows `requirements.lock | 800 +-------------------`. That suggests a wholesale regeneration, which PY-9 exists to make safe. If the regeneration was done via `scripts/refresh-deps.sh` (linux/amd64 container), good. If someone ran `pip-compile` locally on macOS *once* during the cycle, PY-9 caught it (bug #56 in commit `eded402`). Confirm the final lock is the one from the container.

---

## 10. What We *Didn't* Find (Claims That Didn't Hold Up on Verification)

A grumpy review still needs to be honest. Several claims raised in the initial automated sweep did not verify:

- **"`__init__.py:147` device-registry set intersection is broken because of type mismatch."** False. `device.identifiers` and `live_identifiers` are both `set[tuple[str, str]]`. Set intersection of tuples of hashable primitives is exactly what it looks like. The code is correct.
- **"`main.py:351` blocks the event loop by calling `open('/etc/timezone').read()` inside an async context."** False. Line 351 is a comment inside an aiohttp template-API handler. No blocking `open()` there.
- **"Dockerfile layer ordering invalidates pip cache on every source change."** Plausible on a quick glance but not audited. I'm leaving this *unconfirmed* rather than assert it; look yourself before acting.
- **"`event_bus` leaks subscribers on crashed WebSocket sessions."** Unverified. `subscribe`/`unsubscribe` look symmetric; the WS endpoint should have a `finally: unsubscribe(q)` and I didn't read that handler.
- **"The WORKITEMS claim of 'E2E backfill' is spotty."** Partially confirmed (see §4), but without a full test-by-test audit I'm not going to claim which specific items are under-covered.

Call-outs here exist so that later reviewers don't cite this document for things this document did not actually verify.

---

## 11. Punch List (if you shipped tomorrow, fix at least these)

**Status (1.5.0):** 7 of 8 shipped; item 8 deferred to 1.6.

In priority order. Not one of these is a "full rewrite"; all are under an hour each.

1. ~~**Fix the changelog.**~~ ✅ CR.1, 1.5.0-dev.78. Full release-scope summary grouped by workstream (rebrand / HA integration / firmware download / auth / ESPHome unbundling / supply chain / UI quality + "Under the hood" tail).
2. ~~**Decide multi-instance.**~~ ✅ CR.2, 1.5.0-dev.77. `"single_config_entry": true` in manifest.json.
3. ~~**Wire integration auth or document the hole.**~~ ✅ CR.3, 1.5.0-dev.77 (subsumed by AU.7). Bearer token wired; add-on's shared worker token is what `/ui/api/*` accepts under the new middleware path. `CONF_TOKEN` is real. Direct-port auth flipped to **mandatory** in 1.5.
4. ~~**Drop the dead write in `job_queue.py:604`.**~~ ✅ CR.4, 1.5.0-dev.77.
5. ~~**Fix the three `api/client.ts` error-swallowers.**~~ ✅ CR.5, 1.5.0-dev.77. Plus new **UI-6** invariant to prevent the pattern returning.
6. ~~**Replace both `page.waitForTimeout` calls in E2E.**~~ ✅ CR.6, 1.5.0-dev.77. Plus new **E2E-1** invariant.
7. ~~**Drop DIAGNOSTIC category on queue-depth/online-devices sensors.**~~ ✅ CR.7, 1.5.0-dev.77.
8. 🟡 **Document HA-integration test reality.** Deferred — the 1.5 choice was to accept the mock-heavy state and queue the proper rewrite as IT.1 (rename) + IT.2 (pytest-homeassistant-custom-component) + IT.3 (contract tests) in `WORKITEMS-1.6.md`. CR.26 placeholder in 1.5 points at the 1.6 items.

---

## 12. Closing

This is a *good* release that's being *undersold and under-verified*. The work inside it is solid — the HA integration is ambitious, the UI refactor is a real cleanup, the security workstream is more disciplined than most OSS projects I see. But it's ready-to-ship-with-asterisks, not ready-to-ship.

The single biggest lever is cultural: *test what a user actually does, not what the code happens to expose as functions*. The mock-heavy test suite is giving you false confidence. Close that gap and the next release ships with fewer of these "half-wired" gaps.

And rewrite the changelog before you merge. Users deserve to know what they're getting.

— a grumpy reviewer
