# Security Audit: ESPHome Distributed Build Server

**Date:** 2026-03-29
**Version audited:** 0.0.21
**Scope:** Server add-on (`ha-addon/server/`), Dockerfile, `run.sh`, `config.yaml`, and the bundled worker (`client/client.py`) as it interacts with the server security model.

---

## Executive Summary

The ESPHome Distributed Build Server is a Home Assistant add-on that coordinates remote firmware compilation. Its threat model is deliberately relaxed: it runs on a trusted home network, behind Home Assistant's ingress authentication for the browser UI, and uses a shared secret token for build workers. Within that context, the implementation is generally sound — the code is clean, intentional, and most of the obvious risks are already mitigated.

However, several meaningful security issues remain. The most significant are:

1. **The server token is transmitted to any browser that opens the UI** (HIGH). The `/ui/api/server-info` endpoint returns the raw auth token, which is then embedded in the "Connect Worker" docker command shown to the user. This deliberately exposes the credential to the browser, but it also means any network observer or compromised browser extension obtains a fully working API credential.

2. **The worker auto-update mechanism executes arbitrary code delivered by the server** (HIGH). Build workers automatically download Python source files from the server and replace their own code on disk, then exec themselves. A server compromise — or a man-in-the-middle against plaintext HTTP — results in arbitrary code execution on every connected build machine.

3. **The UI API has no authentication** (MEDIUM in context, would be HIGH outside HA). All `/ui/api/*` endpoints rely entirely on HA Ingress to enforce authentication. If the add-on port (8765) is reachable directly without going through HA, anyone can enqueue builds, read logs (including secrets), edit YAML configs, and remove workers with no credentials at all.

4. **`secrets.yaml` is included in every build bundle** sent to workers (MEDIUM). Every build worker receives a full tarball of the ESPHome config directory, including `secrets.yaml`, which typically contains Wi-Fi passwords, API keys, and OTA passwords.

5. **Unbounded queue growth** enables denial of service (LOW/MEDIUM) from any authenticated worker.

The findings below are detailed with affected code locations and concrete recommendations.

---

## Risk Rating Scale

| Rating   | Meaning |
|----------|---------|
| Critical | Can be exploited to compromise the host system or HA instance without any credentials |
| High     | Significant impact, exploitable by a network-adjacent attacker or with minimal access |
| Medium   | Real impact but requires either local access, existing credentials, or a specific attack chain |
| Low      | Minor hardening issues or defence-in-depth gaps |
| Info     | Observations and best-practice notes with negligible direct risk |

---

## Findings

### F-01 — Auth Token Exposed to Browser via `/ui/api/server-info`

**Severity:** HIGH

**Description:**

`ui_api.py` line 32 returns `cfg.token` directly in the JSON response to the browser:

```python
return web.json_response({
    "token": cfg.token,
    "port": cfg.port,
    ...
})
```

The browser uses this to render a pre-filled `docker run` command in the "Connect Worker" modal. This is convenient UX, but the consequence is that:

- The raw Bearer token is stored in JavaScript memory and accessible to any script running in the same browser origin.
- Any browser extension with broad permissions, XSS injection, or JavaScript console access can read the token.
- The token is also readable by any browser developer who opens DevTools → Network while the UI is open.
- The token is transmitted over plaintext HTTP from the add-on to the browser (see F-05).

The token grants full access to all `/api/v1/*` endpoints: register workers, claim jobs, submit results, and read build logs.

**Affected code:** `ui_api.py:32` (`get_server_info`), `static/index.html:706-714` (`renderDockerCmd`)

**Recommended fix:**

Do not return the full token to the browser. Instead, serve the docker command server-side (as a pre-rendered string), masking everything except the last 4 characters for visual confirmation. Alternatively, provide a dedicated "copy token" flow that requires a deliberate user action and does not store the token in global JavaScript state. At minimum, consider returning only a token prefix for display purposes.

---

### F-02 — Worker Auto-Update Executes Arbitrary Python Code from Server

**Severity:** HIGH

**Description:**

`client/client.py` lines 495–516 implement an auto-update mechanism. When the server reports a newer worker version, the worker downloads all `.py` files from `/api/v1/client/code` and writes them directly over its own source files, then calls `os.execv` to restart itself:

