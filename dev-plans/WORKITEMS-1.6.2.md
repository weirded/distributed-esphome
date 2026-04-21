# Work Items — 1.6.2

Theme: **Honest Gold.** 1.6.1 shipped a "silver" claim that hassfest never validated and an AppArmor profile that confined nothing; the PR #80 review flagged four user-visible bugs that landed anyway; the TEST-AUDIT-1.6.1 top-five blind spots stayed open. 1.6.2 closes all of that *and* walks the remaining Bronze+Silver+Gold rules to `done` or honestly-justified `exempt` so the `quality_scale: gold` claim in `manifest.json` is one the code actually backs.

Read first, in order: `dev-plans/TEST-AUDIT-1.6.1.md` (the authoritative blind-spot list), `ha-addon/custom_integration/esphome_fleet/quality_scale.yaml` (current per-rule status — some of it is stale), `dev-plans/archive/WORKITEMS-1.6.1.md` §SS, §QS, §PR (where the deferrals originated).

Scope rule: **no new user-visible capabilities this release.** Every workitem either (a) closes a TEST-AUDIT blind spot, (b) fixes a shipped-but-broken path, (c) lifts a quality-scale rule from `todo`/missing to `done`/`exempt`, or (d) rewrites a user-facing claim to match reality. Feature requests that land mid-cycle go to `WORKITEMS-1.7.md` or `WORKITEMS-future.md`. Gold-equivalence or bust — there is no partial credit here.

Definition of "Gold" for a custom integration: hassfest never runs on out-of-tree code in prod, so "official" Gold isn't available. **Gold-equivalent** means: (i) every rule in Bronze+Silver+Gold of `script/hassfest/quality_scale.py`'s `ALL_RULES` is `done` or `exempt` with a reason in our `quality_scale.yaml`; (ii) a local `python3 -m script.hassfest --action quality_scale` against our integration passes clean when the manifest claims `gold`; (iii) CI runs that same validator on every PR (CI.4) so the claim can't silently rot. That's the bar this release targets.

---

## TP — Truth-in-claims (undo the pretend)

1.6.1 publishes three claims the code doesn't fully back: AppArmor-confined, silver-tier integration, all-tests-honest. This section pulls reality up to the claim where cheap, rewrites the claim to match reality where not, and leaves nothing quietly asymmetric.

- [ ] **TP.1 Rewrite SECURITY.md's SS.1 paragraph.** Current wording reads as a hardening improvement; the profile is attached-but-permissive (`file, capability, network, signal, dbus, unix, mount, pivot_root, ptrace,` all unqualified = functionally unconfined). Lift the honest caveat from `WORKITEMS-1.6.1.md` SS.1 ("permissive-but-attached buys the security-star credit today; tightening is tracked as future work") up into SECURITY.md proper. Don't ship a second release claiming SS.1 confined anything.

- [ ] **TP.2 Actually tighten the AppArmor profile (SS.1b).** Minimum viable narrow rules that don't break PlatformIO/penv/git/pip: `deny /etc/shadow* rw,`, `deny /run/secrets/** rw,`, `deny /proc/*/mem rw,`, `deny @{PROC}/sys/kernel/** w,`. Drop unqualified `ptrace,` (replace with `deny ptrace,` or remove — nothing in our stack ptraces anything). Verify with hass-4 smoke 17/17 green. Unblocks TP.1 from reading as "SECURITY.md now admits SS.1 is a no-op" → "SECURITY.md describes the first-pass confinement that landed." Prereq: CI.2 lands first so narrowing attempts don't burn deploy cycles to find breakage.

- [ ] **TP.3 Refresh and complete `quality_scale.yaml`; flip `manifest.quality_scale` to `gold` only when it's honest.** The file exists (371 lines) but has rot: (a) the header comment still says "manifest.json's `quality_scale: silver`" — the manifest now says `bronze`; fix the header. (b) `runtime-data` says "migration … is planned when the HA minimum is bumped past 2024.11" — the HA minimum *is* past 2024.11 now (today is 2026-04); the deferral expired. Either migrate (see QS.G6) and mark `done`, or restate the real reason it's deferred. (c) Every Bronze+Silver+Gold rule from `script/hassfest/quality_scale.py`'s `ALL_RULES` must appear with `done`/`exempt` — any rule currently `todo` must be closed by a QS.* workitem below, or re-scoped to a future release (and the manifest tier drops accordingly). (d) After every QS.* item lands, run `python3 -m script.hassfest --action quality_scale` locally; expect zero errors at tier `gold`. Only then edit `manifest.json` from `quality_scale: bronze` → `quality_scale: gold`. Ground rule: if even one Gold rule stays `todo` at ship-time, manifest stays at `silver` or `bronze` — we do not ship a claim hassfest doesn't back.

