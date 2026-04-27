# Work Items — 1.7.1

Theme: **Honest Gold — the quality-scale tier flip 1.7.0 punted on.** 1.7.0 carried "Honest Gold" as a workstream alongside heffneil-inspired device-management polish and fleet tags + routing; in practice the tags + routing piece consumed the bandwidth, and the tier-flip slid here. 1.7.1's single user-visible change is `manifest.quality_scale: silver` → `gold` — every workitem below exists in support of that one line being honest at tag time.

Read first, in order: `dev-plans/TEST-AUDIT-1.6.1.md` (the authoritative blind-spot list whose remaining items HT.2–4 / HT.8–10 close), `ha-addon/custom_integration/esphome_fleet/quality_scale.yaml` (the per-rule status — every QS.* below either lifts a `todo` to `done` or replaces an exempt-with-stale-rationale claim with a real one), `dev-plans/archive/WORKITEMS-1.7.0.md` (the four QS / HT / CI items that landed before the slide — HT.5, HT.6, CI.3, CI.5; plus QS.G10's WONTFIX disposition).

Definition of "Gold" for a custom integration: hassfest never runs on out-of-tree code in prod, so "official" Gold isn't available. **Gold-equivalent** means: (i) every rule in Bronze+Silver+Gold of `script/hassfest/quality_scale.py`'s `ALL_RULES` is `done` or `exempt` with a reason in our `quality_scale.yaml`; (ii) a local `python3 -m script.hassfest --action quality_scale` against our integration passes clean when the manifest claims `gold`; (iii) CI runs that same validator on every PR (CI.4) so the claim can't silently rot. That's the bar this release targets.

Scope rule: every workitem below either (a) closes a TEST-AUDIT-1.6.1 blind spot, (b) lifts a quality-scale rule from `todo`/missing to `done`/`exempt`, or (c) hardens the gate around (a)+(b) so the claim survives future drift. Nothing else lands in 1.7.1 — keep the file small and the gate green.

---

## QS — Quality Scale: the rule walk

Every rule below either (i) still reads `todo` in `quality_scale.yaml`, (ii) reads `done` but the code tells a different story, or (iii) is missing from the file entirely. Lifting each to honest `done` or `exempt` is what makes TP.3's tier-flip safe. Rule slugs match `script/hassfest/quality_scale.py`'s `ALL_RULES`.

QS.G10 (declare HA-version floor in `manifest.json`) was attempted in 1.7.0-dev.27 and reverted in dev.28 — the `"homeassistant"` key is core-only, custom-integration manifests reject it. The "document the minimum in DOCS.md" half rolls into QS.G3 below.

### QS.B — Bronze (only `brands` outstanding)

- [ ] **QS.B1 Submit brand assets to `home-assistant/brands`.** Artwork is staged under `docs/brands-submission/` (per `quality_scale.yaml:35–40`); the PR to `home-assistant/brands` hasn't been opened. Prepare the submission (matching that repo's README: `icon.png` 256×256, `icon@2x.png` 512×512, `logo.png`, `logo@2x.png` — all under `custom_integrations/esphome_fleet/`), open the PR, link it back here. This rule can ship as `done` in our file once the brands PR is merged; until then, leave it `todo` with the PR URL in the comment so it's visible why Gold's on hold.

### QS.S — Silver

- [ ] **QS.S1 Silver `test-coverage` → Gold-grade coverage.** Silver's bar is ≥95% real line-coverage (not mocked). 1.6.2 landed HT.1 / HT.7 / HT.11 (real-hass lifecycle + reconfigure + reauth flow tests) which unblocks most of this; HT.12 (coverage measurement) still needs to land here. Sequence: HT.12 lands → re-run `pytest --cov=ha-addon.custom_integration.esphome_fleet` → confirm ≥95% → flip `test-coverage` to `done` in `quality_scale.yaml`. Until then it stays `todo` and Gold doesn't ship. **Chain:** QS.S1 ⇐ HT.12 ⇐ CI.6 (gate).

### QS.G — Gold tier (the main lift)

- [ ] **QS.G1 `docs-data-update` — Integration DOCS section.** Add a "How data updates" subsection to `ha-addon/DOCS.md` → Integration. Explain: coordinator polls the add-on's `/ui/api/*` endpoints every 30s (`update_interval=timedelta(seconds=30)` in `coordinator.py`); a push WebSocket supplements the poll for real-time event signals; the user can force an immediate refresh via the integration card's *Reload* button. Flip the `quality_scale.yaml:docs-data-update` entry to `done` when the section is live.

