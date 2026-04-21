# Work Items — 1.6.2

Theme: **Honest quality. No new features.** Every item closes a test-audit blind spot, fixes a known-broken path that shipped in 1.6.1 despite a review flag, or rewrites a user-facing claim to match what the code actually does. Read `dev-plans/TEST-AUDIT-1.6.1.md` first — this file is the action plan for the gaps documented there, plus the shipped-but-broken items flagged in the PR #80 review that landed anyway.

Scope rule: **no new user-visible capabilities this release.** If a feature request lands mid-cycle, it goes to `WORKITEMS-1.7.md` or `WORKITEMS-future.md`. The release is defensible-1.6 hardening or it's nothing.

---

## TP — Truth-in-claims (undo the pretend)

The 1.6.1 PR description and SECURITY.md claim a security/quality-scale posture that the code doesn't back up. This section corrects the public-facing docs to match reality and (where cheap) raises reality to match the original claim.

- [ ] **TP.1 Rewrite SECURITY.md's SS.1 paragraph.** Current wording reads as a hardening improvement; the profile is attached-but-permissive (`file, capability, network, signal, dbus, unix, mount, pivot_root, ptrace,` all unqualified = functionally unconfined). Lift the honest caveat from `WORKITEMS-1.6.1.md` SS.1 ("permissive-but-attached buys the security-star credit today; tightening is tracked as future work") up into SECURITY.md proper. Don't ship a second release claiming SS.1 confined anything.

- [ ] **TP.2 Actually tighten the AppArmor profile (SS.1b).** Minimum viable narrow rules that don't break PlatformIO/penv/git/pip: `deny /etc/shadow* rw,`, `deny /run/secrets/** rw,`, `deny /proc/*/mem rw,`, `deny @{PROC}/sys/kernel/** w,`. Drop unqualified `ptrace,` (replace with `deny ptrace,` or remove — nothing in our stack ptraces anything). Verify with hass-4 smoke 17/17 green. Unblocks TP.1 from reading as "SECURITY.md now admits SS.1 is a no-op" → "SECURITY.md describes the first-pass confinement that landed."

- [ ] **TP.3 Ship `quality_scale.yaml` — honest per-rule listing.** New file at `ha-addon/custom_integration/esphome_fleet/quality_scale.yaml` enumerating every silver + bronze rule with status (`done` / `todo` / `exempt`) + a one-line reason each. Run the silver-rules validator locally (`python3 -m script.hassfest --action quality_scale` or the workflow-action equivalent) before committing. **Ground rule:** if more than one or two rules are `todo`, the manifest drops back to `quality_scale: bronze` until they land. The silver claim is real or it isn't — stop publishing it while hassfest's silver validator doesn't run.

- [ ] **TP.4 `PARALLEL_UPDATES = 0` on every entity platform.** Concrete silver-rule breach shipped in 1.6.1. Add the one-liner at module top of `ha-addon/custom_integration/esphome_fleet/{sensor,binary_sensor,button,number,update}.py`. With TP.3 + CI.4 in place, this is enforced at CI time forever.

- [ ] **TP.5 CHANGELOG.md retrospective entry at the top of 1.6.2.** Short "Corrections to 1.6.1" section opening the release notes. Users upgrading from 1.6.1 need to know: (a) the AppArmor profile they thought confined the add-on didn't, now it partly does; (b) the "silver" integration-quality claim was unenforced, it's now backed by `quality_scale.yaml` (or reset to bronze); (c) the four TR.* items below closed paths that shipped broken. No marketing copy — user-centric plain language.

---

## TR — Real-bug remedies (flagged in PR #80 review, merged anyway)

Each of these was explicitly called out before merge. Fixing them here rather than pretending they don't exist.

