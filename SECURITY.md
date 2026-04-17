# Security Policy

## Supported Versions

| Version  | Supported          |
|----------|--------------------|
| 1.5.x    | ✅ Current release  |
| 1.4.x    | ✅ Previous stable — security fixes only if trivially backportable |
| < 1.4.0  | ❌ No patches       |

*(Note: the 1.5 release was developed as `1.4.1-dev.N` through dev.72 and renumbered late cycle as scope grew beyond a patch release. Docker tags with the `1.4.1-dev.N` stamp remain pullable from GHCR but are superseded by the 1.5.x stable tags.)*

## Reporting a Vulnerability

If you discover a security vulnerability, please [open a GitHub issue](https://github.com/weirded/distributed-esphome/issues/new) with:

- A description of the vulnerability
- Steps to reproduce
- The affected version(s)
- Any suggested fix (optional but appreciated)

For vulnerabilities you'd prefer not to disclose publicly, open a minimal placeholder issue asking for a private contact channel and the maintainer will follow up.

## Threat Model

This project's security posture is documented in [`dev-plans/SECURITY_AUDIT.md`](dev-plans/SECURITY_AUDIT.md), including:

- An explicit **Threat Model** section spelling out the six trust assumptions (browser, LAN, workers, Supervisor, operator, build-log provenance) and the items explicitly NOT accepted
- A supply chain threat model with current mitigation state
- An OWASP Top 10 (2021) assessment
- 20 individual findings (F-01 through F-20) with severity ratings and current status
- A "Post-audit mitigations" summary of everything shipped since the original 2026-03-29 audit

The stated threat model is a **trusted home network** behind Home Assistant's Ingress authentication. The server add-on relies on HA Ingress for UI authentication and a shared Bearer token for worker authentication. Since the 2026-04-16 refresh: **F-18 (worker pip install hash-pinning)** is the only remaining open finding and the only item explicitly *not* accepted by the threat model. See the audit document for the full analysis.

## Security Measures

### Supply chain

- **Hash-pinned Python dependencies** (`--require-hashes`) in both server and client Docker images. Lockfiles regenerated via `scripts/refresh-deps.sh`.
- **`pip-audit` + `npm audit`** gating CI on every push — hard failures block merge.
- **Dependabot** configured for pip × 2 (server + client), npm, docker × 2, and github-actions (weekly).
- **Cosign-signed GHCR images** (keyless / GitHub OIDC) — verify with:
  ```bash
  cosign verify \
    --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-.*\.yml@.*' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com \
    ghcr.io/weirded/esphome-dist-client:latest
  ```
- **CycloneDX SBOM attestations** — every published image has a CycloneDX SBOM bound to its digest via `cosign attest --type cyclonedx`. Inspect the component inventory with `cosign verify-attestation --type cyclonedx ... | jq`.
- **SHA-pinned GitHub Actions** — every non-local `uses:` in the workflow files is pinned to a 40-char commit SHA with a trailing `# vN.M.P` version comment. New invariant in `scripts/check-invariants.sh` fails CI on any floating-tag reference. Dependabot bumps both the SHA and the version comment together.
- **PY-7 invariant** — every `--ignore-vuln` in `pip-audit` must carry an inline applicability assessment (why the fix can't be pulled in, whether our code exercises the vulnerable path, dated). Prevents silent CVE dismissals.
- **PY-8 invariant** — every direct dep in `requirements.txt` must also appear in `requirements.lock`. Enforced by `scripts/check-invariants.sh` so a forgotten `refresh-deps.sh` fails CI instead of shipping a broken image.
- **PY-9 invariant** — no macOS-only transitive packages (`pyobjc*`, `appnope`) in `requirements.lock`. Forces lockfile regeneration through the linux/amd64 Docker wrapper in `scripts/refresh-deps.sh`.

### Web surface

- **Security response headers** (CSP, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `X-Frame-Options: SAMEORIGIN`) on every UI response via a dedicated aiohttp middleware. Deliberately not applied to the `/api/v1/*` worker tier.
- **Path traversal prevention** — all file-endpoint handlers route through `helpers.safe_resolve()`.
- **`X-Ingress-Path` sanitization** — the Supervisor-supplied header is regex-stripped to `[/A-Za-z0-9._-]` before being interpolated into the HTML `<base href="…">`. Defence-in-depth against a misconfigured reverse proxy.
- **Monaco editor bundled via Vite** — no external CDN, eliminates a supply-chain vector and enables offline/air-gapped HA installations.

### UI-API authentication (opt-in)

- **`require_ha_auth` add-on option** — when enabled, direct-port (`:8765`) `/ui/api/*` requests must carry a valid HA Bearer token validated against the Supervisor's `/auth` endpoint. Responds `401 Bearer realm="ESPHome Fleet"` on missing or invalid tokens. Ingress-tunneled access is unaffected (Supervisor injects `X-Ingress-Path`).
- **Default `false`** in 1.5 to preserve backwards compatibility with setups that expect unauthenticated direct-port access; planned to flip to default-on in 1.6.
- **Mutation attribution** — when the request was authenticated, compile / pin / schedule / rename / delete log lines suffix the resolved user's name (`…enqueued by stefan`), giving per-user audit trails in the add-on log.

### Protocol & validation

- **Typed protocol** (pydantic v2) with structured `ProtocolError` responses on malformed payloads. `PROTOCOL_VERSION` gate rejects mismatched peers with a clear error.
- **Byte-identical `protocol.py`** between server and client, enforced by `tests/test_protocol.py::test_server_and_client_protocol_files_are_identical` — prevents wire-contract drift.
- **Log payload DoS guard** — `/api/v1/jobs/{id}/log` rejects bodies larger than ~2MB (`log_payload_too_large` → HTTP 413) before aiohttp buffers the full input.

### Auth / observability

- **Structured 401 reasons** (`missing_authorization_header`, `authorization_not_bearer_scheme`, `bearer_token_mismatch`) logged at WARNING with the peer IP for every worker-tier auth refusal.
- **IPv6-aware peer IP normalization** — IPv6 zone IDs stripped, IPv4-mapped IPv6 unwrapped, `peername=None` handled without crashing.
- **Token file least-privilege** — `/data/auth_token` is written with `0600` so even a world-readable `/data` volume mount on the host can't leak the worker-tier bearer.

### What is *not* in scope

These are accepted risks within the home-network threat model; see the full audit for rationale:

- **HTTP between workers and server** (not HTTPS). Users with remote workers across network segments should front the server with their own reverse proxy.
- **Bearer token visible to the browser** (required for the Connect Worker modal's `docker run` command UX).
- **Direct-port `/ui/api/*` unauthenticated by default** (relies on HA Ingress being the only path). Flip `require_ha_auth: true` in the add-on options to require a valid HA Bearer on direct-port access — see above.
- **`secrets.yaml` delivered to every build worker** (required for ESPHome's `!secret` resolution; workers are trusted per the threat model).
- **Build workers can execute `external_components:` / `includes:` / `libraries:` Python** during compile — core ESPHome feature, accepted because workers are trusted.
- **Worker-to-worker job-result authorization isn't checked** on `submit_result` / `update_status` — any authenticated worker can submit results for any job. Accepted because workers are trusted.

### What is *not* accepted

One finding remains **OPEN** and is not accepted by the threat model:

- **Worker `pip install esphome==<version>` is not hash-pinned** (F-18). At job time the worker resolves the full ESPHome dependency graph from PyPI without `--require-hashes`, so a compromised upstream release executes on every worker that compiles for that version. Queued as SC.3 for the 1.5 cycle — ship per-ESPHome-version constraints files in the worker image, `pip install --require-hashes -c …`, and refuse uncovered versions rather than silently falling back.

If your deployment doesn't match the trusted-home-network model, read the audit carefully before exposing the add-on.