```python
for filename, content in files.items():
    if not filename.endswith(".py"):
        continue
    target = (client_dir / filename).resolve()
    if target.parent != client_dir:
        logger.warning("Skipping suspicious path in update: %s", filename)
        continue
    target.write_text(content, encoding="utf-8")
```

The path check (`target.parent != client_dir`) prevents writing outside the client directory, which is a correct safeguard. However, the content written is unchecked Python source that will execute with the client process's full privileges as soon as `os.execv` is called.

This means:

- If the server is compromised, every connected build worker immediately executes attacker-controlled code.
- If the HTTP connection is intercepted (the transport is plaintext HTTP — see F-05), a MitM attacker can inject arbitrary code.
- There is no signature verification, checksum, or integrity check of any kind on the downloaded files.
- The version check is purely a string comparison (`sv != CLIENT_VERSION`); the server controls both the version string and the code.

Additionally, `api.py` lines 237–252 (`get_client_code`) simply globs `*.py` files from `/app/client/` and returns them verbatim. There is no manifest, no signing key, and no way for the worker to distinguish a legitimate update from a tampered one.

**Affected code:** `client/client.py:480-518` (`_apply_update`), `api.py:237-253` (`get_client_code`)

**Recommended fix:**

The safest fix is to remove the auto-update mechanism entirely and rely on Docker image updates. If auto-update is retained, the server should sign the code bundle (e.g., with a private key stored in `/data/`), and the worker should verify the signature before writing any files. At minimum, add a SHA-256 hash of the bundle to the server response and verify it worker-side. The hash alone does not prevent a MitM attack over HTTP, but combined with HTTPS it provides meaningful integrity.

---

### F-03 — UI API Has No Authentication; Relies Entirely on HA Ingress

**Severity:** MEDIUM (HIGH if port 8765 is directly reachable)

**Description:**

All `/ui/api/*` endpoints are unconditionally allowed by the auth middleware in `main.py` lines 37-38:

```python
if path.startswith("/ui/api/") or path in ("/", "/index.html"):
    return await handler(request)
```

No token, session, or credential check of any kind is performed. This is acceptable when HA Ingress is the only path to those endpoints. However, the add-on also exposes port 8765 directly to the host network (`config.yaml` lines 18-19: `ports: 8765/tcp: 8765`).

If any of the following is true, the UI API is fully open to the LAN:

- The user has not configured a firewall rule blocking port 8765.
- The user accesses the UI via the direct port rather than through HA Ingress.
- Another device on the LAN makes a direct HTTP request to the HA host on port 8765.

Through the unauthenticated UI API, an attacker on the LAN can:

- Enqueue compile jobs for any configured ESPHome target (`POST /ui/api/compile`).
- Read full build logs, which may contain device credentials in error output (`GET /ui/api/queue`).
- Read and **write** any `.yaml` config file in the ESPHome config directory (`GET/POST /ui/api/targets/{filename}/content`).
- Read device IP addresses, firmware versions, and other device metadata.
- Remove or disable build workers.

**Affected code:** `main.py:37-38`, `ui_api.py` (all endpoints), `config.yaml:18-19`

**Recommended fix:**

Add a secondary auth check to the UI API that validates the `X-Ingress-Path` or `X-Supervisor-Token` header (both injected by HA Ingress and absent on direct connections). Alternatively, bind the server to `127.0.0.1` only for the ingress path, and use a separate port with token auth for direct client access. At minimum, document the exposure clearly and recommend a firewall rule.

---

### F-04 — `secrets.yaml` Included in Every Build Bundle Sent to Workers

**Severity:** MEDIUM

**Description:**

`scanner.py` lines 37-55 (`create_bundle`) tarballs the entire ESPHome config directory recursively and sends it to build workers as a base64-encoded payload in the job response:

```python
for path in sorted(base.rglob("*")):
    if not path.is_file():
        continue
    arcname = str(path.relative_to(base))
    tar.add(str(path), arcname=arcname)
```

