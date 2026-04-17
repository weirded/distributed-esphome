# ESPHome Fleet — End-User Persona (draft v1)

**Purpose.** A single page we can point at when making scope / UX / copywriting decisions: *"is this the right move for who we're actually building for?"* Sketched from the product docs (`README.md`, `ha-addon/DOCS.md`), the internal-engineering stance (`CLAUDE.md`), the threat model (`dev-plans/SECURITY_AUDIT.md` §Threat Model), the UX review (`dev-plans/UX_REVIEW.md`), the four live WORKITEMS files, and the live hass-4 install the UX review profiled (65/67 devices, 4 remote workers on Linux/macOS/Windows/Proxmox).

> **Working draft.** The user will refine — open questions flagged with 🟡.

---

## At a glance

> **"Pat"** — **tech-curious** homeowner (not necessarily tech-professional), runs a mature Home Assistant OS install with 30–100+ ESPHome devices. Any age between mid-20s and mid-70s; as likely to live in Munich, Utrecht, or Birmingham as in Portland or Austin. Has enough hardware around the house that "a Pi is slow, the mini-PC is fast, the gaming PC is sometimes idle" is a real thing. Comfortable with Docker, reads tracebacks without flinching, treats `homeassistant.local` as a domain name. Runs the latest stable ESPHome on a trusted home LAN, reaches the dashboard from outside via Nabu Casa, Tailscale, or Cloudflare. One household, one Fleet install.

One-sentence positioning: **"I outgrew the stock ESPHome dashboard two years ago but didn't want to write my own tool."**

This document profiles Pat and Pat alone. Decisions that serve other kinds of users (the household member who only uses HA dashboards, the brand-new HA user, the contributor) are out of scope here — when such decisions come up, we note them as "not primarily for Pat" but we don't personify them.

---

## Demographics & context