- [ ] **QS.G2 `docs-examples` — formal Examples section.** `DOCS.md` → Integration currently sketches automations informally. Restructure into a `## Examples` section with at least three concrete scenarios, each as a copy-pasteable YAML snippet that references our entities: (i) fire a notification when any target's Update entity reports a pending version, (ii) trigger the `esphome_fleet.compile` service on schedule via HA Scheduler, (iii) route a worker-offline binary-sensor transition to a dashboard warning card. Link at least one to a published HA blueprint if we author one; otherwise note that blueprint contributions are welcome.

- [ ] **QS.G3 `docs-known-limitations` — single dedicated section.** Consolidate what's scattered across `DOCS.md` today into a `## Known limitations` section: (a) HA Core restart required after integration-code upgrade (Python module caching); (b) Supervisor `@sha256:` digest pinning blocked on upstream Supervisor schema; (c) AppArmor profile is first-pass confinement only (narrow denies on secrets + `/proc/*/mem` + `/sys/kernel` writes, unrestricted file/network elsewhere) — link to SECURITY.md for the threat model; (d) worker-offline detection uses a 30s heartbeat window; transient blips of ~45s register as offline-then-online; (e) the factory-vs-OTA firmware-variant distinction isn't surfaced in the integration's Update entity — users pick in the Web UI; (f) **HA-version floor: this integration requires HA Core ≥ 2024.11** — declared here rather than in `manifest.json` because custom-integration manifests reject the `homeassistant` key (see the QS.G10 disposition in `dev-plans/archive/WORKITEMS-1.7.0.md`); the constraint is enforced at runtime via API-shape checks, and HA <2024.11 will surface an unhelpful traceback rather than a clean message.

