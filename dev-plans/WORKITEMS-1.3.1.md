# Work Items — 1.3.1 (hardening point release)

Theme: **Harden for 1.4.** A targeted hardening pass between 1.3 and 1.4. No new user features. Goal: close the highest-leverage regression blindspots, fragility hazards, and CLAUDE.md gaps surfaced by the post-1.3 audit, so 1.4's feature work (device create, firmware download, web serial, thread/IPv6, AI editor) lands on a foundation that catches breakage in CI instead of in production.

The audit's findings, in priority order:

1. **Server↔worker protocol is untyped dicts.** Magic-string keys crossing a network boundary. 1.4 will add new job fields; a typo will silently break deployed workers. Highest leverage.
2. **Scary code paths have no safety net.** `main.py` background loops, `version_manager.py` concurrency, OTA retry path, auth middleware edge cases, LIB.0 image-version branches, queue persistence corruption.
3. **Footguns waiting to fire.** Unlocked client globals, peer-IP auth trust, log-cap-after-append, silent options.json fallback, three CLAUDE.md violations already in the UI code.
4. **CLAUDE.md is mostly accurate but mixes enforceable invariants with aspirational guidance, has gaps the bug history proves we need, and is ~30% trimmable.**

## Workstream A — Typed contracts at the server↔worker seam

- [ ] **A.1 Define protocol message types** — `ha-addon/server/protocol.py` (or shared module): `RegisterRequest/Response`, `HeartbeatRequest/Response`, `JobAssignment`, `JobResultSubmission`, `SystemInfo`. Use stdlib `dataclasses` + `TypedDict` (no new deps) unless pydantic is explicitly approved.
- [ ] **A.2 Add `protocol_version: int` field** to register + heartbeat, separate from `image_version`. Server logs and rejects unknown protocol versions cleanly with a structured error response (not a half-processed payload).
- [ ] **A.3 Server-side validation on receive** — every worker-facing endpoint in `api.py` decodes the request body into the typed message and rejects malformed payloads with a 400 + reason.
- [ ] **A.4 Client-side validation on receive** — `client.py` validates job assignments before extracting the bundle. Builds typed result submissions instead of inline `{"success": ..., "log": ...}` dicts.
- [ ] **A.5 Round-trip + compatibility tests** — one test per message type, plus explicit "old worker missing field" and "new worker extra field" cases for both directions.

## Workstream B — Targeted tests for the scary paths

Not "raise coverage to 80%." Pick the places where a silent break is catastrophic.

- [ ] **B.1 `version_manager.py` concurrency stress test** — 10 threads call `ensure_version("2026.3.3")` simultaneously; assert venv created exactly once, no deadlock, LRU consistent. Second test: fill LRU while another thread holds the oldest entry, verify `keep_version` honored.
- [ ] **B.2 `main.py` auth middleware edge cases** — peer IP `None`, IPv6 supervisor, plausible spoof (`172.30.32.3`), Supervisor token present but wrong, missing headers entirely. Use `aiohttp.test_utils` with a real transport.
- [ ] **B.3 `main.py` timeout_checker tests** — frozen-clock test of (a) ASSIGNED job past `JOB_TIMEOUT` → PENDING + retry_count++, (b) retries exhausted → FAILED, (c) heartbeat during timeout window cancels the timeout.
- [ ] **B.4 `client.py` OTA retry regression test** — mock `subprocess.Popen`: compile success, upload fail, retry. Assert retry uses `esphome upload` (not `run`), assert `--no-logs` is NOT in the upload arg list. Direct regression test for #177.
- [ ] **B.5 `api.py` LIB.0 image-version parametrized test** — `image_version` ∈ `{None, "", "1", "2", "3", "garbage"}`, assert heartbeat + register response per case, including `image_upgrade_required` branch.
- [ ] **B.6 `job_queue.py` persistence corruption tests** — load a malformed `queue.json`: assert we log ERROR (not silently drop) and start with empty queue. Same for a partial/truncated file.