- [ ] **TR.1 Fix bug #3's disconnect filter.** `ha-addon/server/device_poller.py::_AioesphomeapiDisconnectFilter` mutates `record.levelno` and returns `True`. Per Copilot's review (PR #80 comment), `Logger.callHandlers` already chose the ERROR handler before the filter ran — so the record still ships at ERROR, just with a misleading `DEBUG` label. Fix: return `False` to drop the matching record (simplest) or re-emit on a DEBUG-level logger under a different name and return `False` on the original (keeps the information). Regression test in `tests/test_device_poller.py` using pytest's `caplog` fixture: assert the "disconnect request failed" record does not surface at `ERROR`-level capture.

- [ ] **TR.2 Fix `mdns_advertiser.py` malformed-URL + dead conditional.** `ha-addon/server/mdns_advertiser.py:62` → `base_url = "http://:8765"` when `_primary_ipv4()` returns None. Either skip registration entirely on the None branch (advertising no-IP serves no one) or omit `base_url` from properties. Line 83's `socket.gethostname() if socket.gethostname() else None` is dead code — `gethostname()` always returns a non-empty string; guard against `"localhost"` specifically (which is what actually breaks mDNS resolution). Both covered by HT.5's new test file.

- [ ] **TR.3 Fix the three `async_step_reconfigure` bugs.** `ha-addon/custom_integration/esphome_fleet/config_flow.py`:
  1. Drop the `async_update_reload_and_abort` fallback branch (HA <2024.11 doesn't invoke this step, so the branch is dead code) **or** bump manifest's `homeassistant` minimum from `2024.1.0` to `2024.11` so the comment matches reality.
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

---

## HT — Honest testing (close TEST-AUDIT-1.6.1's top blind spots)

- [ ] **HT.1 Unskip IT.2 — real-hass lifecycle test.** `tests/test_integration_setup.py:126,166` — both tests are `@pytest.mark.skip`-decorated with `TODO(IT.2): plug in async_mock_integration so HA's loader can find esphome_fleet`. Land the wiring. Minimum coverage:
  - `setup → unload → setup` reload cycle. Asserts no duplicate service registration, no leaked listeners, `hass.data[DOMAIN]` cleans up correctly. (This is the CR.12-class bug from 1.5 that the 84 `_logic.py` tests can't catch.)
  - `setup with unreachable server → coordinator retry → recovers`. Asserts `async_setup_entry` doesn't crash on first-poll failure and that the coordinator's retry path restores the entry on the next tick.

  PY-10 invariant becomes load-bearing instead of cosmetic. Prereq for QS.8 (≥95% integration coverage) ever being honest.

- [ ] **HT.2 Reseed-consumer invariant (`check-invariants.sh` new rule).** The class of bug behind **#11 (1.6.1)** (encryption-key race on fresh boot) and **#18 (1.6.1)** (static-IP OTA regression) is the same: `_resolve_esphome_config` returns `None` during the ESPHome lazy-install window, leaving `_encryption_keys` / `_address_overrides` / `_name_map` unseeded. Fix landed as `main.reseed_device_poller_from_config`. New invariant: grep for every module-level read of those three dicts; for each hit, require the same module references `reseed_device_poller_from_config` OR is `main.py` itself. Fails CI if a future consumer lands without the reseed wire-up. **This is the durable close on the bug class — don't skip it in favour of yet another narrow test.**

- [ ] **HT.3 Static-IP fixture suite (the deferred-in-#18 trap).** `tests/fixtures/esphome_configs/` gains: `wifi_use_address.yaml`, `wifi_static_ip.yaml`, `ethernet_static_ip.yaml`, `openthread_use_address.yaml`, `wifi_static_ip_via_substitution.yaml` (`static_ip: ${ip}` + substitutions block), `wifi_static_ip_via_secret.yaml` (`static_ip: !secret my_ip`), `packages_with_network.yaml` (address comes from an included package). New `tests/test_ota_address_resolution.py` parametrises over every fixture and asserts `(address, source)` matches what ESPHome's own `esphome.core.CORE.address` produces against the same YAML — **ESPHome as the oracle, not hand-coded expected values**, so the test tracks upstream behaviour automatically when ESPHome's resolver shifts.

- [ ] **HT.4 `e2e-hass-4/static-ip-ota.spec.ts` — prod regression guard.** Add a target with `wifi.manual_ip.static_ip: 192.0.2.1` (TEST-NET-1, unroutable by design). Trigger compile. Assert the resulting job record has `ota_address == "192.0.2.1"` (not `shopaccesscontrol.local` or similar). Compile fails at the OTA step because the IP is unroutable — intentional; the assertion is on job metadata, not successful upload. The static-IP bug has shipped twice (radiowave911 in 1.4.x and again in 1.6). A third ship is unacceptable; this guard forces the failure mode onto CI instead of into the next support thread.

- [ ] **HT.5 `tests/test_mdns_advertiser.py` — dedicated coverage.** Module shipped in 1.6.1 with zero unit tests. Cover: happy-path register/unregister against a mocked `AsyncZeroconf`; `_primary_ipv4()` returning `None` (post-TR.2 fix: asserts either skip or omitted `base_url`); `stop()` before `start()` doesn't crash; `start()` twice is idempotent (or raises cleanly). Assert `socket.gethostname() == "localhost"` branch uses the fallback path TR.2 picks.

- [ ] **HT.6 Connect Worker modal snapshot test.** `ha-addon/ui/e2e/connect-worker-modal.spec.ts` (mocked Playwright). Render the modal, switch format tabs (bash / powershell / compose), grab each rendered command, assert: `--network host` present in bash + compose (post-TR.4); `-e SERVER_URL=` present with the right value; `-v esphome-versions:/esphome-versions` volume mount present. Closes "bash branch silently breaks and every current test sees the modal rendering fine."

- [ ] **HT.7 Real-flow test for `async_step_reconfigure` (post-TR.3).** `tests/test_integration_reconfigure_flow.py` using `pytest_homeassistant_custom_component`'s `hass` fixture and `hass.config_entries.flow.async_init(DOMAIN, context={"source": "reconfigure", "entry_id": ...})`. Exercise: (a) entry exists + valid input, (b) entry exists + invalid URL, (c) entry_id refers to nonexistent entry (TR.3's abort path), (d) context missing `entry_id` (TR.3's `.get()` path). The three bugs in the existing `async_step_reconfigure` would all have been caught by this style of test; `tests/test_integration_reconfigure_logic.py`'s SimpleNamespace shape didn't.

- [ ] **HT.8 One stress test for git-versioning concurrency.** `tests/test_git_versioning.py` gains: 50 concurrent `commit_file` calls via `asyncio.gather` against a single tmp repo. Assert 50 commits land in `git log --oneline | wc -l`, no `.git/index.lock` error, no file-content bleed across commits (e.g. commit N's content appears in commit N+1's tree). Module docstring explicitly flags the `.git/index.lock` race as a concern; there's currently no test that would detect if the module-level lock broke. If it passes today, baseline regression guard; if it fails, we have a real bug to fix.

- [ ] **HT.9 One stress test for firmware-storage concurrency.** `tests/test_firmware_storage.py` gains: 10 concurrent firmware uploads via `asyncio.gather` against a single DAO with a budget set lower than the aggregate size. Assert: none get evicted mid-write (no half-written .bin files survive), budget enforcer's "evict oldest" picks the correct victim under contention, `has_firmware` protection against coalesced-job eviction holds. Module took 81 new lines in 1.6.1 #9; current test file is 142 lines — thin.

- [ ] **HT.10 Protocol cross-version mismatch test.** Pin the current `ha-addon/server/protocol.py` as `tests/fixtures/protocol_v{PROTOCOL_VERSION}.py` at the start of the release cycle. New test in `tests/test_protocol.py`: instantiate a worker-shaped request-builder from the pinned old copy; POST it through the current server; assert graceful `ProtocolError` with a version-mismatch field (no undefined-field crash, no silent parse-as-unrelated-endpoint). PY-6 invariant covers "server + client files byte-identical"; this covers "we didn't break wire compat without bumping `PROTOCOL_VERSION`."

---

## CI — Automate the catches

- [ ] **CI.1 `build.yml` workflow — Dockerfile buildx build on every PR.** Runs `docker buildx build --load` on `ha-addon/Dockerfile` and `ha-addon/client/Dockerfile`. Doesn't publish; just asserts the build succeeds. Closes "broken Dockerfile lands on main and only fails in `publish-{server,client}.yml` after merge, when `develop` already advertises the fix." ~3–4 min extra per push; cheap insurance.

- [ ] **CI.2 `apparmor.yml` workflow — profile syntax + load smoke.** New workflow: `apt-get install apparmor-utils`, run `apparmor_parser -N` against `ha-addon/apparmor.txt` to syntax-check, then `docker build` the add-on image and run the container with the profile loaded (`--security-opt apparmor=esphome_dist_server`) — assert the container reaches a healthcheck endpoint. Doesn't prove confinement works; proves the profile loads and doesn't break boot. **Prereq for any meaningful SS.1 tightening post-TP.2** — otherwise the feedback loop for every narrowing attempt is "deploy to hass-4 Sunday and watch what breaks."

- [ ] **CI.3 `compile-test.yml` ESPHome version matrix.** Current: `ESPHOME_VERSION: "2026.3.2"` hardcoded. Matrix it on `{pinned_old: 2026.3.2, latest_stable: <bumped per release>}`. Upstream API regressions (the "2026.4.0 reshaped the API" class of bug from 1.5) land as a CI red on the `latest_stable` axis while the pinned axis anchors reproducibility. ~6–8 min extra in parallel.

- [ ] **CI.4 Hassfest runs the silver-rules validator.** `.github/workflows/hassfest.yml` today validates manifest shape only. Adjust the action inputs (or run `python3 -m script.hassfest --action quality_scale` directly) so the committed `quality_scale.yaml` (TP.3) gets validated against its claimed tier on every PR. Without this, TP.3 is another file that could silently rot.

- [ ] **CI.5 PY-10b invariant — skipped-integration-test ratio.** `scripts/check-invariants.sh` gains a rule: count `@pytest.mark.skip` decorators in `tests/test_integration_*.py` files that DON'T end in `_logic.py`; fail if the ratio exceeds 50%. PY-10 today passes with 100% skipped contents (the whole of `test_integration_setup.py`), which means the invariant's filename convention is load-bearing only if the tests inside actually run. Post-HT.1 the skip ratio drops to 0 and this rule is a future-regression guard.

---

## SD — Scope discipline

- [ ] **SD.1 No new features this release.** Every workitem above either fixes a known-broken path, closes a TEST-AUDIT blind spot, or aligns a user-facing claim with code reality. If a capability request lands mid-cycle — from a user, a GitHub issue, or a project-internal nice-to-have — it goes to `WORKITEMS-1.7.md` or `WORKITEMS-future.md`. The release is defensible-1.6 hardening or it's nothing. This isn't an artificial constraint; it's the point of the release.

- [ ] **SD.2 Release-blocker gate pre-tag.** Before tagging `v1.6.2`: run `dev-plans/RELEASE_CHECKLIST.md`'s security-docs cross-check, a fresh `hassfest` with the silver-rules validator enabled (CI.4), and the TEST-AUDIT-1.6.1 Top-5 coverage assertions (HT.1–HT.5 landed). If TP.3 lists more than one silver rule as `todo`, the manifest ships at `bronze` not `silver`. No shipping a claim hassfest doesn't back.

- [ ] **SD.3 Next TEST-AUDIT produced in-release.** Draft `dev-plans/TEST-AUDIT-1.6.2.md` as the last workitem before tag. Goal: prove that the eight TEST-AUDIT-1.6.1 Top-blind-spots got durable closure (not just "patched and moved on"). If an entry in TEST-AUDIT-1.6.1 doesn't have a corresponding "closed via X" line in the 1.6.2 audit, that's a signal the work was cosmetic. Audit the audit.

---

## Open Bugs & Tweaks

### Carried forward from 1.6.1

*(none yet — 1.6.1 closed with bugs #1–#22 all addressed. Any post-tag regression against `v1.6.1` lands here as a numbered bug.)*

### New in 1.6.2

*(to be populated as bugs surface)*