- [ ] **QS.G4 `docs-troubleshooting` — single dedicated section.** Consolidate into `## Troubleshooting` with the symptom→cause→fix shape the gold rule wants: "Integration card says *Reconfigure*" → token rotated or URL changed → run Reconfigure flow; "Entities stuck at *unavailable*" → add-on URL mismatch or add-on stopped → check Supervisor logs + URL; "Zeroconf discovery never fires on a fresh HA" → mDNS reflector not enabled on the router, add-on URL must be entered manually; "Reauth flow dead-ends" → expired refresh-token path, delete + re-add entry (rare; 1.6.2's TR.6 closed a code-path contributor). Four to six items is enough; refresh as real support threads surface.

- [ ] **QS.G5 `entity-translations` — move every `_attr_name` to `_attr_translation_key`.** Current state: zero entities use `_attr_translation_key` (verified by `grep -c _attr_translation_key ha-addon/custom_integration/esphome_fleet/{sensor,binary_sensor,button,number,update}.py` → all 0). Every entity ships an English-only name via `_attr_name = "…"`. Work:
  1. Enumerate every distinct entity shape across the five platforms — target scheduled-upgrade sensor, worker online binary_sensor, worker clean-cache button, worker parallel-slots number, target update entity, etc. Give each a short snake-case translation key.
  2. Replace `_attr_name = "Queue depth"` → `_attr_translation_key = "queue_depth"` (and drop `_attr_name` — HA composes from `entity.<platform>.queue_depth.name` in `strings.json`).
  3. Populate `strings.json` → `entity.sensor.queue_depth.name`, etc., for every key. Mirror to `translations/en.json`.
  4. For entities whose `device_class` already provides a translated name (the built-in rule exemption — `binary_sensor`/`number`/`sensor`/`update` with a device_class set), verify the name shows up correctly without a translation_key and note the exemption in the entity's code comment.
  5. Verify in the HA UI: entity names render identically to today; *Customize* dialog shows the English names as defaults and exposes them for localization.
  6. Flip `entity-translations` to `done` in `quality_scale.yaml`.

- [ ] **QS.G6 `runtime-data` — migrate from `hass.data[DOMAIN][entry.entry_id]` to `entry.runtime_data`.** The `quality_scale.yaml:109–115` comment hedged "migration planned when HA minimum is bumped past 2024.11" — we're well past (today is 2026-04). 1.6.2's TP.3 restated the hedge honestly; 1.7.1 actually migrates. Concretely:
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

### QS.P — Platinum lookahead (not claimed this release)

- [ ] **QS.P1 Scope `strict-typing` for a future release.** Run `mypy --strict` against `ha-addon/custom_integration/esphome_fleet/` and count the diagnostics; triage into (a) genuinely fixable right here (add an annotation), (b) fixable after QS.G6 lands (typed ConfigEntry alias unlocks half of them), (c) bounded by `Any` on coordinator dict reads — needs a `TypedDict` for the server's response shape (which is pydantic-shaped on the server side; we could import and re-use the `protocol.py` models). **No code changes this release** — but produce a short `dev-plans/STRICT-TYPING-PLAN.md` that enumerates counts, categories, and a 1.8 or 1.9 landing plan. Platinum also needs every dep in `manifest.json.requirements` to ship `py.typed` or a `types-*` stub; since our requirements list is empty, that half is free. Update the `quality_scale.yaml:strict-typing` comment with the counts from the audit.

---

## HT — Honest testing (close TEST-AUDIT-1.6.1's remaining blind spots)

1.6.2 landed HT.1 / HT.7 / HT.11 (real-flow tests wired to the TR.* fixes), HT.14 (standalone-Docker install regression guard), and the full HT.13 family. 1.7.0 added HT.5 (mdns advertiser unit coverage) and HT.6 (Connect Worker modal e2e). The remaining TEST-AUDIT blind spots (and the CI wiring for HT.13/HT.14, which both need a GHCR-reachable runner with SSH reach to a test host) land here.

### Static-IP regression coverage (the bug class behind #18 + #84)

HT.2/HT.3/HT.4 are one bug class — `_resolve_esphome_config` returning `None` during the ESPHome lazy-install window leaving address-resolution dicts unseeded — covered at three altitudes (invariant grep, fixture matrix, prod e2e). Land them together; partial coverage at any one altitude leaves the regression path open.

- [ ] **HT.2 Reseed-consumer invariant (`check-invariants.sh` new rule).** The class of bug behind **#11 (1.6.1)** (encryption-key race on fresh boot) and **#18 (1.6.1)** (static-IP OTA regression) is the same: `_resolve_esphome_config` returns `None` during the ESPHome lazy-install window, leaving `_encryption_keys` / `_address_overrides` / `_name_map` unseeded. Fix landed as `main.reseed_device_poller_from_config`. New invariant: grep for every module-level read of those three dicts; for each hit, require the same module references `reseed_device_poller_from_config` OR is `main.py` itself. Fails CI if a future consumer lands without the reseed wire-up. **This is the durable close on the bug class — don't skip it in favour of yet another narrow test.**

- [ ] **HT.3 Static-IP fixture suite (the deferred-in-#18 trap).** `tests/fixtures/esphome_configs/` gains: `wifi_use_address.yaml`, `wifi_static_ip.yaml`, `ethernet_static_ip.yaml`, `openthread_use_address.yaml`, `wifi_static_ip_via_substitution.yaml` (`static_ip: ${ip}` + substitutions block), `wifi_static_ip_via_secret.yaml` (`static_ip: !secret my_ip`), `packages_with_network.yaml` (address comes from an included package). New `tests/test_ota_address_resolution.py` parametrises over every fixture and asserts `(address, source)` matches what ESPHome's own `esphome.core.CORE.address` produces against the same YAML — **ESPHome as the oracle, not hand-coded expected values**, so the test tracks upstream behaviour automatically when ESPHome's resolver shifts. Also folds in `wifi_domain.yaml`, `ethernet_domain.yaml`, `wifi_domain_via_substitution.yaml`, `wifi_domain_via_secret.yaml` per #84's coverage plan.

- [ ] **HT.4 `e2e-hass-4/static-ip-ota.spec.ts` — prod regression guard.** Add a target with `wifi.manual_ip.static_ip: 192.0.2.1` (TEST-NET-1, unroutable by design). Trigger compile. Assert the resulting job record has `ota_address == "192.0.2.1"` (not `shopaccesscontrol.local` or similar). Compile fails at the OTA step because the IP is unroutable — intentional; the assertion is on job metadata, not successful upload. The static-IP bug has shipped twice (radiowave911 in 1.4.x and again in 1.6). A third ship is unacceptable; this guard forces the failure mode onto CI instead of into the next support thread. Sibling `e2e-hass-4/wifi-domain-ota.spec.ts` for #84 per the coverage plan: target with `wifi.domain: .invalid-tld.test` — compile succeeds, job record's `ota_address` ends in `.invalid-tld.test`, OTA fails at the resolve step.

### Concurrency stress for thin modules

HT.8 + HT.9 share a frame: each module took a non-trivial complexity bump (git-versioning lock, firmware-storage eviction) without commensurate test growth. One stress test per module — passes today = baseline regression guard, fails today = real bug surfaced. Cheap to write, durable in value.

- [ ] **HT.8 One stress test for git-versioning concurrency.** `tests/test_git_versioning.py` gains: 50 concurrent `commit_file` calls via `asyncio.gather` against a single tmp repo. Assert 50 commits land in `git log --oneline | wc -l`, no `.git/index.lock` error, no file-content bleed across commits (e.g. commit N's content appears in commit N+1's tree). Module docstring explicitly flags the `.git/index.lock` race as a concern; there's currently no test that would detect if the module-level lock broke. If it passes today, baseline regression guard; if it fails, we have a real bug to fix.

- [ ] **HT.9 One stress test for firmware-storage concurrency.** `tests/test_firmware_storage.py` gains: 10 concurrent firmware uploads via `asyncio.gather` against a single DAO with a budget set lower than the aggregate size. Assert: none get evicted mid-write (no half-written .bin files survive), budget enforcer's "evict oldest" picks the correct victim under contention, `has_firmware` protection against coalesced-job eviction holds. Module took 81 new lines in 1.6.1 #9; current test file is 142 lines — thin.

### Wire-format coverage

- [ ] **HT.10 Protocol cross-version mismatch test.** Pin the current `ha-addon/server/protocol.py` as `tests/fixtures/protocol_v{PROTOCOL_VERSION}.py` at the start of the release cycle. New test in `tests/test_protocol.py`: instantiate a worker-shaped request-builder from the pinned old copy; POST it through the current server; assert graceful `ProtocolError` with a version-mismatch field (no undefined-field crash, no silent parse-as-unrelated-endpoint). PY-6 invariant covers "server + client files byte-identical"; this covers "we didn't break wire compat without bumping `PROTOCOL_VERSION`."

### Coverage measurement (closes QS.S1; gated by CI.6)

- [ ] **HT.12 Integration coverage measurement.** Add `--cov=ha-addon/custom_integration/esphome_fleet` to the `pytest` invocation in `pytest.ini` (or `pyproject.toml`, wherever coverage config currently lives). Pipe to `--cov-report=term-missing --cov-fail-under=95` guarded by an env var so local runs don't fail on intermediate states — CI sets the env var and gates on the threshold. Once this lands, the real number (post-HT.1 + HT.7 + HT.11) should be comfortably above 95%; confirm and flip `test-coverage` to `done` in `quality_scale.yaml` (closes QS.S1).

### Test-infrastructure carryover

- [ ] **HT.15 Automate config-entry creation on the haos-pve test VM.** Discovered 1.6.2-pre-tag while broadening `@requires-ha` coverage to haos-pve in commit 382e2b8: the integration installer copies files to `/config/custom_components/esphome_fleet/` at add-on boot, but no automated step completes the config flow, so HA never registers `esphome_fleet.compile` / `cancel` / `validate` services. Result: the three `ha-services.spec.ts` specs (#64) returned 400 against haos-pve — not a 1.6.2 regression, just a test-infrastructure gap on the throwaway VM. Workaround landed: tagged the affected describe block with `@requires-integration-config` and `--grep-invert`-filtered it on haos-pve in `scripts/test-matrix.py`. The proper fix is to add a step to `scripts/haos/install-addon.sh` (or a new helper invoked from `push-to-haos.sh`) that POSTs `/api/config/config_entries/flow` with `domain=esphome_fleet`, walks `async_step_user` with `base_url` + the add-on token sourced from `~/.config/distributed-esphome/haos-addon-token`, and confirms the entry reaches `loaded` state before Playwright kicks off. Once that lands, drop `--grep-invert=@requires-integration-config` from the haos-pve target so all `@requires-ha` specs run there too.

---

## TP — Truth-in-claims (the tier flip itself)

TP.3 is the single delivery this release exists to make; CI.4 below is its gate. Land them as one push, in order: TP.3 (after every QS.* lands) → CI.4 (so future drift fails the build, not the next reviewer).

- [ ] **TP.3 (clauses c + d) — flip `manifest.quality_scale` to `gold` only when it's honest.** (c) Every Bronze+Silver+Gold rule from `script/hassfest/quality_scale.py`'s `ALL_RULES` must appear with `done`/`exempt` in our `quality_scale.yaml` — any rule still `todo` must be closed by a QS.* workitem above or re-scoped to a future release (and the manifest tier drops accordingly). (d) After every QS.* item lands, run `python3 -m script.hassfest --action quality_scale` locally; expect zero errors at tier `gold`. Only then edit `manifest.json` from `quality_scale: bronze` → `quality_scale: gold`. Ground rule: if even one Gold rule stays `todo` at ship-time, manifest stays at `silver` or `bronze` — we do not ship a claim hassfest doesn't back.

---

## CI — Gate the Gold claim

CI.4 protects the tier flip (TP.3); CI.6 protects the coverage claim (HT.12 / QS.S1). Without both gates, "honest" Gold reverts to "honest at tag time, anyone's guess by next release."

- [ ] **CI.4 Hassfest runs the quality-scale validator at our claimed tier.** `.github/workflows/hassfest.yml` today validates manifest shape only. Adjust the action inputs (or run `python3 -m script.hassfest --action quality_scale` directly against a checkout of `home-assistant/core`) so the committed `quality_scale.yaml` gets validated against `manifest.json.quality_scale`'s claimed tier on every PR. Validators that fire at Gold (from `script/hassfest/quality_scale_validation/`): `action_setup.py`, `config_entry_unloading.py`, `config_flow.py`, `diagnostics.py`, `discovery.py`, `parallel_updates.py`, `reauthentication_flow.py`, `reconfiguration_flow.py`, `runtime_data.py`, `test_before_setup.py`, `unique_config_entry.py`. Without this gate, TP.3's tier-flip is a file that could silently rot.

- [ ] **CI.6 Coverage ratchet for the integration.** Add a job step that runs `pytest --cov=ha-addon/custom_integration/esphome_fleet --cov-report=term --cov-fail-under=95` (HT.12) and fails if the number drops below the committed threshold. Store the threshold in a single place (env var or a pytest config key) so bumping it post-HT.1 is one line. Keeps Gold's `test-coverage` claim honest between releases.

---

## SD — Scope discipline (pre-tag gates)

- [ ] **SD.2 Release-blocker gate pre-tag (Gold-grade).** Before tagging `v1.7.1`, every one of the following must be true:
  1. `dev-plans/RELEASE_CHECKLIST.md`'s security-docs cross-check passes (no stale claims).
  2. `python3 -m script.hassfest --action quality_scale` passes clean at the tier declared in `manifest.json.quality_scale`. If the manifest says `gold`, zero errors; if every Gold rule isn't `done`/`exempt`, the manifest tier drops to whatever is honest (silver or bronze) **before** the release tag — we do not ship a claim hassfest doesn't back.
  3. The TEST-AUDIT-1.6.1 Top-5 blind spots (HT.2–HT.4 here, plus HT.1 in 1.6.2 and HT.5 in 1.7.0) have landed. Not `in progress`, not `partially`. Landed + merged + CI-green.
  4. `brands` PR at `home-assistant/brands` is either merged (so `brands` can be `done`) or the `quality_scale.yaml:brands` comment carries the open PR URL and tier drops if it was gating Gold.
  5. `scripts/check-invariants.sh` — all rules (PY-1..10, PY-10b, HT.2's reseed-consumer rule, UI-1..7, E2E-1) green.
  6. HT.12's coverage number ≥95% for `ha-addon/custom_integration/esphome_fleet/**`.
  7. `ha-addon/CHANGELOG.md` accurately describes what users see changing from 1.7.0 → 1.7.1 (the tier flip, translated entity names, runtime-data migration, the new docs sections, repair-issues surfacing). Per CLAUDE.md: only changes relative to 1.7.0; the QS.G10 attempt+revert from 1.7.0-dev never existed from the user's perspective.

- [ ] **SD.3 Produce `TEST-AUDIT-1.7.1.md` as the last workitem before tag.** Prove each TEST-AUDIT-1.6.1 top blind spot has durable closure (a test exists AND would fail without the fix AND the underlying bug class is structurally prevented, not just patched). For each of items 1–13 in TEST-AUDIT-1.6.1, write one line: "closed via HT.X (1.6.2 / 1.7.0 / 1.7.1)" or "re-deferred — here's why and here's the owning workitem in 1.8." If even one entry reads "we ran out of time," treat that as a signal to cut non-blocking scope and land the test. Audit the audit. Also produce `TEST-AUDIT-1.7.0.md` covering tags + routing + DM + RC if 1.7.0 ships without one — defer to whichever turn closes the 1.7.0 release.

---

## Open Bugs & Tweaks

### Carried forward from 1.7.0

*(Any post-tag regression against `v1.7.0` lands here as a numbered bug once 1.7.0 ships.)*

### New in 1.7.1

*(none yet)*
