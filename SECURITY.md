# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.3.x   | ✅ Current release  |
| < 1.3   | ❌ No patches       |

## Reporting a Vulnerability

If you discover a security vulnerability, please [open a GitHub issue](https://github.com/weirded/distributed-esphome/issues/new) with:

- A description of the vulnerability
- Steps to reproduce
- The affected version(s)
- Any suggested fix (optional but appreciated)

## Threat Model

This project's security posture is documented in [`dev-plans/SECURITY_AUDIT.md`](dev-plans/SECURITY_AUDIT.md), including:

- A supply chain threat model (9 prioritized vectors)
- An OWASP Top 10 (2021) assessment
- 20 individual findings (F-01 through F-20) with severity ratings and fix status

The stated threat model is a **trusted home network** behind Home Assistant's Ingress authentication. The server add-on relies on HA Ingress for UI authentication and a shared Bearer token for worker authentication. See the audit document for the full analysis and accepted risks.

## Security Measures in 1.3.1+

- **Hash-pinned Python dependencies** (`--require-hashes`) in both server and client Docker images
- **pip-audit + npm audit** gating CI on every push
- **Dependabot** configured for pip, npm, docker, and github-actions (weekly)
- **GHCR images signed with cosign** (keyless / GitHub OIDC) — verify with:
  ```bash
  cosign verify \
    --certificate-identity-regexp 'https://github.com/weirded/distributed-esphome/.github/workflows/publish-.*\.yml@.*' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com \
    ghcr.io/weirded/esphome-dist-client:latest
  ```
- **Security response headers** (CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, X-Frame-Options) on every UI response
- **Typed protocol** (pydantic v2) with structured validation errors on malformed payloads
