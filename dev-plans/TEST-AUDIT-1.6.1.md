# Test Audit — 1.6.1

**Authored:** 2026-04-20 against `develop` at `021dafe` (release/1.6.1).
**Scope:** identify the biggest coverage gaps across the Python + Playwright + CI surfaces, and rank the areas most likely to regress in 1.6.2+.

Not a pat-on-the-back doc. The suite is genuinely substantial — ~39 Python test files, 6500+ LOC in the five biggest alone, 110+ mocked Playwright tests, 17 real-hass prod-smoke tests, and 16 `check-invariants.sh` rules. But every codebase of this size has shapes of bug the tests can't catch, and 1.6 + 1.6.1 shipped two different symptoms of the same underlying blind spot (encryption-key race at fresh boot → static-IP OTA regression). That's the repeated-failure-mode signal this audit is designed around.

---

## Coverage landscape (snapshot)

| Surface | Files | Tests | Notes |
|---|---|---|---|
| `tests/test_*.py` (unit + service) | 39 | ~400+ | Ruff/mypy/pytest gate CI on every push. Big modules: `test_ui_api.py` (67 tests, 1446 LOC), `test_queue.py` (64 tests, 1099 LOC), `test_git_versioning.py` (48 tests, 952 LOC), `test_settings.py` (718 LOC). |
| `tests/test_integration_*_logic.py` | 10 | 84 | All SimpleNamespace / mock-based. Cheap to run; *don't* catch the CR.12-class lifecycle bugs they're named for. |
| `tests/test_integration_setup.py` | 1 | 2 | The only file that imports `pytest_homeassistant_custom_component`. **Both tests are `@pytest.mark.skip`-decorated** (IT.2 TODO still open). |
| `ha-addon/ui/e2e/*.spec.ts` (mocked) | 23 | ~110 | Fast (~1–2 min). Good UI regression net for rendered state + route interception. |
| `ha-addon/ui/e2e-hass-4/*.spec.ts` (real) | 5 | 17 | Full compile + OTA against a real device (`cyd-office-info`). The only surface that exercises the worker → ESP32 path end-to-end. |
| `.github/workflows/hassfest.yml` | 1 | (opaque) | Validates manifest *schema*. Does NOT validate the silver/gold rules — no `quality_scale.yaml` committed. |
| `.github/workflows/compile-test.yml` | 1 | 16 fixtures | Real `esphome compile` across 16 YAMLs at pinned ESPHome `2026.3.2`. Catches toolchain regressions but pinned to one version. |
| `scripts/check-invariants.sh` | 1 | 16 rules | Grep-shaped: PY-1..10, UI-1..7, E2E-1. Cheap and reliable; limited to patterns that grep can see. |

---

## Top blind spots, ranked by (likelihood × blast radius)

### 1. HA integration lifecycle — IT.2 still skipped (HIGH / HIGH)

`tests/test_integration_setup.py:126,166` — both tests wear `@pytest.mark.skip` with `TODO(IT.2): plug in async_mock_integration so HA's loader can find esphome_fleet`. The 10 `_logic.py` suites pass against `SimpleNamespace` mocks and happily accept code that leaks listeners, registers services twice, or forgets to clean up in `async_on_unload` — the exact CR.12 shape from 1.5. PY-10 invariant enforces the import so the filename stays honest, but the invariant's value is zero if every test inside is skipped.

**Fix direction** — finish the `async_mock_integration` wiring. Two tests is the minimum: `setup → unload → setup` (reload cycle) and `setup with unreachable server → retry after coordinator update`. Everything else downstream flows from the fixture being real.

**Severity:** this is where the next CR.12 will ship unnoticed. Silver claim's Gold-grade-coverage rule (QS.8 in 1.6.1) explicitly depends on IT.1/IT.2/IT.3 landing.

### 2. Silver-tier rules are unenforced (HIGH / HIGH)

No `ha-addon/custom_integration/esphome_fleet/quality_scale.yaml`. Hassfest validates the manifest schema only; the silver rules checker is a separate validator that reads `quality_scale.yaml` with per-rule status. Without the file, you could flip the manifest to `platinum` tomorrow and hassfest still passes. Concrete rule the repo currently fails without noticing: **`PARALLEL_UPDATES` unset on every entity platform** (`sensor.py`, `binary_sensor.py`, `button.py`, `number.py`, `update.py`) — already flagged in the PR #80 review.

