# Work Items — 1.6.3

Theme: **Honest Gold.** 1.6.2 started under this theme and pivoted mid-cycle to install-path unblocks when real-user bugs surfaced (#82, #83, #84). The Gold work didn't go away — it re-homed here. 1.6.3 walks the remaining Bronze+Silver+Gold quality-scale rules to `done` or honestly-justified `exempt`, closes the TEST-AUDIT-1.6.1 blind spots that stayed open, delegates the remaining hand-rolled ESPHome logic to ESPHome's own code, polishes the UX debt carried from the 1.6.1 review, and flips the `quality_scale: gold` claim in `manifest.json` to one hassfest actually validates.

Read first, in order: `dev-plans/TEST-AUDIT-1.6.1.md` (the authoritative blind-spot list), `ha-addon/custom_integration/esphome_fleet/quality_scale.yaml` (current per-rule status — the header + `runtime-data` hedge got fixed in 1.6.2's TP.3; the rule statuses still need to walk), `dev-plans/archive/WORKITEMS-1.6.2.md` once it's archived at `v1.6.2` tag (so you can see what the pivot landed before this release picked up).

Scope rule: every workitem either (a) closes a TEST-AUDIT blind spot, (b) lifts a quality-scale rule from `todo`/missing to `done`/`exempt`, (c) delegates more hand-rolled code to ESPHome, or (d) polishes UX debt. Gold-equivalence or bust — there is no partial credit here.

Definition of "Gold" for a custom integration: hassfest never runs on out-of-tree code in prod, so "official" Gold isn't available. **Gold-equivalent** means: (i) every rule in Bronze+Silver+Gold of `script/hassfest/quality_scale.py`'s `ALL_RULES` is `done` or `exempt` with a reason in our `quality_scale.yaml`; (ii) a local `python3 -m script.hassfest --action quality_scale` against our integration passes clean when the manifest claims `gold`; (iii) CI runs that same validator on every PR (CI.4) so the claim can't silently rot. That's the bar this release targets.

---

## TP — Truth-in-claims (the quality-scale tier flip)

1.6.2 landed TP.1 (SECURITY.md SS.1 rewrite), TP.2 (AppArmor narrowing), TP.3 docs clauses (a) + (b) (quality_scale.yaml header + runtime-data hedge), and TP.4 (CHANGELOG corrections). What stayed behind is the quality-scale tier flip itself — it only becomes honest once every QS.* item lands.

- [ ] **TP.3 (clauses c + d) — flip `manifest.quality_scale` to `gold` only when it's honest.** (c) Every Bronze+Silver+Gold rule from `script/hassfest/quality_scale.py`'s `ALL_RULES` must appear with `done`/`exempt` in our `quality_scale.yaml` — any rule still `todo` must be closed by a QS.* workitem below or re-scoped to a future release (and the manifest tier drops accordingly). (d) After every QS.* item lands, run `python3 -m script.hassfest --action quality_scale` locally; expect zero errors at tier `gold`. Only then edit `manifest.json` from `quality_scale: bronze` → `quality_scale: gold`. Ground rule: if even one Gold rule stays `todo` at ship-time, manifest stays at `silver` or `bronze` — we do not ship a claim hassfest doesn't back.

---

## EH — ESPHome-delegation (stop hand-rolling what ESPHome already provides)

Audit on 2026-04-22 of `ha-addon/server/` + `ha-addon/client/` looking for places we re-implement functionality ESPHome ships as a library (`esphome.*`) or a CLI (`esphome <subcommand>`). EH.2 landed in 1.6.2-dev.11 along the #84 fix (ESPHome's full validator became the primary resolver). Three remaining items:

- [ ] **EH.1 Use `esphome idedata` for firmware-artifact discovery.** `ha-addon/client/client.py:1225-1275` (`_collect_firmware_variants`) walks `.esphome/build/<name>/.pioenvs/<name>/firmware.{factory,}.bin` via hardcoded path templates. Stable for ESP32/ESP8266 today; breaks the moment ESPHome ships a target platform with a different PlatformIO layout (RP2040, nRF52, Zephyr, the new `host` platform). ESPHome's `esphome idedata <yaml>` (and `esphome.platformio_api.get_idedata()` Python API) emits JSON including `firmware_elf_path`, `firmware_bin_path`, and `extra_flash_images` (list of `{offset, path}` entries for bootloader/partition-table blobs). Fix: after a successful `esphome run`, invoke `<venv>/bin/esphome idedata <yaml>` and parse the JSON as the authoritative artifact manifest; retain today's path walk as a legacy fallback (probe once per job, cache the decision). Bonus: `extra_flash_images` unblocks a future USB-first-flash flow without further reinvention (currently we only archive `firmware.factory.bin` + `firmware.bin`; bootloader + partition table are silently dropped). Test: `tests/test_client_firmware_collection.py` across ESP32 (factory+ota), ESP8266 (ota only), and a synthetic RP2040 fixture; mocked `idedata` JSON drives the parse path and a real compile against `cyd-office-info` proves the wire.

- [ ] **EH.3 Replace magic-string config keys with `esphome.const` imports.** `ha-addon/server/scanner.py` and `ha-addon/client/client.py` reference `"esphome"`, `"name"`, `"wifi"`, `"ethernet"`, `"openthread"`, `"api"`, `"substitutions"`, `"packages"`, `"platform"`, `"framework"`, `"board"`, `"use_address"`, `"manual_ip"`, `"static_ip"`, `"domain"` as string literals scattered across many call sites. ESPHome's own code uses `CONF_ESPHOME`, `CONF_NAME`, `CONF_WIFI`, `CONF_ETHERNET`, `CONF_OPENTHREAD`, `CONF_API`, `CONF_SUBSTITUTIONS`, `CONF_PACKAGES`, `CONF_PLATFORM`, `CONF_FRAMEWORK`, `CONF_BOARD`, `CONF_USE_ADDRESS`, `CONF_MANUAL_IP`, `CONF_STATIC_IP`, `CONF_DOMAIN` from `esphome.const` — any upstream rename becomes an `ImportError` in our layer instead of a silent dict-miss that drops `friendly_name` / `use_address` / etc. for every user. Mechanical sweep; `ruff` + `mypy` + existing test suite catches typos. Scope the change to files where ESPHome is already on `sys.path` (i.e. anywhere touched after `_esphome_ready` fires) — the cold-start fallback paths keep the literal strings so they work before the venv is installed. Pairs naturally with UD.4 (bluetooth-proxy column) since `CONF_BLUETOOTH_PROXY` lives in the same import.

- [ ] **EH.4 Simplify ESPHome version detection.** `ha-addon/server/scanner.py:207-228` (`_get_installed_esphome_version`) shells to `<venv>/bin/esphome version` and string-parses `"Version: X.Y.Z"` on stdout as the primary path; `importlib.metadata.version("esphome")` at lines 232-234 is a fallback. Once the venv's `site-packages` is on `sys.path` (which happens before `_esphome_ready` fires) the two paths return the same answer — the subprocess is redundant and ~50ms of fork+exec on a hot path. Fix: either (a) reorder so `importlib.metadata` is primary and subprocess is the disambiguator when we have reason to believe server-process Python is pointing at a different ESPHome than the venv, or (b) import `esphome.const.__version__` directly (single attr read, no subprocess, no parsing). Keep the current memoization. Lowest priority of the four; bundle with any nearby scanner.py work rather than as a standalone PR. Test: `tests/test_scanner_version.py` with and without the venv activated, asserting the two paths agree and the subprocess is skipped on the warm path.

---

## QS — Quality Scale: path to honest Gold

Every rule below either (i) still reads `todo` in `quality_scale.yaml`, (ii) reads `done` but the code tells a different story, or (iii) is missing from the file entirely. Lifting each to honest `done` or `exempt` is what makes TP.3's tier-flip safe. Rule slugs match `script/hassfest/quality_scale.py`'s `ALL_RULES`.

### QS.B — Bronze (only `brands` outstanding)

- [ ] **QS.B1 Submit brand assets to `home-assistant/brands`.** Artwork is staged under `docs/brands-submission/` (per `quality_scale.yaml:35–40`); the PR to `home-assistant/brands` hasn't been opened. Prepare the submission (matching that repo's README: `icon.png` 256×256, `icon@2x.png` 512×512, `logo.png`, `logo@2x.png` — all under `custom_integrations/esphome_fleet/`), open the PR, link it back here. This rule can ship as `done` in our file once the brands PR is merged; until then, leave it `todo` with the PR URL in the comment so it's visible why Gold's on hold.

### QS.S — Silver

- [ ] **QS.S1 Silver `test-coverage` → Gold-grade coverage.** Silver's bar is ≥95% real line-coverage (not mocked). 1.6.2 landed HT.1 / HT.7 / HT.11 (real-hass lifecycle + reconfigure + reauth flow tests) which unblocks most of this; HT.12 (coverage measurement) still needs to land here. Sequence: HT.12 lands → re-run `pytest --cov=ha-addon.custom_integration.esphome_fleet` → confirm ≥95% → flip `test-coverage` to `done` in `quality_scale.yaml`. Until then it stays `todo` and Gold doesn't ship.

### QS.G — Gold tier (the main lift)

- [ ] **QS.G1 `docs-data-update` — Integration DOCS section.** Add a "How data updates" subsection to `ha-addon/DOCS.md` → Integration. Explain: coordinator polls the add-on's `/ui/api/*` endpoints every 30s (`update_interval=timedelta(seconds=30)` in `coordinator.py`); a push WebSocket supplements the poll for real-time event signals; the user can force an immediate refresh via the integration card's *Reload* button. Flip the `quality_scale.yaml:docs-data-update` entry to `done` when the section is live.

- [ ] **QS.G2 `docs-examples` — formal Examples section.** `DOCS.md` → Integration currently sketches automations informally. Restructure into a `## Examples` section with at least three concrete scenarios, each as a copy-pasteable YAML snippet that references our entities: (i) fire a notification when any target's Update entity reports a pending version, (ii) trigger the `esphome_fleet.compile` service on schedule via HA Scheduler, (iii) route a worker-offline binary-sensor transition to a dashboard warning card. Link at least one to a published HA blueprint if we author one; otherwise note that blueprint contributions are welcome.

- [ ] **QS.G3 `docs-known-limitations` — single dedicated section.** Consolidate what's scattered across `DOCS.md` today into a `## Known limitations` section: (a) HA Core restart required after integration-code upgrade (Python module caching); (b) Supervisor `@sha256:` digest pinning blocked on upstream Supervisor schema; (c) AppArmor profile is first-pass confinement only (narrow denies on secrets + `/proc/*/mem` + `/sys/kernel` writes, unrestricted file/network elsewhere) — link to SECURITY.md for the threat model; (d) worker-offline detection uses a 30s heartbeat window; transient blips of ~45s register as offline-then-online; (e) the factory-vs-OTA firmware-variant distinction isn't surfaced in the integration's Update entity — users pick in the Web UI.

- [ ] **QS.G4 `docs-troubleshooting` — single dedicated section.** Consolidate into `## Troubleshooting` with the symptom→cause→fix shape the gold rule wants: "Integration card says *Reconfigure*" → token rotated or URL changed → run Reconfigure flow; "Entities stuck at *unavailable*" → add-on URL mismatch or add-on stopped → check Supervisor logs + URL; "Zeroconf discovery never fires on a fresh HA" → mDNS reflector not enabled on the router, add-on URL must be entered manually; "Reauth flow dead-ends" → expired refresh-token path, delete + re-add entry (rare; 1.6.2's TR.6 closed a code-path contributor). Four to six items is enough; refresh as real support threads surface.

- [ ] **QS.G5 `entity-translations` — move every `_attr_name` to `_attr_translation_key`.** Current state: zero entities use `_attr_translation_key` (verified by `grep -c _attr_translation_key ha-addon/custom_integration/esphome_fleet/{sensor,binary_sensor,button,number,update}.py` → all 0). Every entity ships an English-only name via `_attr_name = "…"`. Work:
  1. Enumerate every distinct entity shape across the five platforms — target scheduled-upgrade sensor, worker online binary_sensor, worker clean-cache button, worker parallel-slots number, target update entity, etc. Give each a short snake-case translation key.
  2. Replace `_attr_name = "Queue depth"` → `_attr_translation_key = "queue_depth"` (and drop `_attr_name` — HA composes from `entity.<platform>.queue_depth.name` in `strings.json`).
  3. Populate `strings.json` → `entity.sensor.queue_depth.name`, etc., for every key. Mirror to `translations/en.json`.
  4. For entities whose `device_class` already provides a translated name (the built-in rule exemption — `binary_sensor`/`number`/`sensor`/`update` with a device_class set), verify the name shows up correctly without a translation_key and note the exemption in the entity's code comment.
  5. Verify in the HA UI: entity names render identically to today; *Customize* dialog shows the English names as defaults and exposes them for localization.
  6. Flip `entity-translations` to `done` in `quality_scale.yaml`.

- [ ] **QS.G6 `runtime-data` — migrate from `hass.data[DOMAIN][entry.entry_id]` to `entry.runtime_data`.** The `quality_scale.yaml:109–115` comment hedged "migration planned when HA minimum is bumped past 2024.11" — we're well past (today is 2026-04). 1.6.2's TP.3 restated the hedge honestly; 1.6.3 actually migrates. Concretely:
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

- [ ] **QS.G10 Declare `manifest.json.homeassistant` minimum.** Currently the key is absent; HA treats that as "any version." Set `"homeassistant": "2024.11.0"` (or the real minimum we've validated against — coordinate with TR.3 which already declared 2024.11 as the minimum). This clears the ambiguity in the `async_step_reconfigure` dead-branch and locks the `entry.runtime_data` / typed-ConfigEntry requirements at QS.G6. Document the chosen minimum in `DOCS.md` under Installation.

### QS.P — Platinum lookahead (not claimed this release)

- [ ] **QS.P1 Scope `strict-typing` for a future release.** Run `mypy --strict` against `ha-addon/custom_integration/esphome_fleet/` and count the diagnostics; triage into (a) genuinely fixable right here (add an annotation), (b) fixable after QS.G6 lands (typed ConfigEntry alias unlocks half of them), (c) bounded by `Any` on coordinator dict reads — needs a `TypedDict` for the server's response shape (which is pydantic-shaped on the server side; we could import and re-use the `protocol.py` models). **No code changes this release** — but produce a short `dev-plans/STRICT-TYPING-PLAN.md` that enumerates counts, categories, and a 1.7 or 1.8 landing plan. Platinum also needs every dep in `manifest.json.requirements` to ship `py.typed` or a `types-*` stub; since our requirements list is empty, that half is free. Update the `quality_scale.yaml:strict-typing` comment with the counts from the audit.

---

## HT — Honest testing (close TEST-AUDIT-1.6.1's remaining blind spots)

1.6.2 landed HT.1 / HT.7 / HT.11 (real-flow tests wired to the TR.* fixes) and the HT.13 family + HT.14 (install-path regression guards). The remaining TEST-AUDIT blind spots land here.

- [ ] **HT.2 Reseed-consumer invariant (`check-invariants.sh` new rule).** The class of bug behind **#11 (1.6.1)** (encryption-key race on fresh boot) and **#18 (1.6.1)** (static-IP OTA regression) is the same: `_resolve_esphome_config` returns `None` during the ESPHome lazy-install window, leaving `_encryption_keys` / `_address_overrides` / `_name_map` unseeded. Fix landed as `main.reseed_device_poller_from_config`. New invariant: grep for every module-level read of those three dicts; for each hit, require the same module references `reseed_device_poller_from_config` OR is `main.py` itself. Fails CI if a future consumer lands without the reseed wire-up. **This is the durable close on the bug class — don't skip it in favour of yet another narrow test.**

- [ ] **HT.3 Static-IP fixture suite (the deferred-in-#18 trap).** `tests/fixtures/esphome_configs/` gains: `wifi_use_address.yaml`, `wifi_static_ip.yaml`, `ethernet_static_ip.yaml`, `openthread_use_address.yaml`, `wifi_static_ip_via_substitution.yaml` (`static_ip: ${ip}` + substitutions block), `wifi_static_ip_via_secret.yaml` (`static_ip: !secret my_ip`), `packages_with_network.yaml` (address comes from an included package). New `tests/test_ota_address_resolution.py` parametrises over every fixture and asserts `(address, source)` matches what ESPHome's own `esphome.core.CORE.address` produces against the same YAML — **ESPHome as the oracle, not hand-coded expected values**, so the test tracks upstream behaviour automatically when ESPHome's resolver shifts. Also folds in `wifi_domain.yaml`, `ethernet_domain.yaml`, `wifi_domain_via_substitution.yaml`, `wifi_domain_via_secret.yaml` per #84's coverage plan.

- [ ] **HT.4 `e2e-hass-4/static-ip-ota.spec.ts` — prod regression guard.** Add a target with `wifi.manual_ip.static_ip: 192.0.2.1` (TEST-NET-1, unroutable by design). Trigger compile. Assert the resulting job record has `ota_address == "192.0.2.1"` (not `shopaccesscontrol.local` or similar). Compile fails at the OTA step because the IP is unroutable — intentional; the assertion is on job metadata, not successful upload. The static-IP bug has shipped twice (radiowave911 in 1.4.x and again in 1.6). A third ship is unacceptable; this guard forces the failure mode onto CI instead of into the next support thread. Sibling `e2e-hass-4/wifi-domain-ota.spec.ts` for #84 per the coverage plan: target with `wifi.domain: .invalid-tld.test` — compile succeeds, job record's `ota_address` ends in `.invalid-tld.test`, OTA fails at the resolve step.

- [ ] **HT.5 `tests/test_mdns_advertiser.py` — dedicated coverage.** Module shipped in 1.6.1 with zero unit tests. Cover: happy-path register/unregister against a mocked `AsyncZeroconf`; `_primary_ipv4()` returning `None` (post-TR.2 fix: asserts either skip or omitted `base_url`); `stop()` before `start()` doesn't crash; `start()` twice is idempotent (or raises cleanly). Assert `socket.gethostname() == "localhost"` branch uses the fallback path TR.2 picks.

- [ ] **HT.6 Connect Worker modal snapshot test.** `ha-addon/ui/e2e/connect-worker-modal.spec.ts` (mocked Playwright). Render the modal, switch format tabs (bash / powershell / compose), grab each rendered command, assert: `--network host` present in bash + compose (post-TR.4); `-e SERVER_URL=` present with the right value; `-v esphome-versions:/esphome-versions` volume mount present. Closes "bash branch silently breaks and every current test sees the modal rendering fine."

- [ ] **HT.8 One stress test for git-versioning concurrency.** `tests/test_git_versioning.py` gains: 50 concurrent `commit_file` calls via `asyncio.gather` against a single tmp repo. Assert 50 commits land in `git log --oneline | wc -l`, no `.git/index.lock` error, no file-content bleed across commits (e.g. commit N's content appears in commit N+1's tree). Module docstring explicitly flags the `.git/index.lock` race as a concern; there's currently no test that would detect if the module-level lock broke. If it passes today, baseline regression guard; if it fails, we have a real bug to fix.

- [ ] **HT.9 One stress test for firmware-storage concurrency.** `tests/test_firmware_storage.py` gains: 10 concurrent firmware uploads via `asyncio.gather` against a single DAO with a budget set lower than the aggregate size. Assert: none get evicted mid-write (no half-written .bin files survive), budget enforcer's "evict oldest" picks the correct victim under contention, `has_firmware` protection against coalesced-job eviction holds. Module took 81 new lines in 1.6.1 #9; current test file is 142 lines — thin.

- [ ] **HT.10 Protocol cross-version mismatch test.** Pin the current `ha-addon/server/protocol.py` as `tests/fixtures/protocol_v{PROTOCOL_VERSION}.py` at the start of the release cycle. New test in `tests/test_protocol.py`: instantiate a worker-shaped request-builder from the pinned old copy; POST it through the current server; assert graceful `ProtocolError` with a version-mismatch field (no undefined-field crash, no silent parse-as-unrelated-endpoint). PY-6 invariant covers "server + client files byte-identical"; this covers "we didn't break wire compat without bumping `PROTOCOL_VERSION`."

- [ ] **HT.12 Integration coverage measurement.** Add `--cov=ha-addon/custom_integration/esphome_fleet` to the `pytest` invocation in `pytest.ini` (or `pyproject.toml`, wherever coverage config currently lives). Pipe to `--cov-report=term-missing --cov-fail-under=95` guarded by an env var so local runs don't fail on intermediate states — CI sets the env var and gates on the threshold. Once this lands, the real number (post-HT.1 + HT.7 + HT.11) should be comfortably above 95%; confirm and flip `test-coverage` to `done` in `quality_scale.yaml` (closes QS.S1).

---

## CI — Automate the catches

1.6.2 landed CI.1 (Dockerfile buildx smoke) and CI.2 (AppArmor profile syntax + load smoke, paired with TP.2). The remaining four items land here.

- [ ] **CI.3 `compile-test.yml` ESPHome version matrix.** Current: `ESPHOME_VERSION: "2026.4.2"` hardcoded. Matrix it on `{pinned_old: 2026.4.0, latest_stable: <bumped per release>}`. Upstream API regressions (the "2026.4.0 reshaped the API" class of bug from 1.5) land as a CI red on the `latest_stable` axis while the pinned axis anchors reproducibility. ~6–8 min extra in parallel.

- [ ] **CI.4 Hassfest runs the quality-scale validator at our claimed tier.** `.github/workflows/hassfest.yml` today validates manifest shape only. Adjust the action inputs (or run `python3 -m script.hassfest --action quality_scale` directly against a checkout of `home-assistant/core`) so the committed `quality_scale.yaml` gets validated against `manifest.json.quality_scale`'s claimed tier on every PR. Validators that fire at Gold (from `script/hassfest/quality_scale_validation/`): `action_setup.py`, `config_entry_unloading.py`, `config_flow.py`, `diagnostics.py`, `discovery.py`, `parallel_updates.py`, `reauthentication_flow.py`, `reconfiguration_flow.py`, `runtime_data.py`, `test_before_setup.py`, `unique_config_entry.py`. Without this gate, TP.3's tier-flip is a file that could silently rot.

- [ ] **CI.5 PY-10b invariant — skipped-integration-test ratio.** `scripts/check-invariants.sh` gains a rule: count `@pytest.mark.skip` decorators in `tests/test_integration_*.py` files that DON'T end in `_logic.py`; fail if the ratio exceeds 50%. PY-10 today passes with 100% skipped contents (the whole of `test_integration_setup.py`), which means the invariant's filename convention is load-bearing only if the tests inside actually run. Post-HT.1 the skip ratio drops to 0 and this rule is a future-regression guard.

- [ ] **CI.6 Coverage ratchet for the integration.** Add a job step that runs `pytest --cov=ha-addon/custom_integration/esphome_fleet --cov-report=term --cov-fail-under=95` (HT.12) and fails if the number drops below the committed threshold. Store the threshold in a single place (env var or a pytest config key) so bumping it post-HT.1 is one line. Keeps Gold's `test-coverage` claim honest between releases.

---

## UD — UX debt carried from 1.6.1 review (minor polish)

Three items surfaced in `dev-plans/UX_REVIEW-1.6.1.md` §5 as "defer to 1.7." They're small; folding them into 1.6.3 prevents "defer" from becoming "forgotten." Two additional Devices-tab columns join them.

- [ ] **UD.1** Add `title` tooltip on the "via ARP" label in the Devices tab so hover explains the detection mechanism (per UX_REVIEW-1.6.1 UX.1).

- [ ] **UD.2** Shorter "Worker selection" column pills at ≤1280px viewport — current text overflows on a standard 13" laptop (UX_REVIEW-1.6.1 UX.2).

- [ ] **UD.3** Reconfigure form's "Submit" button uses the `submit:` translation key, not a hard-coded English label (UX_REVIEW-1.6.1 UX.3). Folds naturally into QS.G5's translation pass.

- [ ] **UD.4 Devices tab: Bluetooth-proxy column.** Add a "BT proxy" column to the Devices tab rendering one of `active` / `passive` / `–` per target. Source: the target YAML's `bluetooth_proxy:` block — `active: true` → "active", block present without `active:` or with `active: false` → "passive", block absent → "–". Extract in `scanner._extract_metadata`, expose on the `Device` shape (`ha-addon/server/protocol.py` + `ha-addon/ui/src/types/index.ts`), render via `useDeviceColumns.tsx`. Toggleable in the Devices tab's existing column-visibility menu; hidden by default on viewports <1280px (matches UD.2's shape). Pairs with EH.3 — use `CONF_BLUETOOTH_PROXY` once that lands; literal `"bluetooth_proxy"` key is fine for the cold-start path that runs before the venv is on `sys.path`.

- [ ] **UD.5 Devices tab: platform / board column.** Add a "Platform" column showing the chip family (`ESP32`, `ESP8266`, `RP2040`, `Host`, …) with the specific board (`esp32dev`, `nodemcu_32s`, `esp01_1m`, …) on a secondary line or in a hover tooltip. Platform derives from which top-level component block is present in YAML (`esp32:`, `esp8266:`, `rp2040:`, `host:`); board is the `board:` value inside that block. Extract + expose + render as UD.4. Where possible, read from ESPHome's `storage.json` post-compile (the validated source of truth) and fall back to raw YAML only for never-compiled targets. Useful when operating a mixed-chip fleet where "which board is this actually?" matters for firmware-size budgeting and OTA compatibility.

---

## SD — Scope discipline

- [ ] **SD.2 Release-blocker gate pre-tag (Gold-grade).** Before tagging `v1.6.3`, every one of the following must be true:
  1. `dev-plans/RELEASE_CHECKLIST.md`'s security-docs cross-check passes (no stale claims).
  2. `python3 -m script.hassfest --action quality_scale` passes clean at the tier declared in `manifest.json.quality_scale`. If the manifest says `gold`, zero errors; if every Gold rule isn't `done`/`exempt`, the manifest tier drops to whatever is honest (silver or bronze) **before** the release tag — we do not ship a claim hassfest doesn't back.
  3. The TEST-AUDIT-1.6.1 Top-5 blind spots (HT.2–HT.5 here, plus HT.1 which landed in 1.6.2) have landed. Not `in progress`, not `partially`. Landed + merged + CI-green.
  4. `brands` PR at `home-assistant/brands` is either merged (so `brands` can be `done`) or the `quality_scale.yaml:brands` comment carries the open PR URL and tier drops if it was gating Gold.
  5. `scripts/check-invariants.sh` — all rules (PY-1..10, PY-10b from CI.5, HT.2's reseed-consumer rule, UI-1..7, E2E-1) green.
  6. HT.12's coverage number ≥95% for `ha-addon/custom_integration/esphome_fleet/**`.
  7. `ha-addon/CHANGELOG.md` accurately describes what users see changing from 1.6.2 → 1.6.3 (the tier flip, translated entity names, new Devices-tab columns, etc.).

- [ ] **SD.3 Produce `TEST-AUDIT-1.6.2.md` then `TEST-AUDIT-1.6.3.md` as the last workitems before tag.** Prove each TEST-AUDIT-1.6.1 top blind spot has durable closure (a test exists AND would fail without the fix AND the underlying bug class is structurally prevented, not just patched). For each of items 1–13 in TEST-AUDIT-1.6.1, write one line: "closed via HT.X" or "re-deferred — here's why and here's the owning workitem in 1.7." If even one entry reads "we ran out of time," treat that as a signal to cut non-blocking scope and land the test. Audit the audit.

---

## Open Bugs & Tweaks

### Carried forward from 1.6.2

*(Any post-tag regression against `v1.6.2` lands here as a numbered bug once 1.6.2 ships.)*

### New in 1.6.3

*(empty at the start of the cycle; bugs get numbered as they surface.)*