Grounded in the [2024 Home Assistant Community Survey](https://www.home-assistant.io/blog/2024/12/16/community-survey-2024/) (8,600+ responses, summary presented at [State of the Open Home 2025](https://www.home-assistant.io/blog/2025/04/16/state-of-the-open-home-recap/)) and Home Assistant's own characterization of its user base. Key published findings:
- **2+ million active installations** worldwide as of 2025.
- **"Tech-curious"** is HA's own framing for its majority — deliberately broader than "tech-professional."
- **3+ years of HA use** for the majority — this is not a fad-chaser community.
- **2.8 people per household** on average — family homes, not single-occupant techie caves.
- **11–100 devices** per typical install — with a long tail into the hundreds that ESPHome Fleet specifically serves.
- **21,000+ GitHub contributors** in 2024 — but contributors are a small fraction of users; the vast majority never touch a PR.
- **Values alignment** around privacy and choice is stronger than around "cool tech."

**Age range: wide. Roughly 25–70, with a concentration 35–55 and meaningful tails on both ends.** The home-automation hobby maps well onto homeownership + disposable time, which is itself a wide band: young couples setting up their first house, mid-career families managing a growing household, empty-nesters re-tinkering, and retirees with time + savings for a big fleet. The stereotype of "under-30 tech bro" does not match HA's actual base.

**Geography: global, with a pronounced European skew.** HA is a Netherlands-founded project with a heavy continental-European core. The practical order of user concentration (roughly, from community observation — not an official breakdown):

1. **Central / Western Europe:** Germany and the Netherlands are disproportionately represented; UK, Belgium, Austria, Switzerland, France follow.
2. **Nordics:** Sweden, Denmark, Norway, Finland punch well above their population weight.
3. **North America:** United States + Canada — a large cohort but not the majority of the global base.
4. **Australia / New Zealand.**
5. **Growing but under-represented:** Southern Europe (Spain, Italy, Portugal), Eastern Europe, East Asia (Japan, Taiwan, Singapore), Brazil, and parts of the Middle East.

For ESPHome Fleet specifically this means: English is the lingua franca of the community but is a second language for a substantial fraction of the user base. Units, number formats, electrical standards (230V/50Hz vs 120V/60Hz), WiFi regulatory domains, Thread/Matter availability all vary. The maintainer's own install happens to be US-located — but the product should never *assume* that.

**Profession: not primarily software engineers.** Tech-curious doesn't map cleanly onto a job title. The HA user base includes software engineers and sysadmins, yes, but also:
- **Engineers in other disciplines** — mechanical, electrical, civil, industrial control.
- **Technically-inclined tradespeople** — electricians, HVAC technicians, solar installers, network cable installers.
- **STEM-adjacent professionals** — architects, scientists, medical technicians, engineers-turned-managers, teachers.
- **"Knowledge workers" generally** — who happen to have a systems-thinking hobby streak.
- **Retirees** with a technical background and time to tinker.
- **University students** in technical fields who inherited an interest from a parent.
- **People who simply got obsessive about their smart home** — photographers, writers, small-business owners. The gateway drug is often one frustrating off-the-shelf product, not a professional need.

Programming is **not** a default. "Can read a README carefully, follow a `docker run` command, and copy a YAML example and tweak it" is the floor. Some Pats write code daily; others haven't since university and prefer YAML precisely because it isn't code.

**Gender: male-skewed but not monoculture.** HA has acknowledged this publicly — the recently-introduced UX research function and neurodiversity question in the 2024 survey reflect a deliberate effort to listen to a broader community than the GitHub-issue-filing majority. Design decisions should avoid assuming a male-coded "sysadmin in a basement" stereotype even though that cohort is real and loud.

**Household: homeowners** (or long-term renters with the kind of landlord who lets them wire things). The product's value proposition is only persuasive at the point where someone has 15+ devices, which generally only happens in homes you've lived in for more than a couple of years. Apartments and condos are under-represented but not absent.

**Neurodiversity.** HA's own 2024 survey explicitly asked about this, which tells us the community considers it worth designing for. Practical consequence: **consistency, low-surprise defaults, deterministic behavior, keyboard-operable interfaces, and low sensory noise** (no animated drifting gradients, no autoplay, no badge flicker) matter more in this community than in a consumer product. This aligns naturally with power-user preferences — an overlap we should preserve.

**Community touchpoints.** r/homeassistant and r/esphome on Reddit, the [Home Assistant Community forum](https://community.home-assistant.io/), the HA Discord, occasional GitHub issues, and a YouTube ecosystem (Jeff Geerling, The Hook Up, Everything Smart Home, DB Tech, and a long tail of language-specific channels in German, Dutch, and other European languages). Information travels along these rails — if a bug is painful enough, it shows up as a forum post before it becomes a GitHub issue.

### Pat's concrete install profile

Signals to anchor decisions against:

- **Deployment: Home Assistant OS** (or Home Assistant Supervised, a small sibling cohort). Not HA Container, not a bare-Docker install. This means we can rely on Supervisor — `hassio_api`, `auth_api`, the Supervisor token, Ingress injection, and the add-on options schema all work. We don't need to design fallbacks for "what if there's no Supervisor."
- **ESPHome track: latest stable.** Pat upgrades when a release is out and marked stable, not on beta cadence. The `Show betas` toggle defaults off. The breaking-change-analyzer (1.7 BC.*) is a *nice-to-have* — Pat already reads release notes before bumping versions.
- **HA Voice / Assist user: yes, probably.** Pat uses Home Assistant's native Assist features — voice control, the Assist pipeline, the unified Updates card. The Fleet HA integration's entity richness (update entities, schedule sensors, worker-state sensors) matters for Pat's daily HA experience, not just for automation authors.
- **Remote access: yes, via their own choice of tunnel.** Nabu Casa Cloud subscription, or a Tailscale tailnet, or a Cloudflare Tunnel. The product doesn't need to know or care which — but the fact that Pat *does* reach the UI from outside the house means (a) mobile/narrow-viewport degradation matters more than a pure-desktop persona would imply, and (b) the `require_ha_auth` opt-in **is** load-bearing when Pat drops out of Ingress.
- **Scope: one household, one Fleet install.** Multi-site / shared-fleet use cases are out. `single_config_entry: true` (CR.2) is the correct call.
- **Custom `external_components` authoring: *some* Pats, not most.** The F-17 accepted-risk posture is right. We shouldn't build a dedicated component-authoring IDE surface — the subset of Pats who write components use a real editor + git repo and point ESPHome at it. Our YAML editor is for the other 80%.
- **Secret management: plain `secrets.yaml` universally.** HashiCorp Vault / 1Password CLI / external secret stores are not in the picture. F-04 (secrets.yaml delivered to every worker) stays accepted-risk; no integration with external secret managers needed.
- **Streamer mode's real purpose: GitHub issue attachments.** Not Twitch / YouTube. Pat reaches for streamer mode when they're about to screenshot a bug and post it to a GitHub issue or forum thread. Practical consequence: *everywhere a bug-report screenshot might originate*, streamer mode should do the right thing. That means the Secrets modal + Connect Worker token field (UX.9 / UX.31 in `UX_REVIEW.md`) are meaningful streamer-mode gaps, and less-expected screenshot sources (Live Logs modal, validate output, editor diagnostics) deserve a once-over too.

---

## Technical sophistication

**Medium-to-high, with wide variance.** Pat can do things, but the floor is not "professional software engineer." The product has to be usable by someone who follows instructions carefully, not just by someone who writes instructions. Specifically:

- **Docker-comfortable, not Docker-expert.** Can copy a `docker run` or `docker compose up -d` from a README and adjust env vars. Understands *what* a volume is. Doesn't necessarily understand `network_mode: host` by heart — but will believe the docs when they say to use it. May use Portainer/Dockge as a GUI over Docker. Some Pats set up Docker from the CLI; others only ever use it via an appliance-UI.
- **YAML-comfortable, improving over time.** Edits ESPHome configs by hand, sometimes by copy-paste-tweak from forum examples. Uses `!secret` and substitutions fluently; `packages:` and `external_components:` less so (and sometimes only because the community told them to). Owns a `secrets.yaml`. The Monaco editor with schema autocomplete is a big part of why Pat tolerates editing YAML at all.
- **Linux-aware, not Linux-native.** May SSH into the HA host occasionally, may never. Reads error messages and can tell the difference between "network error" and "permission denied." Some Pats run Unraid, TrueNAS, or a Synology with Docker support — the appliance-UI is the primary interface, not the shell.
- **Networking-aware, at the level the hobby demands.** Knows mDNS exists because they had to fix it once. Understands "IoT VLAN" because a forum post told them to set one up. Can use a web admin UI for their router. Debugging a packet capture is out of scope for most Pats.
- **Git-familiar, not git-native.** Has a GitHub account (probably just to click ⭐ on projects). May have cloned a repo once. The 1.6 GitHub Sync feature is an **aspirational** capability — most Pats have never run `git commit` — which is exactly why we're making it automatic behind a single button.
- **API-curious.** Can follow a `curl` recipe from a README. 1.7 LLM integration assumes they can generate an OpenAI / Anthropic API key *when instructed*, not that they have one lying around.
- **Cron-literate, reluctantly.** Can recognize `0 2 * * *` as "2 AM daily" because they've seen it before. The inline cron preview in the Schedule modal exists *because* plenty of Pats would otherwise bounce off the raw expression.

**The floor is moving down over time.** Features in 1.6 / 1.7 / 1.8 (file-tree editor with auto-versioning, LLM YAML assist, Web Serial first-flash, HA-native Update entities) each lower the required technical floor by one notch. The product is consciously becoming more accessible — *without* removing the power-user surface.

**What Pat is NOT today:**
- A first-time HA user who installed their first sensor last month — not because we forbid them, but because the *value proposition* (fleet management) doesn't apply until there's a fleet. We don't optimize against them; we just don't target them.
- A "my spouse set this up" passive consumer. They use HA's frontend, not the add-on's UI.
- Someone who genuinely panics at the sight of YAML. The product requires tolerating YAML. Closing this gap is an aspirational direction for a later release (LLM authoring, visual YAML builders).
- Someone who expects a mobile-first experience. Desktop is the primary surface; phone is occasional triage.

**What Pat is NOT required to be, despite product origin-story optics:**
- A professional software developer.
- Fluent in English (though they can *operate* in English).
- A US resident.
- Male.
- Under 50.

---

## Fleet & hardware profile

Drawn from the live hass-4 install the UX review observed, which is the maintainer's own setup and a reasonable midpoint for the target persona:

- **Devices: 30–150.** The product's sweet spot begins at the point where the stock dashboard breaks down (~15 devices, anecdotally) and runs up through what the home-lab hobby can reasonably accumulate (150ish before people start building scripting layers). Observed: **67 devices**.
- **Device mix is wildly heterogeneous.** Sensors (CO2, env, presence, power), actuators (plugs, valves, LEDs, UFO lights), bridges (BT proxies for Xiaomi/BLE, DSC alarm interface), info displays (CYD touchscreens, Ulanzi clocks), energy infrastructure (BMS for battery banks, Victron integration, PG&E power monitor), gate/door controllers. Nothing is "just one kind of thing."
- **Boards:** ESP32 dominant (esp32dev, esp32-s2, esp32-s3, esp32-c3, esp32-c6, esp32-p4), some esp8266 legacy, occasional RP2040 / RP2350, Nano C6. Comfortable across multiple chip families.
- **Frameworks:** arduino + esp-idf both in use (the test install explicitly has esp32s2-idf fixtures).
- **Network topology:** probably IoT VLAN separation, mDNS forwarding configured, static DHCP reservations for critical devices.
- **Thread / Matter:** emerging — the install has a `matter-test` device, and Thread/IPv6 support is a 1.8 workitem. The persona is curious about Matter but hasn't committed.

**Compile infrastructure:**
- HA host: typically a Raspberry Pi 4, or an Intel NUC / mini-PC, or an N100 box. Sometimes "Home Assistant Yellow" / "Home Assistant Green."
- Additional compile targets: varies wildly. Observed set:
  - `local-worker` (the built-in one on HA itself)
  - A Linux desktop (Debian on Proxmox — Intel i7 / 8 GB)
  - A Windows desktop (Windows 10 / i5)
  - A macOS machine (Apple Silicon M1 Mini)
  - A fast laptop that runs a worker when docked at the desk
- **The heterogeneity is itself a signal.** This user has *leftover hardware* and wants to put it to work.

---

## Goals (what Pat hires ESPHome Fleet to do)

1. **Parallelize fleet-wide upgrades across every machine Pat can spare — the original reason this project exists.** When a new ESPHome release drops and Pat wants to move the whole fleet to it, a sequential compile-per-device on a single worker — even a beefy one — is **hours of wall-clock time** at 50+ devices. Distributing the queue across the Proxmox VM, the idle gaming PC overnight, the macOS Mini in the office, and the built-in local worker cuts the same job to minutes. This is the headline win that justifies the whole distributed-compile architecture; bulk operations, scheduling, and per-device pinning are the affordances that make it usable, but raw wall-clock speed on a fleet-wide upgrade is the *why*.
2. **Offload a single compile to hardware that can actually do it.** HA runs on a Pi for a reason; compiles don't belong there. Even without a multi-worker fleet-wide upgrade in play, a one-off "I just edited `cyd-office-info.yaml`, compile it" shouldn't take 8 minutes on the HA host when a 30-second compile is possible on a faster box.
3. **Keep a growing fleet maintainable without it eating my Saturdays.** Bulk operations, scheduling, pinned versions — so "upgrade everything to 2026.4.0 at 3 AM Sunday except the two devices pinned to 2026.3.3 because they're on an older framework" is a one-click setup, not a shell-script ritual.
4. **Keep Home Assistant as the single source of truth.** Pat's configs live in `/config/esphome/`; Pat's dashboard shows device state; Pat's automations trigger compiles. ESPHome Fleet is the *management layer*, not a parallel universe.
5. **See everything in one view.** Fleet-wide "is anything outdated?", "which devices haven't compiled successfully in the last week?", "what's pinned where?" — the Devices tab *is* the answer.
6. **Test carefully before rolling out.** Pin one device to a new ESPHome version, compile + OTA it, watch the logs for a week, then roll out to the fleet with Upgrade Outdated.
7. **Schedule disruptive operations for off-hours.** OTA reboots light bulbs. Pat wants them at 3 AM, not while the kids are doing homework.
8. **Keep an audit trail.** "When did this device last compile successfully?" "What changed between the current config and what's actually running?" (1.6 AV.* + JH.* will fulfill this more fully.)

---

## Pain points before ESPHome Fleet

The documented hook that brings Pat here (from `ha-addon/DOCS.md` and implied in `README.md`):

- **"The stock ESPHome dashboard works fine for 8 devices, not for 80."** No bulk operations, no sorting, no filtering, no scheduling, no pinning.
- **"Compilations on the HA host are painful."** 3–10 minute compile cycles on a Pi, felt especially when iterating on YAML.
- **"No audit of what's actually running."** Is that device on 2026.2.1 or 2026.3.0? Stock dashboard just shows what's in the YAML.
- **"I don't want to hand-roll cron jobs on the Pi for OTA upgrades."** Wants a UI-managed, HA-integrated scheduler.

---

## Attitudes and preferences

**High signal from the UX review + code conventions:**

- **Wants high information density.** Small fonts, dense tables, tooltips-rich. The UX_REVIEW explicitly calls out "high information density" as a product value. Whitespace-heavy "clean" design *feels wrong* to Pat.
- **Wants the full picture up front, not progressive disclosure.** Column picker exposes 11 columns — because Pat wants that many, eventually.
- **Appreciates transparency.** The `# distributed-esphome:` YAML comment block is visible in the editor because Pat wants to see how the sausage is made. `via mDNS` / `wifi.use_address` is surfaced under each IP — same reason.
- **Is allergic to inconsistency.** The UX_REVIEW's terminology audit and case-normalization pass exist because Pat *notices* when "Upgrade" and "COMPILING + OTA" and "Compile + OTA" all refer to the same thing. Small drift = big irritation.
- **Wants power-user affordances.** Live cron preview, version-list search with beta toggle, pin-specific-version column — all lovingly built.
- **Respects the product's choices.** The threat model explicitly accepts plaintext HTTP on the LAN, bearer-in-browser, secrets-to-every-worker — because Pat agrees *for their deployment*. The product says "this is a home-lab tool with trusted-LAN assumptions" and Pat says "yes, exactly."
- **Resents repetitive busywork.** If Pat has to click through the same confirm dialog ten times to do a bulk action, or tail a log file over SSH to learn why a compile failed, Pat will grumble. Good bulk operations, clear error messages, and one-click access to logs all respect Pat's time.

**Aesthetics:** dark mode default, accent-blue-ish (HA-native color palette), monospaced accents, Lucide icons, shadcn primitives. Not Bootstrap. Not Material. Not retro-green-on-black terminal cosplay.

---

## Workflows Pat actually runs

These are the surfaces the product is optimized around — each maps to a specific tab / modal cluster:

### Daily / weekly
- **Glance at the Devices tab** to check "anything red?" — offline devices, stale firmware, workers down.
- **Compile one device** after editing a YAML — the per-row `[Upgrade]` button + Editor → Save & Upgrade combo.
- **Watch live logs** after a compile to confirm the device came up healthy — `Live Logs` in the hamburger.
- **Clear the Queue** of done jobs periodically — or leave it; terminal jobs persist across restarts by design, so Pat has a running record of what compiled when.

### Monthly
- **Bulk upgrade** the fleet when a new ESPHome version looks stable — `[Upgrade ▼] → Upgrade All Online`.
- **Adjust schedules** after DST / seasonal routine changes.
- **Edit `secrets.yaml`** when a WiFi password rotates or a new BLE bindkey lands.
- **Pin a device** when an ESPHome release breaks one specific component they care about — Unpin later.

### Occasionally
- **Add a new device** — `+ New Device`, duplicate from an existing one with similar setup.
- **Add a new worker** — Connect Worker modal, paste the generated `docker run` (or compose) onto whatever idle machine is handy.
- **Duplicate a device** when rolling out a second copy of an already-working config (e.g., Garage Door (Big) → Garage Door (Small)).
- **Dig into a failed compile log** — Queue → Log modal.

### Rarely
- **Worker cache eviction, remove a retired worker** — via the Workers tab actions.
- **Validate an edited YAML without compiling** — Editor → Validate.
- **Download a firmware binary** instead of OTA-ing — Compile + Download mode (for first-flash via USB on a new device).
- **Restart the whole add-on** via HA — because something wedged and a restart is the simplest move.

### Aspirational (product is heading here)
- **Auto-versioned config** — every save is a git commit, view diff of what changed since the last compile (1.6 AV.*).
- **Per-device compile history** — "when did this device last compile successfully" (1.6 JH.*).
- **HA native Update entities** — Fleet's compile-and-OTA shows up in HA's standard Updates card (1.5/1.6 UE.*).
- **LLM assist for YAML** — ghost-text completions, a chat panel for "add a DHT22 sensor on GPIO4" (1.7 AI).
- **Pre-upgrade breaking-change analysis** — "will this release break any of my devices" (1.7 BC.*).
- **Web Serial first-flash** — USB-flash a brand-new ESP from the browser without the CLI (1.8).

---

## Trust posture & security temperament

Explicit from `SECURITY_AUDIT.md`'s Threat Model section:

- **"It's my LAN, it's my problem."** Pat accepts the six trust assumptions the threat model spells out — trusted browser, trusted LAN, trusted workers, trusted Supervisor, trusted operator, build-log-provenance-is-self-referential. None of these is a negotiation.
- **Does NOT want zero-trust overhead inside the house.** Mutual TLS between workers and server would be "solving the wrong problem for my home-lab."
- **DOES want sensible defaults where it's free.** Hash-pinned lockfiles, SHA-pinned GitHub Actions, cosign-signed images, SBOM attestations — all shipped and documented because they're zero-cost wins Pat appreciates knowing about (even if Pat personally never runs `cosign verify`).
- **Owns their own worker-update cadence.** When a worker image updates, Pat runs `docker pull && docker restart <container>` on their own schedule. Doesn't want a background process rebooting their compile hosts at 3 AM on the product's timetable.
- **Has a strong opinion about ESPHome's `external_components` being accepted by design.** Because Pat personally uses them. Killing that feature to close F-17 would be user-hostile.

---

## The product decisions this persona justifies

Cross-referencing the persona against shipped and planned features:

| Decision | Why Pat is the reason |
|---|---|
| Dense tables, 11-column-picker Devices tab | Info density over whitespace |
| Per-device YAML editor with Monaco + schema autocomplete | Pat edits YAML by hand |
| Per-device version pinning + ESPHome version dropdown | Pat tests versions before rolling out |
| Custom cron schedules with inline preview | Pat can read `0 2 * * *`; the preview is bonus validation |
| Plaintext bearer token in Connect Worker modal | Pat's LAN; Pat's machine; pasting a `docker run` is the fast path |
| `external_components` + `includes` + `libraries` execute on workers | Pat uses these |
| Docker Compose tab in Connect Worker (UX.10) | Pat runs Compose stacks |
| Auto-versioning via git, not a bespoke diff format (1.6 AV.*) | Pat already knows git |
| No auto-update of workers baked in (WU.* declined in 1.6) | Pat owns their update cadence |
| `require_ha_auth` ships *opt-in first, mandatory later* | Pat may have scripts on port 8765; we give them time |
| `streamer_mode` exists at all | Pat posts screenshots to GitHub issues + forum threads; wants to blur WiFi passwords + IPs before hitting Submit |
| LLM integration is opt-in, BYO-API-key (1.7) | Pat has API keys; doesn't want Anthropic proxying their YAML |
| Server stays near-idle when nothing's happening | Pat leaves the UI open on a second monitor; doesn't want it pegging the Pi HA runs on |

---

## Roadmap implications (suggested re-ordering)

Given the clarified Pat profile — HA OS, latest stable, Assist user, has remote access, single household, secrets.yaml only, most-don't-author-components — the published 1.5 → 1.8 roadmap is **roughly right**, but a few items shift in weight relative to the draft priority. My read:

**Gains weight for Pat:**
- **UE.*** (HA Native Update entities, spread across 1.5 / 1.6). Pat uses the HA Updates card daily; having Fleet's per-device update state in that card is higher-value than the draft implied.
- **JH.*** (Job History, 1.6). Pat runs latest-stable and picks upgrade windows from release notes — "when did this device last compile successfully?" is the companion question and the JH drawer answers it.
- **DO.*** (Device Organization / key-value tags, 1.6). At 50+ heterogeneous devices, grouping/filtering is how Pat stops scrolling. Undersold in the original plan.
- **Thread / IPv6 support** (1.8 #17). Matter is gaining real traction; the `matter-test` device in the install is a canary. Consider pulling this earlier than 1.8.
- **Web Serial flashing** (1.8 3.2a). Every new device Pat adds needs a first-flash; today Pat drops to the CLI or opens `web.esphome.io` in a separate tab. A second-tier pull-forward candidate.

**Loses weight for Pat:**
- **BC.*** (Breaking-change analyzer, 1.7). Pat already reads release notes by hand. This becomes "nice rigor for release days" rather than a critical feature.
- **AV.*** (Auto-versioning via git, 1.6). Pat is git-familiar, not git-native — the *safety-net* framing is right, but this is lower urgency than JH / UE / DO. Keep shipping it, don't front-load it.
- **GS.*** (GitHub Sync, 1.6 stretch). Pat may have a GitHub account but mostly doesn't push configs there today. Genuinely stretch scope.
- **AI/LLM YAML assist** (1.7). Fun, marketable, but the Monaco editor + schema autocomplete are already doing most of the work. "BYO API key" gating also reduces adoption.
- **Remote Compilation** (1.8 RC.*). Pat's workers are on-LAN. VPS compile is a niche within a niche.

**Suggested re-ordering inside 1.6** (within the shipped release target — not a new release split):
`UE.* > JH.* > DO.* > FT.* (file tree) > AV.* > GS.*`

**For 1.8, consider pulling forward:** Thread/IPv6 (#17) and Web Serial (3.2a) — both are stock-ESPHome-dashboard parity items Pat notices every time they set up a new device.

None of this is urgent enough to re-file the workitems; but when the 1.6 release comes up for sequencing, weight the above.

---

*End of draft v2 — Pat-only, clarifications folded in. Expect the Roadmap section to move most in the next iteration; the demographic and sophistication sections should be close to final.*