## Workstream C — Fragility fixes

- [ ] **C.1 Lock client globals** — `_active_jobs`, `_selected_esphome_version`, component cache in `client.py`. Single `threading.Lock` (or convert counters to atomic primitives). Add a test that simulates a heartbeat arriving mid-`run_job()`.
- [ ] **C.2 Harden `auth_middleware`** — `main.py:51–84`: normalize IPv6 supervisor addr, handle `peername=None`, log refusal reason on every 401 (currently silent — useless for diagnostics).
- [ ] **C.3 Cap log append BEFORE append** in `job_queue.append_log()` so a single huge line can't transiently blow memory before truncation fires.
- [ ] **C.4 `app_config.py` fail-loud** — log every missing-key fallback and every unknown key at startup. Don't silently swallow malformed `options.json`.
- [ ] **C.5 Fix three CLAUDE.md violations in the UI (pre-rewrite)**:
  - Move `https://schema.esphome.io/` `fetch()` out of `EditorModal.tsx` into `api/client.ts` (or new `api/esphomeSchema.ts`).
  - Replace hand-rolled `<input>`/`<select>` in `ConnectWorkerModal.tsx` with shadcn `Input`/`Select`.
  - Remove inline `style={{ padding: 18 }}` in `ConnectWorkerModal.tsx`.
- [ ] **C.6 Playwright contract fixtures** — `ha-addon/ui/e2e/fixtures.ts`: derive mock shapes from the actual TS types in `api/client.ts` so a field rename breaks tests. Add the missing job states (`pending`, `timed_out`) to the fixtures so the queue tab is exercised on the full state space.

## Workstream D — CLAUDE.md rewrite (this is QG.1)

Do this **last**, after A–C land, so the file reflects reality.

- [ ] **D.1 Trim ~30%** — collapse the verbose Commands and Branching & Release sections to one-line pointers (`scripts/`, `dev-plans/RELEASE_CHECKLIST.md`). Delete the Frontend Stack blurb that duplicates Design Principles.
- [ ] **D.2 Split rules into two explicit sections**:
  - **Enforced invariants** (grep/lint/test checkable): no `fetch()` outside `api/client.ts`; no `@apply`; no `any` in new code; all subprocess invocations log their full command line first; YAML parsed with `yaml.safe_load`, never regex; no `flex` on `<td>`; worker Docker image changes require `IMAGE_VERSION` bump.
  - **Design judgment** (aspirational): UX walkthrough, semantic HTML, composition over override. Marked clearly as guidance, not enforced.
- [ ] **D.3 Add missing rules from bug history**:
  - Subprocess command logging (#176/#177/#180)
  - YAML parsing safety: `yaml.safe_load`, never regex (#160)
  - Viewport boundary detection for popovers/menus (#161/#164)
  - Device name normalization (hyphen ↔ underscore) (#159)
  - `esphome run` accepts `--no-logs`; `esphome upload` does NOT (#177)
- [ ] **D.4 Clarify Project Tracking** — define "turn" for `bump-dev.sh`, state explicitly that bug numbers are global/monotonic across releases, state when to create the next `WORKITEMS-X.Y+1.md`.
- [ ] **D.5 `scripts/check-invariants.sh`** — small grep-based linter for the enforced invariants. Wire into the CI `ruff` job. This is what makes Enforced Invariants actually enforced — without it, D.2 decays.

## Open Bugs

(none yet — this release starts clean)

---

## Open questions before starting

1. **pydantic vs stdlib for Workstream A** — pydantic gives better validation + clearer errors, but adds a server-side dep. Stdlib `TypedDict`+`dataclass` is zero-dep but enforcement is weaker. Default: stdlib unless explicitly approved.
2. **Scope check** — is this the right scope for a point release, or should some workstreams (especially A) wait for 1.4 proper? Current recommendation: A, B, C land in 1.3.1; D lands at the very end as the capstone.