`secrets.yaml` is intentionally excluded from the list of *compile targets* (`scan_configs` line 30), but it is explicitly included in the bundle because ESPHome's `!secret` directive requires it at compile time. The CLAUDE.md documentation acknowledges this.

The consequence is that every authenticated build worker receives a copy of `secrets.yaml` on every job, whether or not the specific target being compiled uses any secrets. `secrets.yaml` in a typical ESPHome installation contains Wi-Fi SSIDs and passwords, API encryption keys, OTA passwords, and MQTT credentials.

While build workers are authenticated and presumably trusted machines, this increases the blast radius of a compromised worker and unnecessarily distributes sensitive credentials to all build workers.

**Affected code:** `scanner.py:37-55` (`create_bundle`)

**Recommended fix:**

Parse the target YAML (ESPHome already has a resolver for this — `_resolve_esphome_config` in scanner.py does it) and identify which secrets are actually referenced by the specific target. Deliver only those secrets, or better, perform secret substitution server-side before bundling, so no `secrets.yaml` needs to leave the server at all. If server-side substitution is not feasible, at minimum document the exposure in the add-on description so operators understand what data leaves the HA host.

---

### F-05 — All Worker-Server Communication Is Plaintext HTTP

**Severity:** MEDIUM

**Description:**

Build workers connect to the server over `http://` (plaintext). The server URL is generated in the UI's docker command (`static/index.html:713`):

```javascript
const serverUrl = `http://${host}:${port}`;
```

For build workers connecting across a LAN, all of the following are transmitted in cleartext:

- The Bearer auth token (on every request).
- The full ESPHome config bundle including `secrets.yaml` (F-04), sent per job.
- Build logs which may contain device credentials in error output.
- The worker auto-update code (see F-02 — MitM can inject arbitrary Python).

On most home networks, this risk is low in practice, but it is a meaningful concern in environments where the HA host and the build workers are on separate network segments (e.g., a remote builder in a different physical location).

**Affected code:** `static/index.html:713`, `run.sh:24`, `client/client.py:261-264` (HEADERS)

**Recommended fix:**

Support HTTPS for the server. For a home network add-on, the most practical option is to allow the user to configure an existing reverse proxy (Nginx Proxy Manager, Traefik) in front of port 8765 and document that as the recommended path for remote clients. Add a configuration option `require_https: bool` that logs a warning if remote clients connect over HTTP.

---

### F-06 — Supervisor IP Bypass Allows Unauthenticated API Access from HA Supervisor

**Severity:** LOW (info for the deployment model; design decision to document)

**Description:**

`main.py` lines 47-48 and `api.py` lines 45-46 unconditionally trust any request originating from `172.30.32.2`:

```python
if peer_ip == "172.30.32.2":
    return await handler(request)
