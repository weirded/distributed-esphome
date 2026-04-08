# Development Plans

Roadmap and bug tracking for distributed-esphome, organized by release.

## Active files

- **[WORKITEMS-1.3.1.md](WORKITEMS-1.3.1.md)** — **Current release.** Hardening point release between 1.3 and 1.4: typed server↔worker contracts, targeted regression tests, fragility fixes, CLAUDE.md rewrite
- **[WORKITEMS-1.4.md](WORKITEMS-1.4.md)** — Planned: ESPHome Dashboard parity (create device, firmware download, web serial)
- **[WORKITEMS-1.5.md](WORKITEMS-1.5.md)** — Planned: Power-user features (file tree editor, AI/LLM, config diff)
- **[WORKITEMS-future.md](WORKITEMS-future.md)** — Backlog without committed scope
- **[SECURITY_AUDIT.md](SECURITY_AUDIT.md)** — Security audit findings (refer when making security-relevant changes)
- **[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)** — Step-by-step release process

## Archive

Historical release plans for versions already shipped. Kept for reference but not edited.

- **[archive/WORKITEMS-1.0.md](archive/WORKITEMS-1.0.md)** — First stable release: distributed compile, vanilla JS UI, mDNS discovery
- **[archive/WORKITEMS-1.1.md](archive/WORKITEMS-1.1.md)** — React UI rewrite, Monaco editor, HA integration, device lifecycle (89 bug fixes)
- **[archive/WORKITEMS-1.2.md](archive/WORKITEMS-1.2.md)** — shadcn/ui design system, TanStack Table, SWR, local worker (69 bug fixes)
- **[archive/WORKITEMS-1.3.md](archive/WORKITEMS-1.3.md)** — Quality + Testing: CI, Playwright, ruff, coverage, security hardening, client image version detection

## How this works

- Each release file mixes **work items** (planned features, marked `[x]` when done) and **bug fixes** (checkboxes with `**#NNN**` IDs and `*(X.Y.Z-dev.N)*` version tags).
- Bug numbers are global and monotonic across releases.
- The current release file contains **open bugs** at the bottom — these get folded into the main list as they land.
- When a release ships (merges to `main`), move its file to `archive/` and update the references in this README and `CLAUDE.md`.