**Fix direction** — ship `quality_scale.yaml` listing each rule as `done` / `todo` / `exempt` with reasoning. Run `hassfest --requirements --action quality_scale` (or the workflow action's equivalent) to get a list of currently-failing rules before committing the file.

### 3. AppArmor profile has zero regression surface (HIGH / MED-HIGH)

`ha-addon/apparmor.txt` is honestly a no-op today (every operation class allowed unconditionally — see the PR #80 review). When it gets tightened (follow-up tracked as SS.1's "permissive-but-attached → observed-narrow-rules"), the feedback loop is "deploy to hass-4 and watch what breaks." No CI workflow loads the profile, boots the container, and exercises PlatformIO + pip + ESPHome + mDNS. One broken rule, and it surfaces at deploy time on a Sunday.

**Fix direction** — add a `apparmor.yml` GH workflow: apt-get install `apparmor-utils` + parser, syntax-check the profile with `apparmor_parser -N`, then `docker build` the add-on image with the profile loaded and assert the container reaches a known-good healthcheck. Doesn't need to prove full confinement; just "profile parses and the add-on still boots." Stop the Sunday-deploy class of surprise.

### 4. `_resolve_esphome_config` returning `None` is a recurring bug shape (HIGH / HIGH)

This is the actual "same root cause ships twice" finding. Bug **#11** (live-logs `Connection requires encryption` on fresh boot — 1.6.1) and Bug **#18** (static-IP OTA regression — 1.6.1) are different symptoms of `_resolve_esphome_config` returning `None` during the ESPHome lazy-install window, leaving `_encryption_keys` / `_address_overrides` unpopulated. Fix landed as `main.reseed_device_poller_from_config(...)` hook + `scanner.build_name_to_target_map` hyphen/underscore normalisation.

**What's covered now:** `tests/test_versioning_enable_hook.py` covers the settings→init_repo path (different hook). The reseed hook has three narrow tests (`test_name_map_encryption_keys_include_underscore_variant`, `test_reseed_device_poller_refreshes_after_install`, `test_reseed_device_poller_no_op_when_poller_absent`).

**What's not covered:** the *class* of bug. No test enumerates "every downstream consumer of `build_name_to_target_map`" and asserts it gets re-seeded. If 1.7 adds a fourth consumer of `_address_overrides` or `_encryption_keys` and forgets the reseed hook, tests pass and symptom #3 ships.

**Fix direction** — make the blind spot impossible to hit again:
- **Invariant** (`check-invariants.sh`): grep for any module-level assignment from scanner helpers that isn't also touched by `reseed_device_poller_from_config` — fails CI if a future consumer is added without the reseed wire-up. One rule; closes the class.
- **Fixture-driven suite** under `tests/fixtures/esphome_configs/` covering each address-source path (`wifi_use_address.yaml`, `wifi_static_ip.yaml`, `ethernet_static_ip.yaml`, `openthread_use_address.yaml`, `wifi_static_ip_via_substitution.yaml`, `wifi_static_ip_via_secret.yaml`, `packages_with_network.yaml`) with assertions that use ESPHome's own `CORE.address` as the oracle. Already documented in WORKITEMS-1.6.1 #18 as deferred; the "deferred" is the real trap.
- **`e2e-hass-4/static-ip-ota.spec.ts`** regression guard asserting `ota_address == "<literal IPv4>"` (not `*.local`) on the worker's job record after a compile against a target with `wifi.manual_ip.static_ip`. Compile fails at OTA against an unroutable test-net IP; the assertion is on the job metadata, not successful upload.

### 5. `ha-addon/server/mdns_advertiser.py` has no dedicated test file (MED / MED)

`tests/test_mdns_advertiser.py` doesn't exist. The module is brand-new in 1.6.1 and has specific failure modes a unit test would catch:

- `_primary_ipv4()` returns `None` → `base_url = "http://:8765"` gets advertised (see PR #80 review finding B).
- `socket.gethostname()` returns `"localhost"` on some minimal container images → `"localhost.local."` advertised, can't resolve.
- `async_unregister_service` called before `async_register_service` finished → stop-before-start race.
- Duplicate instance name on the LAN (two HA instances running the add-on) → mDNS conflict resolution isn't asserted.

**Fix direction** — add `tests/test_mdns_advertiser.py` with at minimum: happy-path register/unregister (mock `AsyncZeroconf`), `_primary_ipv4 is None` branch (assert either skip or omit-base_url), `stop()` before `start()` doesn't crash.

### 6. Git-versioning races aren't stress-tested (MED / HIGH)

`tests/test_git_versioning.py` is 952 lines / 48 tests — strong *functional* coverage. But the gotchas in the actual code ("commits race on `.git/index.lock`", see module docstring) are the kind of thing a single-event-loop unit test can't reproduce. `conftest.py`'s `_reset_auto_versioning_state` fixture exists specifically because `commit_file` schedules async tasks bound to a per-test event loop — meaning the existing tests have already hit "tasks leak across loops" and papered it over with a reset, not a test that asserts the serialisation actually works.

**Fix direction** — one stress test under `tests/test_git_versioning.py`: 50 concurrent `commit_file` calls via `asyncio.gather` against a single tmp repo. Assert: 50 commits in `git log`, no index-lock error, no file-content mix-up across commits. If that passes today, great — baseline guard against future regressions. If it fails, we have a real concurrency bug.

Related: **settings-lock ordering in the init_repo hook (#19)**. Workitem body flags that `update_settings` holds `_get_lock()` when it would dispatch `init_repo`; `run_in_executor` handles the subprocess-outside-the-lock aspect but no test asserts concurrent `update_settings` calls don't deadlock.

### 7. Dockerfile + AppArmor integration has no pre-push guard (MED / MED)

`.github/workflows/publish-{server,client}.yml` run `docker build` on publish, which is after merge to main. CI on `develop` doesn't run a full `docker build` — only `compile-test.yml` uses the client image, and it pulls published layers rather than rebuilding. A broken Dockerfile lands on main, publish fails there, and `develop` is already advertising the fix as shipped.

**Related**: the Supervisor-rejects-`@sha256:`-build_from detection relies on the next `apt-get` layer failing (see PR #80 review finding — the Debian-only guard would make this explicit).

**Fix direction** — add a `build.yml` workflow that runs `docker buildx build --load` on both Dockerfiles on every PR. Doesn't need to publish; just needs to build. ~3-4 min extra per push; buys pre-merge detection of any Dockerfile-shape bug.

### 8. `firmware_storage.py` coverage is thin relative to its surface (MED / MED)

`tests/test_firmware_storage.py` is 142 lines. The module took 81 new lines in 1.6.1 (#9 "archive every successful compile, OTA path included"). Budget enforcer + orphan reconciler are the real race-prone paths (WORKING-state checks during concurrent write, retention eviction under disk pressure). Bug #1's `has_firmware` protection against coalesced-job garbage-collection is asserted at the functional level but not under pressure.

**Fix direction** — one stress test: spawn 10 concurrent firmware uploads against a single DAO, assert none get evicted mid-write, assert the budget enforcer's "evict oldest" picks the right victim. Follow the same shape as the git-versioning stress test.

### 9. Real vs. mocked integration split — 84 tests that don't prove lifecycle (MED / MED)

The 10 `_logic.py` files (~1800 LOC total) test pure functions: `_normalize_base_url`, `async_get_config_entry_diagnostics`'s redaction shape, `_system_health_info`'s keys, `_prune_stale_devices`'s set-math. All valuable, none catch what IT.1–IT.3 are trying to catch. The naming convention (PY-10) is load-bearing *only if* the real `test_integration_setup.py` actually runs. It doesn't (#1 above).

Separate blind spot: **`async_step_reconfigure` (QS.5) has logic tests but no flow test**. The three issues in PR #80 review (unreachable fallback branch, KeyError on missing context, AssertionError on missing entry) would not be caught by `tests/test_integration_reconfigure_logic.py` — a real `hass.config_entries.flow.async_init(..., context={"source": "reconfigure", "entry_id": "bogus"})` would catch them all.

### 10. `compile-test.yml` pins ESPHome `2026.3.2` (LOW / MED)

Current stable is `2026.4.1`. If ESPHome ships a breaking compile-time regression in 2026.4 or 2026.5, we don't see it in CI. Bug #84 in 1.4 was exactly this shape — pinned server was blind to upstream API changes until we tried to bump.

**Fix direction** — matrix the workflow on {pinned_old, latest_stable, latest_beta} so upstream regressions land as a CI red on the `latest_*` axis while the pinned axis anchors reproducibility. Lightweight: matrix adds ~6–8 min in parallel.

### 11. Worker-selection reason (#8) edge cases (LOW / LOW)

`api._handle_claim`'s reason derivation (`pinned_to_worker` / `only_online_worker` / `fewer_jobs_than_others` / `higher_perf_score` / `first_available`) has functional coverage. Not covered: two workers claiming simultaneously with the same perf_score (tie-breaker), racing heartbeats while the claim happens (stale registry snapshot). Low-blast-radius because the reason is displayed not acted upon, but the values end up in the UI's "Worker selection" column and users will file bugs when they say the wrong thing.

### 12. Connect Worker modal's docker-run bash branch missing `--network host` (MED / MED)

Flagged in the PR #80 review — the compose branch has `network_mode: host`, the bash branch doesn't. Every test suite sees the modal rendering correctly because all tests assert structural presence, not output correctness. A user copying the bash output into `docker run` on a LAN with workers behind a NAT bridge would get a worker that can't OTA. Invisible to every current test.

**Fix direction** — snapshot-test in `tests/test_connect_worker_modal.spec.ts` (mocked Playwright): render the modal, grab the output, assert `--network host` is in the bash branch. Takes 5 lines.

### 13. Protocol cross-version compat (LOW / HIGH)

`tests/test_protocol.py` asserts server + client `protocol.py` are byte-identical (PY-6 invariant). `tests/test_api_contract.py` pins per-endpoint request/response shapes. Neither simulates a worker at `PROTOCOL_VERSION = N` connecting to a server at `N+1` or vice versa. PROTOCOL_VERSION gating is on every request, but the test that would catch "we broke compat without bumping PROTOCOL_VERSION" doesn't exist.

**Fix direction** — pin one old `protocol.py` under `tests/fixtures/protocol_v{N-1}.py` and have a test instantiate a worker-shaped client from it against the current server. Asserts: graceful ProtocolError-with-mismatch rather than undefined-field crashes.

---

## Most-likely-to-regress areas for 1.6.2 (forward-looking)

Prioritised by recency × complexity × test-coverage-gap:

1. **AppArmor tightening follow-up** (when SS.1 moves from permissive to narrow). #3 above is the gap.
2. **Anything touching `build_name_to_target_map` / `_address_overrides` / `_encryption_keys` producers or consumers.** Two ships of the same bug class. The invariant in #4 above is the only durable fix.
3. **New HA integration platforms or entity types.** PARALLEL_UPDATES gap + no real lifecycle test means any new platform ships with the same class of lifecycle bug.
4. **Config-flow edits.** QS.4/QS.5 added reauth + reconfigure paths this cycle, and the reconfigure review flagged three issues (dead-code fallback, context KeyError, AssertionError) — all of which would have been caught by a real-flow test (#9 above).
5. **Firmware budget + orphan reconciler under disk pressure.** Real prod data grows, home-lab disk caps hit, reconciler runs. Not stress-tested (#8 above).
6. **ESPHome version bumps beyond `2026.3.2`.** The pinned CI axis is the only compile-test gate; anything new ESPHome introduces (e.g. the "2026.4.0 reshaped the API" event from 1.5) lands as a prod surprise (#10 above).

---

## Mechanical test-tooling gaps

| Gap | Impact | Fix |
|---|---|---|
| No `quality_scale.yaml` | Silver claim unverified | Ship the file; hassfest enforces the rest. |
| PY-10 invariant passes with 100% skipped tests | False-positive on the filename convention | PY-10b: grep `@pytest.mark.skip` in `test_integration_*.py`-non-`_logic` files — fail if ratio > 0.5. |
| No stress-test coverage anywhere | Race conditions surface in prod | One `tests/test_stress.py` file with 5-10 targeted stress scenarios (git commit race, firmware upload race, config rescan race). |
| `compile-test.yml` single ESPHome version | Upstream regressions land in prod | Matrix on {pinned, latest_stable}. |
| `push-to-hass-4.sh` is the only Dockerfile integration test | Dockerfile breakage lands on main | Add `build.yml` workflow that does `docker buildx build` on PR. |
| No `test_mdns_advertiser.py` | New module has 0% unit coverage | Add the file (#5 above). |
| No protocol-version mismatch test | PY-6 invariant is the only guard | Pinned-old-fixture test (#13 above). |
| `check-invariants.sh` has no "consumer of \<producer>" rule | Class-of-bug #4 can ship symptom #3 | New rule scanning for `_address_overrides` / `_encryption_keys` / `_name_map` readers and cross-checking reseed wire-up. |

---

## Recommended 1.6.2 test-work, in order

1. **IT.2 unskip** — land real-hass lifecycle test. Everything else downstream depends on it.
2. **`quality_scale.yaml` + PARALLEL_UPDATES fixes** — close the silver claim gap before it rots.
3. **Reseed-consumer invariant (check-invariants.sh rule)** — durably close the #11/#18 bug class.
4. **Static-IP fixture suite + `e2e-hass-4/static-ip-ota.spec.ts`** — the deferred-in-#18 work is where the next regression lives.
5. **`test_mdns_advertiser.py` + `test_connect_worker_modal` docker-run snapshot** — cheap, closes two known-broken paths.
6. **AppArmor CI smoke workflow** — unblocks SS.1 tightening safely.
7. **One stress test** (git commit races OR firmware upload races) — build the pattern; more can follow.
8. **Protocol mismatch fixture** — one test; catches the next PY-6 slip.

Everything else can queue against `WORKITEMS-future.md` under a "Test hardening" section.

---

## Non-goals

- Coverage percentages. The existing suite is substantial; adding uniform coverage to every module dilutes attention from the class-of-bug shapes above. Aim for *quality* of coverage (does the test catch the bug it's named after?) not quantity.
- "Comprehensive" integration tests that try to exercise every HA platform. Start with setup/unload/reload; extend as specific lifecycle bugs surface.
- Real-hass `e2e-hass-4/` growth beyond ~20 tests. The suite's value is end-to-end smoke, not exhaustive coverage — every added test here adds minutes to every push. Cap + prune.