```

This is the HA Supervisor's internal address, and the intent is to allow the supervisor to call the worker API without needing a token. The trust is based solely on the source IP, which is not spoofable from outside the Docker network in a normal HA installation.

However, this means any process on the same Docker network as the add-on (including other HA add-ons that may be compromised) can make unauthenticated requests to all `/api/v1/*` endpoints, including job manipulation, worker registration, and log retrieval.

The IP is also hardcoded as a string literal in two places; if the Supervisor's IP ever changes, the bypass silently stops working with no diagnostic.

**Affected code:** `main.py:47-48`, `api.py:45-46`

**Recommended fix:**

Consider whether the Supervisor actually needs to call `/api/v1/*` endpoints at all. If not, remove the bypass entirely. If yes, prefer HA's `SUPERVISOR_TOKEN` header (`X-Supervisor-Token`) over IP-based trust, as it is a proper credential rather than a network address. Define the IP as a named constant or config value rather than a bare string literal.

---

### F-07 — No Rate Limiting or Queue Size Cap

**Severity:** LOW

**Description:**

Any authenticated worker (or a UI user, who is unauthenticated — see F-03) can enqueue jobs without any rate limit or maximum queue depth. The `JobQueue.enqueue` method deduplicates by target (one active job per target), which provides meaningful protection against trivial queue flooding for known targets. However:

- A worker with the token can rapidly submit result payloads with arbitrarily large log strings. The `log` field is stored in memory and persisted to `/data/queue.json` with no size cap.
- The `/ui/api/retry` endpoint can be called repeatedly to re-enqueue failed jobs, creating a cycle with no backoff.
- The queue file path is hardcoded to `/data/queue.json`. If `/data` is on the same filesystem as the HA OS, a malicious or buggy worker submitting huge logs could potentially exhaust disk space.

**Affected code:** `job_queue.py:166-216` (`enqueue`), `api.py:177-207` (`submit_job_result`)

**Recommended fix:**

Add a maximum log length (e.g., 512 KB) when accepting job results. Add a maximum total queue size (e.g., 500 jobs). Consider a rate limit on the retry endpoint.

---

### F-08 — Job ID Is Not Validated Against the Claiming Worker

**Severity:** LOW

**Description:**

`api.py` lines 177-207 (`submit_job_result`) accepts a result from any authenticated worker for any job ID, regardless of whether that worker was assigned the job:

```python
job_id = request.match_info["id"]
...
ok = await queue.submit_result(job_id, status, log, ota_result)
```

The `queue.submit_result` method does check that the job is in `WORKING` state, but it does not verify that the submitting worker is the one assigned to the job (`job.assigned_client_id`). This means:

- Worker A can submit a failure result for a job that was assigned to Worker B, causing the job to be marked failed even though Worker B is still working on it.
- A malicious or buggy worker can poison job results for other workers' work.

The same issue applies to `update_job_status` (`/api/v1/jobs/{id}/status`): any authenticated worker can update the status text of any job.

**Affected code:** `api.py:177-207` (`submit_job_result`), `api.py:210-226` (`update_job_status`), `job_queue.py:259-299` (`submit_result`)

**Recommended fix:**

Pass the submitting `client_id` (from the authentication context, not from the request body) to `queue.submit_result` and `queue.update_status`, and reject submissions where `client_id != job.assigned_client_id`.

---

### F-09 — Path Traversal Check Uses `resolve()` on a Non-Existent Path

**Severity:** LOW

**Description:**

`ui_api.py` lines 213-218 and 233-238 guard against path traversal using `Path.resolve()` before the file exists:

```python
path = (config_dir / filename).resolve()
try:
    path.relative_to(config_dir.resolve())
except ValueError:
    return web.json_response({"error": "Invalid filename"}, status=400)
```

`Path.resolve()` on a non-existent path behaves differently across Python versions. On Python 3.5 and earlier, it raises `FileNotFoundError` for non-existent paths; on Python 3.6+, it resolves the path purely lexically if `strict=False` (the default). On Python 3.6+, this check is correct for preventing `../` traversal because lexical resolution handles `..` components.

However, the check does not defend against symlinks: if the ESPHome config directory contains a symlink that points outside the directory, `resolve()` will follow the symlink and the `relative_to` check will fail (raising `ValueError`), so the file would be rejected — this is the correct behavior. **But** for the write endpoint (`save_target_content`), the check only guards the *path*; it does not prevent writing a YAML file that itself contains `!include` directives pointing to files outside the config directory. This is then processed by `_resolve_esphome_config` via ESPHome's own YAML resolver.

**Affected code:** `ui_api.py:213-218`, `ui_api.py:233-238`

**Recommended fix:**

The existing check is adequate for the file read/write operations themselves. Consider adding `strict=True` to the `resolve()` call on the read path (where the file must exist) to make the intent explicit and catch edge cases. Document that the ESPHome YAML `!include` attack surface is inherited from ESPHome's own resolver, not this server.

---

### F-10 — Monaco Editor Loaded from Unpinned CDN

**Severity:** LOW

**Description:**

`static/index.html` lines 1345-1348 load the Monaco editor from `unpkg.com`:

```javascript
script.src = 'https://unpkg.com/monaco-editor@0.44.0/min/vs/loader.js';
require.config({ paths: { vs: 'https://unpkg.com/monaco-editor@0.44.0/min/vs' } });
```

The version `0.44.0` is pinned, which is good. However, `unpkg.com` is a third-party CDN with no SRI (Subresource Integrity) hash on the script tag. If `unpkg.com` is compromised, or if an attacker can intercept the HTTP request to it (the UI itself is served over plaintext — see F-05), they can inject arbitrary JavaScript into the admin UI. This would give them access to the token stored in `serverInfo.token` (see F-01).

The ESPHome logo is also loaded from `https://media.esphome.io/` and the favicon from `https://esphome.io/`, expanding the external script/resource surface.

**Affected code:** `static/index.html:1345-1348`

**Recommended fix:**

Add `integrity="sha384-..."` SRI attributes to the Monaco script tag. Better, bundle Monaco into the Docker image and serve it as a static file, eliminating the external CDN dependency entirely. This also makes the UI work in offline/air-gapped HA installations.

---

### F-11 — Build Log Content Stored Unredacted

**Severity:** LOW

**Description:**

`api.py` lines 189, 203 accept and store the `log` field from clients without any filtering or size limit. Build logs from ESPHome compilation frequently contain:

- Wi-Fi SSID and password (when a compile error includes the full config in the traceback).
- OTA password.
- API encryption key.
- Any value substituted from `secrets.yaml` via ESPHome's substitution system.

These logs are returned verbatim to the browser UI via `/ui/api/queue`, accessible without authentication (see F-03).

**Affected code:** `api.py:189,203`, `job_queue.py:66-87` (`to_dict`), `ui_api.py:94-99` (`get_queue`)

**Recommended fix:**

Consider scrubbing known-sensitive patterns from build logs before storage (e.g., lines containing `password:`, `key:`, `ssid:` where the value appears to be a secret). This is imperfect but reduces accidental exposure. More robustly, restrict the queue/log API to authenticated access even in the UI tier.

---

### F-12 — Dependency Versions Not Pinned

**Severity:** LOW

**Description:**

`ha-addon/server/requirements.txt` uses minimum-version constraints only (`>=`):

```
aiohttp>=3.9
aioesphomeapi>=18.0
zeroconf>=0.131
pyyaml>=6.0
esphome>=2024.1.0
requests>=2.31
```

This means each Docker image build resolves the latest compatible versions of all dependencies at build time. A supply-chain compromise of any upstream package that releases a new version compatible with the `>=` constraint will be automatically included in the next image build.

`client/requirements.txt` has a single line `requests>=2.31`, making the client even more exposed.

**Affected code:** `ha-addon/server/requirements.txt`, `client/requirements.txt`

**Recommended fix:**

Use exact pins (`==`) or a lock file (`pip-compile` / `pip freeze > requirements.lock`) for production builds. For a home add-on where update cadence is important, exact pins with a dependabot or Renovate bot to create PRs for upgrades is a reasonable middle ground. At minimum, pin the major and minor version (`~=3.9` in pip syntax allows patch updates only).

---

### F-13 — Docker Image Uses `$BUILD_FROM` Without Pinned Base

**Severity:** LOW

**Description:**

`ha-addon/Dockerfile` uses `ARG BUILD_FROM` without a default, meaning the base image is determined entirely by the HA add-on build system. The HA base images are generally well-maintained, but the Dockerfile itself has no mechanism to verify the provenance or integrity of the base image. Combined with unpinned Python dependencies, the image's dependency graph is fully determined at build time by external parties.

**Affected code:** `ha-addon/Dockerfile:1-2`

**Recommended fix:**

For builds you control directly, pin the `BUILD_FROM` to a specific digest (`FROM ghcr.io/home-assistant/...:sha256-...`). For HA add-on builds, this is partially constrained by the HA add-on build infrastructure, but documenting the trust assumption is worthwhile.

---

### F-14 — `run.sh` Reads Auth Token from Plaintext File with No Permission Check

**Severity:** Info

**Description:**

`run.sh` lines 7-10 read the auth token from `/data/auth_token` using a polling loop:

```bash
TOKEN=$(cat /data/auth_token 2>/dev/null || echo "")
```

The file is created by `app_config.py` line 36 with no explicit mode — it inherits the process umask. Inside the Docker container, this is acceptable, but there is no verification that the file has restricted permissions (e.g., `0600`). If the `/data` volume is mounted with world-readable permissions on the host, the token is readable by any process on the host with access to the volume.

**Affected code:** `run.sh:7-10`, `app_config.py:36` (`TOKEN_FILE.write_text`)

**Recommended fix:**

Write the token file with explicit mode `0600`:
```python
TOKEN_FILE.write_bytes(token.encode())
TOKEN_FILE.chmod(0o600)
```

---

### F-15 — `X-Ingress-Path` Header Injected Into HTML Without Sanitization

**Severity:** Info

**Description:**

`main.py` lines 118-123 inject the `X-Ingress-Path` header value into the HTML response using a simple string replace:

```python
html = html.replace(
    '<base href="./">',
    f'<base href="{ingress_path}">',
)
```

`X-Ingress-Path` is set by the HA Supervisor and should be a trusted value. In the HA ingress flow, this header cannot be set by untrusted clients. However, if the add-on is ever accessed via a path where the header could be influenced by a user (e.g., a misconfigured proxy), an attacker could inject arbitrary HTML attributes or break out of the `href` attribute. The Supervisor IP bypass on the API tier (`main.py:47`) does not apply here since this is a GET request to `/` or `/index.html`, which bypasses auth entirely.

**Affected code:** `main.py:116-124`

**Recommended fix:**

Sanitize `ingress_path` to contain only URL-safe characters (path segments, slashes) before injecting it into HTML. A simple regex `re.sub(r'[^/a-zA-Z0-9._-]', '', ingress_path)` is sufficient.

---

### F-16 — Registry Is Not Persistent; Worker State Lost on Server Restart

**Severity:** Info

**Description:**

`registry.py` is explicitly documented as "in-memory, no persistence needed." On server restart, all registered workers disappear. Combined with the job queue restart recovery (which resets `WORKING` jobs to `PENDING`), this is handled correctly. However, it means a worker that was mid-job when the server restarted will eventually time out and retry — which is correct behavior — but the `assigned_hostname` on restarted jobs is lost until the worker re-registers and re-claims.

This is an operational observation, not a security issue. It is noted here because the `to_dict` output for jobs includes `assigned_client_id` (a UUID) even after the worker has gone; the UI correctly falls back to `assigned_hostname` for display, but downstream tooling consuming the API should be aware.

**Affected code:** `registry.py`, `job_queue.py:53` (`assigned_hostname` field)

---

## Positive Findings

The following aspects of the implementation are done well and worth noting explicitly.

**Token generation with `secrets.token_hex`:** `app_config.py` uses `secrets.token_hex(16)` to generate the auth token when none is configured. This is cryptographically strong and correct.

**Atomic file writes for persistence:** Both `job_queue.py` (`_persist`) and `device_poller.py` (`_save_cache`) write to a `.tmp` file and atomically rename it to the final path. This prevents partial writes from corrupting the persisted state.

**Path traversal protection on file endpoints:** `ui_api.py` correctly uses `Path.resolve()` + `relative_to()` to guard the config file read and write endpoints against directory traversal attacks. The check is in the right place and uses the right primitive.

**Log endpoint uses `textContent`, not `innerHTML`:** The log modal in `static/index.html` line 1050 assigns build log content via `textContent`, which is safe against XSS. All other user-supplied strings are passed through `escapeHtml()` before being placed in innerHTML.

**Deduplication prevents queue flooding per-target:** `JobQueue.enqueue` refuses to add a second active job for the same target, preventing trivial queue amplification via repeated compile requests for the same device.

**ESPHome YAML resolution uses ESPHome's own pipeline:** `scanner.py` uses ESPHome's internal `load_yaml` + `do_packages_pass` + `do_substitution_pass` chain rather than a hand-rolled YAML parser. This means `!include`, `packages:`, and `${substitutions}` are all handled consistently with ESPHome's own behavior, reducing divergence bugs.

**Worker path validation on auto-update:** `client/client.py` line 509 checks that the target path's parent matches the worker directory before writing update files, preventing the server from writing to arbitrary locations via path injection in the filename.

**Heartbeat-based liveness detection:** The registry uses a configurable `worker_offline_threshold` to determine worker online status rather than a hard-coded magic number, and it is applied consistently in both the API and the UI.

**`tarfile.extractall` uses `filter="data"`:** `client/client.py` line 468 passes `filter="data"` to `extractall`, which is the Python 3.12 recommended way to prevent tar extraction from setting dangerous file permissions or overwriting absolute paths. This is a correct and modern usage.

---

## Summary Table

Status legend: **FIXED** (resolved, release noted) · **PARTIAL** (partially mitigated in the release noted; residual risk remains) · **OPEN** (still live, planned to fix) · **WONTFIX** (accepted risk by design for the HA add-on threat model) · **INFO** (observation, no action planned).

Status as of 1.3.0 release (last reviewed 2026-04-08 against current code).

| ID   | Finding                                              | Severity | Status | Notes |
|------|------------------------------------------------------|----------|--------|-------|
| F-01 | Auth token exposed to browser via server-info API    | High     | WONTFIX | Required for the Connect Worker modal's `docker run` command UX. Risk accepted: the token lives behind HA Ingress authentication, same trust boundary as the rest of HA. |
| F-02 | Worker auto-update executes arbitrary server code    | High     | PARTIAL (1.3.0) | LIB.0/LIB.1 added `IMAGE_VERSION` / `MIN_IMAGE_VERSION` gating so the server refuses source-code auto-updates to workers running a stale Docker image. The arbitrary-code path itself remains; no signature verification. Full fix (signing or removal) tracked for a future release. |
| F-03 | UI API unauthenticated if port 8765 is directly accessible | Medium | WONTFIX | By design — HA Ingress is the only intended access path. Documented in README. |
| F-04 | `secrets.yaml` included in every build bundle        | Medium   | WONTFIX | Required for ESPHome's `!secret` resolution on the worker. Workers are authenticated and trusted machines in the stated threat model. |
| F-05 | Worker-server communication is plaintext HTTP        | Medium   | WONTFIX | By design for the home-network threat model. Users with remote workers across segments can front the server with their own reverse proxy (documented). |
| F-06 | Supervisor IP bypass grants unauthenticated API access | Low    | PARTIAL (1.3.0) | PY.4 moved the hardcoded `172.30.32.2` into `constants.HA_SUPERVISOR_IP`. The bypass itself (IP-based trust) remains. Workstream C.2 in WORKITEMS-1.3.1 will normalize IPv6 supervisor addrs and log refusal reasons. |
| F-07 | No rate limiting or queue size cap                   | Low      | PARTIAL (1.3.0) | SEC.2 capped streaming logs at 512 KB per job. SEC.3 clamped `max_parallel_jobs` on worker registration (0–32). Queue-size cap and retry rate limit not yet added. |
| F-08 | Job results not validated against the claiming worker | Low     | OPEN | Still unverified. Candidate for 1.3.1 Workstream B. |
| F-09 | Path traversal check correct but worth hardening     | Low      | FIXED (1.3.0) | PY.1 introduced `helpers.safe_resolve()` and every UI API file endpoint now uses it. |
| F-10 | Monaco editor loaded from unpinned CDN (no SRI)      | Low      | FIXED (1.1.0) | React UI rewrite bundles `monaco-editor` + `@monaco-editor/react` via Vite. No external CDN. |
| F-11 | Build log content stored unredacted                  | Low      | WONTFIX | Build logs are inherently needed for debugging; scrubbing is imperfect. Mitigated by the F-07 size cap and by the fact that the log API lives behind HA Ingress (see F-03). |
| F-12 | Dependency versions not pinned                       | Low      | OPEN | `requirements.txt` still uses `>=`. Needs a lockfile or exact pins plus a dependabot/renovate flow. Candidate for 1.3.1. |
| F-13 | Docker base image not pinned to a digest             | Low      | WONTFIX | HA add-on build infrastructure controls `BUILD_FROM`; pinning a digest would break the official build flow. Trust assumption documented. |
| F-14 | Auth token file written without explicit permissions | Info     | OPEN | Small hardening. Candidate for 1.3.1. |
| F-15 | `X-Ingress-Path` injected into HTML unsanitized      | Info     | OPEN | Add a regex sanitizer in `serve_index`. Candidate for 1.3.1. |
| F-16 | Worker registry not persistent (operational note)    | Info     | INFO | Operational note, not a security issue. No action planned. |