- [ ] **TP.4 CHANGELOG.md retrospective entry at the top of 1.6.2.** Short "Corrections to 1.6.1" section opening the release notes. Users upgrading from 1.6.1 need to know: (a) the AppArmor profile they thought confined the add-on didn't — now it partly does; (b) the "silver" integration-quality claim from 1.6.1 was unenforced — 1.6.2 either raises it to Gold with hassfest proof or honestly retreats to a lower tier; (c) the five TR.* items closed paths that shipped broken. No marketing copy — user-centric plain language.

*(Former TP.4 "PARALLEL_UPDATES = 0 on every entity platform" is dropped — it's already landed in all five platforms: `sensor.py:49`, `binary_sensor.py:33`, `button.py:32`, `number.py:32`, `update.py:34`. Kept as a confirmed-done entry under QS.S below.)*

---

## TR — Real-bug remedies (flagged in PR #80 review, merged anyway)

Each of these was explicitly called out before merge. Fixing them here rather than pretending they don't exist.

- [ ] **TR.1 Fix bug #3's disconnect filter.** `ha-addon/server/device_poller.py::_AioesphomeapiDisconnectFilter` mutates `record.levelno` and returns `True`. Per Copilot's review (PR #80 comment), `Logger.callHandlers` already chose the ERROR handler before the filter ran — so the record still ships at ERROR, just with a misleading `DEBUG` label. Fix: return `False` to drop the matching record (simplest) or re-emit on a DEBUG-level logger under a different name and return `False` on the original (keeps the information). Regression test in `tests/test_device_poller.py` using pytest's `caplog` fixture: assert the "disconnect request failed" record does not surface at `ERROR`-level capture.

- [ ] **TR.2 Fix `mdns_advertiser.py` malformed-URL + dead conditional.** `ha-addon/server/mdns_advertiser.py:62` → `base_url = "http://:8765"` when `_primary_ipv4()` returns None. Either skip registration entirely on the None branch (advertising no-IP serves no one) or omit `base_url` from properties. Line 83's `socket.gethostname() if socket.gethostname() else None` is dead code — `gethostname()` always returns a non-empty string; guard against `"localhost"` specifically (which is what actually breaks mDNS resolution). Both covered by HT.5's new test file.

- [ ] **TR.3 Fix the three `async_step_reconfigure` bugs.** `ha-addon/custom_integration/esphome_fleet/config_flow.py`:
  1. Drop the `async_update_reload_and_abort` fallback branch (HA <2024.11 doesn't invoke this step, so the branch is dead code) **or** bump manifest's `homeassistant` minimum from `2024.1.0` to `2024.11` so the comment matches reality. Coordinates with QS.G10 (declare a real minimum once).
  2. `self.context["entry_id"]` → `self.context.get("entry_id", "")` + early abort with `reason="reconfigure_unknown_entry"` if missing.
  3. Replace `assert self._reconfigure_entry is not None` (raises AssertionError) with `return self.async_abort(reason="reconfigure_unknown_entry")`; add the abort key to `strings.json` + `translations/en.json`.

  Regression test via HT.7 (real-flow test using the HA fixture).

- [ ] **TR.4 Connect Worker modal bash branch — add `--network host`.** `ha-addon/ui/src/components/ConnectWorkerModal.tsx::buildDockerCmd`'s bash branch is missing `--network host` that the compose branch has. Any user copy-pasting the output onto a LAN with ESP devices outside docker's default bridge gets a worker that can't OTA. Add the flag (same place as `--restart`). Regression guard via HT.6 snapshot test.

- [ ] **TR.5 Dockerfile Debian-assertion guard.** `ha-addon/Dockerfile` currently detects Supervisor's silent build.yaml `@sha256:` regex rejection only because the downstream `apt-get install` fails on the Alpine fallback. One-line guard before the apt-get block:
  ```dockerfile
  RUN . /etc/os-release && [ "$ID" = "debian" ] || \
      (echo "ERROR: unexpected base '$ID' — Supervisor probably rejected build.yaml; aborting" >&2; exit 1)
  ```
  Turns a silent misbuild into a grep-able layer-0 failure. Documented in `ha-addon/build.yaml`'s comment; still worth the explicit guard against Dockerfile drift.

- [ ] **TR.6 Fix the reauth assert sibling to TR.3.** `ha-addon/custom_integration/esphome_fleet/config_flow.py:124` has `assert self._reauth_entry is not None` — exact same bug shape as TR.3.3 but in the reauth path, not reconfigure. A malformed flow dispatch from HA (missing context, entry deleted between reauth-trigger and reauth-confirm) throws `AssertionError` instead of aborting cleanly. Replace with `return self.async_abort(reason="reauth_unknown_entry")`; add the abort key to `strings.json` + `translations/en.json`. Covered by HT.11 (real-flow reauth test).

---

## QS — Quality Scale: path to honest Gold

Every rule below either (i) still reads `todo` in `quality_scale.yaml`, (ii) reads `done` but the code tells a different story, or (iii) is missing from the file entirely. Lifting each to honest `done` or `exempt` is what makes TP.3's tier-flip safe. Rule slugs match `script/hassfest/quality_scale.py`'s `ALL_RULES`.

### QS.B — Bronze (only `brands` outstanding)

- [ ] **QS.B1 Submit brand assets to `home-assistant/brands`.** Artwork is staged under `docs/brands-submission/` (per `quality_scale.yaml:35–40`); the PR to `home-assistant/brands` hasn't been opened. Prepare the submission (matching that repo's README: `icon.png` 256×256, `icon@2x.png` 512×512, `logo.png`, `logo@2x.png` — all under `custom_integrations/esphome_fleet/`), open the PR, link it back here. This rule can ship as `done` in our file once the brands PR is merged; until then, leave it `todo` with the PR URL in the comment so it's visible why Gold's on hold.

### QS.S — Silver (confirmed-done + the one open item)

- [x] **QS.S-confirm `PARALLEL_UPDATES` already landed on every entity platform.** Verified: `sensor.py:49`, `binary_sensor.py:33`, `button.py:32`, `number.py:32`, `update.py:34` — all `PARALLEL_UPDATES = 0` with the coordinator-throttle rationale in the comment. Former TP.4 is satisfied. Nothing to do; mention in release notes and leave the `quality_scale.yaml:parallel-updates` entry as `done`.
- [ ] **QS.S1 Silver `test-coverage` → Gold-grade coverage.** Silver's bar is ≥95% real line-coverage (not mocked). We have ~1800 LOC of `SimpleNamespace`-mocked `_logic.py` tests and a `test_integration_setup.py` with `@pytest.mark.skip` on every real-hass case. HT.1 unblocks this by wiring `async_mock_integration`; HT.7 + HT.11 extend it with real-flow reconfigure + reauth coverage; HT.12 adds the coverage measurement. When those three land, re-run `pytest --cov=ha-addon.custom_integration.esphome_fleet`, confirm ≥95%, flip `test-coverage` to `done` in `quality_scale.yaml`. Until then it stays `todo` and Gold doesn't ship.

### QS.G — Gold tier (the main lift)

- [ ] **QS.G1 `docs-data-update` — Integration DOCS section.** Add a "How data updates" subsection to `ha-addon/DOCS.md` → Integration. Explain: coordinator polls the add-on's `/ui/api/*` endpoints every 30s (`update_interval=timedelta(seconds=30)` in `coordinator.py`); a push WebSocket supplements the poll for real-time event signals; the user can force an immediate refresh via the integration card's *Reload* button. Flip the `quality_scale.yaml:docs-data-update` entry to `done` when the section is live.

- [ ] **QS.G2 `docs-examples` — formal Examples section.** `DOCS.md` → Integration currently sketches automations informally. Restructure into a `## Examples` section with at least three concrete scenarios, each as a copy-pasteable YAML snippet that references our entities: (i) fire a notification when any target's Update entity reports a pending version, (ii) trigger the `esphome_fleet.compile` service on schedule via HA Scheduler, (iii) route a worker-offline binary-sensor transition to a dashboard warning card. Link at least one to a published HA blueprint if we author one; otherwise note that blueprint contributions are welcome.

- [ ] **QS.G3 `docs-known-limitations` — single dedicated section.** Consolidate what's scattered across `DOCS.md` today into a `## Known limitations` section: (a) HA Core restart required after integration-code upgrade (Python module caching); (b) Supervisor `@sha256:` digest pinning blocked on upstream Supervisor schema; (c) AppArmor profile is first-pass confinement only (narrow denies on secrets + `/proc/*/mem` + `/sys/kernel` writes, unrestricted file/network elsewhere) — link to SECURITY.md for the threat model; (d) worker-offline detection uses a 30s heartbeat window; transient blips of ~45s register as offline-then-online; (e) the factory-vs-OTA firmware-variant distinction isn't surfaced in the integration's Update entity — users pick in the Web UI.

- [ ] **QS.G4 `docs-troubleshooting` — single dedicated section.** Consolidate into `## Troubleshooting` with the symptom→cause→fix shape the gold rule wants: "Integration card says *Reconfigure*" → token rotated or URL changed → run Reconfigure flow; "Entities stuck at *unavailable*" → add-on URL mismatch or add-on stopped → check Supervisor logs + URL; "Zeroconf discovery never fires on a fresh HA" → mDNS reflector not enabled on the router, add-on URL must be entered manually; "Reauth flow dead-ends" → expired refresh-token path, delete + re-add entry (rare; TR.6 closes a code-path contributor). Four to six items is enough; refresh as real support threads surface.

- [ ] **QS.G5 `entity-translations` — move every `_attr_name` to `_attr_translation_key`.** Current state: zero entities use `_attr_translation_key` (verified by `grep -c _attr_translation_key ha-addon/custom_integration/esphome_fleet/{sensor,binary_sensor,button,number,update}.py` → all 0). Every entity ships an English-only name via `_attr_name = "…"`. Work:
  1. Enumerate every distinct entity shape across the five platforms — target scheduled-upgrade sensor, worker online binary_sensor, worker clean-cache button, worker parallel-slots number, target update entity, etc. Give each a short snake-case translation key.
  2. Replace `_attr_name = "Queue depth"` → `_attr_translation_key = "queue_depth"` (and drop `_attr_name` — HA composes from `entity.<platform>.queue_depth.name` in `strings.json`).
  3. Populate `strings.json` → `entity.sensor.queue_depth.name`, etc., for every key. Mirror to `translations/en.json`.
  4. For entities whose `device_class` already provides a translated name (the built-in rule exemption — `binary_sensor`/`number`/`sensor`/`update` with a device_class set), verify the name shows up correctly without a translation_key and note the exemption in the entity's code comment.
  5. Verify in the HA UI: entity names render identically to today; *Customize* dialog shows the English names as defaults and exposes them for localization.
  6. Flip `entity-translations` to `done` in `quality_scale.yaml`.

- [ ] **QS.G6 `runtime-data` — migrate from `hass.data[DOMAIN][entry.entry_id]` to `entry.runtime_data`.** The `quality_scale.yaml:109–115` comment hedges "migration planned when HA minimum is bumped past 2024.11" — we're well past (today is 2026-04). The hedge expired; either migrate or state the real reason. Concretely:
  1. Replace `hass.data[DOMAIN][entry.entry_id] = coordinator` in `__init__.py` with `entry.runtime_data = coordinator`.
  2. Update every platform read: `sensor.py:56`, `binary_sensor.py`, `button.py`, `number.py`, `update.py` — replace `hass.data[DOMAIN][entry.entry_id]` with `entry.runtime_data`.
  3. Introduce a typed `ConfigEntry` alias: `type EsphomeFleetConfigEntry = ConfigEntry[EsphomeFleetCoordinator]` in `const.py` or a new `types.py`; annotate `async_setup_entry` / `async_unload_entry` / platform setups / diagnostics / config_flow `async_get_options_flow` to use it. (This also pre-pays for Platinum's `strict-typing` rule, whose `runtime-data` validator adds typed-alias checks when `strict-typing` is `done`.)
  4. Update `diagnostics.py` to read via `entry.runtime_data`.
  5. Audit `hass.data` cleanup in `async_unload_entry`: since there's nothing there to clean up post-migration, remove the pop.
  6. Run full test + hass-4 smoke; flip `runtime-data` to `done` in `quality_scale.yaml`.

- [ ] **QS.G7 `stale-devices` — add `async_remove_config_entry_device` for user-initiated deletion.** Current state: stale-devices is *active removal* via `registry.async_remove_device` in `__init__.py:226` when the coordinator's target/worker snapshot drops an entry. That closes the *automatic* side of the rule, but HA's device page also offers a per-device **Delete** button whose enablement requires the integration to define `async def async_remove_config_entry_device(hass, config_entry, device_entry) -> bool` at the top level of `__init__.py`. Without it, the Delete button is greyed-out and users can't clear stale devices manually (e.g. a worker that's been physically decommissioned but the server still remembers). Implement it: return `True` when the device's identifier no longer appears in the coordinator snapshot; `False` otherwise (still active — refuse). Covered by a unit test in `tests/test_integration_remove_device_logic.py`. Update the `quality_scale.yaml:stale-devices` comment to name both the active-removal and user-removal paths.

- [ ] **QS.G8 `repair-issues` — audit actionable conditions, add custom issues where warranted.** `quality_scale.yaml:repair-issues` says `done` because `ConfigEntryAuthFailed` auto-creates a repair. That's one condition; Gold wants us to surface every user-actionable condition via `ir.async_create_issue`. Audit for these:
  - Worker offline >1h despite being configured → fixable by starting/restarting the worker or removing the config. Severity WARNING.
  - Firmware-storage budget full → fixable by clearing old binaries or raising the budget. Severity WARNING. Link to the Queue-History dialog's Download tab.
  - ESPHome lazy-install failed (PyPI unreachable, no disk space) → surface the install error as a repair issue with the stderr blob. Severity ERROR.
  - Scheduled upgrade failed three times in a row for the same target → Severity WARNING; fix hint: check device reachability or pinned-version mismatch.

  For each, define the issue in `strings.json` → `issues.<issue_id>` with `title` + `description`, create on detection, clear with `ir.async_delete_issue` when the condition resolves. Non-actionable noise stays in logs — don't pollute Repairs with transient events. Update the `quality_scale.yaml:repair-issues` comment to enumerate the new issues.

- [ ] **QS.G9 `entity-disabled-by-default` — re-audit the "exempt — all useful" claim.** `quality_scale.yaml:309–313` currently reads `exempt`. That may or may not be right; the rule wants niche or high-cardinality entities disabled by default. Audit every entity and decide — `_attr_entity_registry_enabled_default = False` on anything whose value (i) changes more often than every ~5 minutes on a steady-state fleet, or (ii) is only useful for debugging. Candidates: per-worker active-jobs count (high-churn), the `scheduled_once` sensor (rarely consulted). If after the audit no entity qualifies, keep `exempt` but replace the comment with the audit rationale ("audited every entity at <date>; none qualify as niche/noisy"). If any qualify, mark `done` and list them.

- [ ] **QS.G10 Declare `manifest.json.homeassistant` minimum.** Currently the key is absent; HA treats that as "any version." Set `"homeassistant": "2024.11.0"` (or the real minimum we've validated against — coordinate with TR.3.1 which needs to pick a number). This clears the ambiguity in the `async_step_reconfigure` dead-branch and locks the `entry.runtime_data` / typed-ConfigEntry requirements at QS.G6. Document the chosen minimum in `DOCS.md` under Installation.

### QS.P — Platinum lookahead (not claimed this release)

- [ ] **QS.P1 Scope `strict-typing` for a future release.** Run `mypy --strict` against `ha-addon/custom_integration/esphome_fleet/` and count the diagnostics; triage into (a) genuinely fixable right here (add an annotation), (b) fixable after QS.G6 lands (typed ConfigEntry alias unlocks half of them), (c) bounded by `Any` on coordinator dict reads — needs a `TypedDict` for the server's response shape (which is pydantic-shaped on the server side; we could import and re-use the `protocol.py` models). **No code changes this release** — but produce a short `dev-plans/STRICT-TYPING-PLAN.md` that enumerates counts, categories, and a 1.7 or 1.8 landing plan. Platinum also needs every dep in `manifest.json.requirements` to ship `py.typed` or a `types-*` stub; since our requirements list is empty, that half is free. Update the `quality_scale.yaml:strict-typing` comment with the counts from the audit.

- [x] **QS.P-confirm `async-dependency` + `inject-websession` already landed.** Verified: only external I/O is `aiohttp` against the add-on's HTTP API; `coordinator.py` uses `async_get_clientsession(hass)` not a fresh `aiohttp.ClientSession`. Nothing to do. If we ever claim Platinum, these two are free.

---

## HT — Honest testing (close TEST-AUDIT-1.6.1's top blind spots)

- [x] **HT.1** *(1.6.2-dev.3)* **Unskip IT.2 — real-hass lifecycle tests.** Landed in `tests/test_integration_setup.py` — three tests under a real `hass` fixture: happy-path setup+unload, `setup → unload → setup` reload cycle (CR.12 class regression guard), and first-poll-failure → `ConfigEntryState.SETUP_RETRY` → reload → `LOADED` recovery path. Wiring: symlink the integration into each test's `hass.config.config_dir/custom_components/` (the `hass` fixture's per-test tmpdir — the old repo-root symlink was in the wrong place), pop `DATA_CUSTOM_COMPONENTS` so HA re-scans, patch `EsphomeFleetCoordinator._async_update_data` + `EventStreamClient._run` to silence HTTP + WebSocket attempts during setup, and session-warm pycares' singleton shutdown thread so `verify_cleanup`'s thread-leak check doesn't trip on first-test lazy-start. PY-10 invariant becomes load-bearing instead of cosmetic; prereq for QS.S1 (≥95% coverage) and SD.2 Gold gate — both still outstanding.

- [ ] **HT.2 Reseed-consumer invariant (`check-invariants.sh` new rule).** The class of bug behind **#11 (1.6.1)** (encryption-key race on fresh boot) and **#18 (1.6.1)** (static-IP OTA regression) is the same: `_resolve_esphome_config` returns `None` during the ESPHome lazy-install window, leaving `_encryption_keys` / `_address_overrides` / `_name_map` unseeded. Fix landed as `main.reseed_device_poller_from_config`. New invariant: grep for every module-level read of those three dicts; for each hit, require the same module references `reseed_device_poller_from_config` OR is `main.py` itself. Fails CI if a future consumer lands without the reseed wire-up. **This is the durable close on the bug class — don't skip it in favour of yet another narrow test.**

- [ ] **HT.3 Static-IP fixture suite (the deferred-in-#18 trap).** `tests/fixtures/esphome_configs/` gains: `wifi_use_address.yaml`, `wifi_static_ip.yaml`, `ethernet_static_ip.yaml`, `openthread_use_address.yaml`, `wifi_static_ip_via_substitution.yaml` (`static_ip: ${ip}` + substitutions block), `wifi_static_ip_via_secret.yaml` (`static_ip: !secret my_ip`), `packages_with_network.yaml` (address comes from an included package). New `tests/test_ota_address_resolution.py` parametrises over every fixture and asserts `(address, source)` matches what ESPHome's own `esphome.core.CORE.address` produces against the same YAML — **ESPHome as the oracle, not hand-coded expected values**, so the test tracks upstream behaviour automatically when ESPHome's resolver shifts.

- [ ] **HT.4 `e2e-hass-4/static-ip-ota.spec.ts` — prod regression guard.** Add a target with `wifi.manual_ip.static_ip: 192.0.2.1` (TEST-NET-1, unroutable by design). Trigger compile. Assert the resulting job record has `ota_address == "192.0.2.1"` (not `shopaccesscontrol.local` or similar). Compile fails at the OTA step because the IP is unroutable — intentional; the assertion is on job metadata, not successful upload. The static-IP bug has shipped twice (radiowave911 in 1.4.x and again in 1.6). A third ship is unacceptable; this guard forces the failure mode onto CI instead of into the next support thread.

- [ ] **HT.5 `tests/test_mdns_advertiser.py` — dedicated coverage.** Module shipped in 1.6.1 with zero unit tests. Cover: happy-path register/unregister against a mocked `AsyncZeroconf`; `_primary_ipv4()` returning `None` (post-TR.2 fix: asserts either skip or omitted `base_url`); `stop()` before `start()` doesn't crash; `start()` twice is idempotent (or raises cleanly). Assert `socket.gethostname() == "localhost"` branch uses the fallback path TR.2 picks.

- [ ] **HT.6 Connect Worker modal snapshot test.** `ha-addon/ui/e2e/connect-worker-modal.spec.ts` (mocked Playwright). Render the modal, switch format tabs (bash / powershell / compose), grab each rendered command, assert: `--network host` present in bash + compose (post-TR.4); `-e SERVER_URL=` present with the right value; `-v esphome-versions:/esphome-versions` volume mount present. Closes "bash branch silently breaks and every current test sees the modal rendering fine."

- [ ] **HT.7 Real-flow test for `async_step_reconfigure` (post-TR.3).** `tests/test_integration_reconfigure_flow.py` using `pytest_homeassistant_custom_component`'s `hass` fixture and `hass.config_entries.flow.async_init(DOMAIN, context={"source": "reconfigure", "entry_id": ...})`. Exercise: (a) entry exists + valid input, (b) entry exists + invalid URL, (c) entry_id refers to nonexistent entry (TR.3's abort path), (d) context missing `entry_id` (TR.3's `.get()` path). The three bugs in the existing `async_step_reconfigure` would all have been caught by this style of test; `tests/test_integration_reconfigure_logic.py`'s SimpleNamespace shape didn't.

- [ ] **HT.8 One stress test for git-versioning concurrency.** `tests/test_git_versioning.py` gains: 50 concurrent `commit_file` calls via `asyncio.gather` against a single tmp repo. Assert 50 commits land in `git log --oneline | wc -l`, no `.git/index.lock` error, no file-content bleed across commits (e.g. commit N's content appears in commit N+1's tree). Module docstring explicitly flags the `.git/index.lock` race as a concern; there's currently no test that would detect if the module-level lock broke. If it passes today, baseline regression guard; if it fails, we have a real bug to fix.

- [ ] **HT.9 One stress test for firmware-storage concurrency.** `tests/test_firmware_storage.py` gains: 10 concurrent firmware uploads via `asyncio.gather` against a single DAO with a budget set lower than the aggregate size. Assert: none get evicted mid-write (no half-written .bin files survive), budget enforcer's "evict oldest" picks the correct victim under contention, `has_firmware` protection against coalesced-job eviction holds. Module took 81 new lines in 1.6.1 #9; current test file is 142 lines — thin.

- [ ] **HT.10 Protocol cross-version mismatch test.** Pin the current `ha-addon/server/protocol.py` as `tests/fixtures/protocol_v{PROTOCOL_VERSION}.py` at the start of the release cycle. New test in `tests/test_protocol.py`: instantiate a worker-shaped request-builder from the pinned old copy; POST it through the current server; assert graceful `ProtocolError` with a version-mismatch field (no undefined-field crash, no silent parse-as-unrelated-endpoint). PY-6 invariant covers "server + client files byte-identical"; this covers "we didn't break wire compat without bumping `PROTOCOL_VERSION`."

- [ ] **HT.11 Real-flow test for `async_step_reauth` (post-TR.6).** Sibling to HT.7. `tests/test_integration_reauth_flow.py` using the `hass` fixture. Exercise: (a) reauth triggered by `ConfigEntryAuthFailed` during coordinator update → `async_step_reauth` renders the form → valid token submitted → entry updates + reloads; (b) missing `entry_id` in context → `reauth_unknown_entry` abort (TR.6's path); (c) `_reauth_entry` is None because the entry was deleted between trigger and confirm → same abort path (the other half of TR.6). The existing `test_integration_reauth_logic.py` wouldn't have caught TR.6.

- [ ] **HT.12 Integration coverage measurement.** Add `--cov=ha-addon/custom_integration/esphome_fleet` to the `pytest` invocation in `pytest.ini` (or `pyproject.toml`, wherever coverage config currently lives). Pipe to `--cov-report=term-missing --cov-fail-under=95` guarded by an env var so local runs don't fail on intermediate states — CI sets the env var and gates on the threshold. Once HT.1 + HT.7 + HT.11 land, the real number should be comfortably above 95%; confirm and flip `test-coverage` to `done` in `quality_scale.yaml` (closes QS.S1).

---

## CI — Automate the catches

- [ ] **CI.1 `build.yml` workflow — Dockerfile buildx build on every PR.** Runs `docker buildx build --load` on `ha-addon/Dockerfile` and `ha-addon/client/Dockerfile`. Doesn't publish; just asserts the build succeeds. Closes "broken Dockerfile lands on main and only fails in `publish-{server,client}.yml` after merge, when `develop` already advertises the fix." ~3–4 min extra per push; cheap insurance.

- [ ] **CI.2 `apparmor.yml` workflow — profile syntax + load smoke.** New workflow: `apt-get install apparmor-utils`, run `apparmor_parser -N` against `ha-addon/apparmor.txt` to syntax-check, then `docker build` the add-on image and run the container with the profile loaded (`--security-opt apparmor=esphome_dist_server`) — assert the container reaches a healthcheck endpoint. Doesn't prove confinement works; proves the profile loads and doesn't break boot. **Prereq for any meaningful SS.1 tightening (TP.2)** — otherwise the feedback loop for every narrowing attempt is "deploy to hass-4 Sunday and watch what breaks."

- [ ] **CI.3 `compile-test.yml` ESPHome version matrix.** Current: `ESPHOME_VERSION: "2026.3.2"` hardcoded. Matrix it on `{pinned_old: 2026.3.2, latest_stable: <bumped per release>}`. Upstream API regressions (the "2026.4.0 reshaped the API" class of bug from 1.5) land as a CI red on the `latest_stable` axis while the pinned axis anchors reproducibility. ~6–8 min extra in parallel.

- [ ] **CI.4 Hassfest runs the quality-scale validator at our claimed tier.** `.github/workflows/hassfest.yml` today validates manifest shape only. Adjust the action inputs (or run `python3 -m script.hassfest --action quality_scale` directly against a checkout of `home-assistant/core`) so the committed `quality_scale.yaml` gets validated against `manifest.json.quality_scale`'s claimed tier on every PR. Validators that fire at Gold (from `script/hassfest/quality_scale_validation/`): `action_setup.py`, `config_entry_unloading.py`, `config_flow.py`, `diagnostics.py`, `discovery.py`, `parallel_updates.py`, `reauthentication_flow.py`, `reconfiguration_flow.py`, `runtime_data.py`, `test_before_setup.py`, `unique_config_entry.py`. Without this gate, TP.3's tier-flip is a file that could silently rot.

- [ ] **CI.5 PY-10b invariant — skipped-integration-test ratio.** `scripts/check-invariants.sh` gains a rule: count `@pytest.mark.skip` decorators in `tests/test_integration_*.py` files that DON'T end in `_logic.py`; fail if the ratio exceeds 50%. PY-10 today passes with 100% skipped contents (the whole of `test_integration_setup.py`), which means the invariant's filename convention is load-bearing only if the tests inside actually run. Post-HT.1 the skip ratio drops to 0 and this rule is a future-regression guard.

- [ ] **CI.6 Coverage ratchet for the integration.** Add a job step that runs `pytest --cov=ha-addon/custom_integration/esphome_fleet --cov-report=term --cov-fail-under=95` (HT.12) and fails if the number drops below the committed threshold. Store the threshold in a single place (env var or a pytest config key) so bumping it post-HT.1 is one line. Keeps Gold's `test-coverage` claim honest between releases.

---

## UD — UX debt carried from 1.6.1 review (minor polish)

Three items surfaced in `dev-plans/UX_REVIEW-1.6.1.md` §5 as "defer to 1.7." They're small; folding them into 1.6.2 costs little and prevents "defer" from becoming "forgotten." If any one of them grows a tail, push it back out.

- [ ] **UD.1** Add `title` tooltip on the "via ARP" label in the Devices tab so hover explains the detection mechanism (per UX_REVIEW-1.6.1 UX.1).
- [ ] **UD.2** Shorter "Worker selection" column pills at ≤1280px viewport — current text overflows on a standard 13" laptop (UX_REVIEW-1.6.1 UX.2).
- [ ] **UD.3** Reconfigure form's "Submit" button uses the `submit:` translation key, not a hard-coded English label (UX_REVIEW-1.6.1 UX.3). Folds naturally into QS.G5's translation pass.

---

## SD — Scope discipline

- [ ] **SD.1 No new features this release.** Every workitem above either fixes a known-broken path, closes a TEST-AUDIT blind spot, lifts a quality-scale rule to `done`/`exempt`, or aligns a user-facing claim with code reality. If a capability request lands mid-cycle — from a user, a GitHub issue, or a project-internal nice-to-have — it goes to `WORKITEMS-1.7.md` or `WORKITEMS-future.md`. The release is defensible-1.6 hardening + honest Gold or it's nothing. This isn't an artificial constraint; it's the point of the release.

- [ ] **SD.2 Release-blocker gate pre-tag (Gold-grade).** Before tagging `v1.6.2`, every one of the following must be true:
  1. `dev-plans/RELEASE_CHECKLIST.md`'s security-docs cross-check passes (no stale claims).
  2. `python3 -m script.hassfest --action quality_scale` passes clean at the tier declared in `manifest.json.quality_scale`. If the manifest says `gold`, zero errors; if every Gold rule isn't `done`/`exempt`, the manifest tier drops to whatever is honest (silver or bronze) **before** the release tag — we do not ship a claim hassfest doesn't back.
  3. The TEST-AUDIT-1.6.1 Top-5 blind spots (HT.1–HT.5) have landed. Not `in progress`, not `partially`. Landed + merged + CI-green.
  4. `brands` PR at `home-assistant/brands` is either merged (so `brands` can be `done`) or the `quality_scale.yaml:brands` comment carries the open PR URL and tier drops if it was gating Gold.
  5. `scripts/check-invariants.sh` — all rules (PY-1..10, PY-10b from CI.5, HT.2's reseed-consumer rule, UI-1..7, E2E-1) green.
  6. HT.12's coverage number ≥95% for `ha-addon/custom_integration/esphome_fleet/**`.
  7. `ha-addon/CHANGELOG.md` carries TP.4's Corrections-to-1.6.1 section and the changelog accurately describes the tier flip (or the honest retreat, whichever shipped).

- [ ] **SD.3 Produce `TEST-AUDIT-1.6.2.md` as the last workitem before tag.** Prove each TEST-AUDIT-1.6.1 top blind spot has durable closure (a test exists AND would fail without the fix AND the underlying bug class is structurally prevented, not just patched). For each of items 1–13 in TEST-AUDIT-1.6.1, write one line: "closed via HT.X" or "re-deferred — here's why and here's the owning workitem in 1.7." If even one entry reads "we ran out of time," treat that as a signal to cut non-blocking scope and land the test. Audit the audit.

---

## Open Bugs & Tweaks

### Carried forward from 1.6.1

*(none yet — 1.6.1 closed with bugs #1–#22 all addressed. Any post-tag regression against `v1.6.1` lands here as a numbered bug.)*

### New in 1.6.2

*(to be populated as bugs surface)*
