#!/usr/bin/env python3
"""Multi-target deploy + smoke orchestrator for ESPHome Fleet.

Deploys the current dev build (ha-addon/VERSION) to three install paths in
parallel, runs the e2e-hass-4 Playwright suite against each, and prints a
collated pass/fail summary plus clickable URLs.

Replaces ``./push-to-hass-4.sh`` as the end-of-turn smoke command. Keeps
push-to-hass-4.sh around as a fast-path single-target loop for UI-only
iteration (no GHCR round-trip).

Targets (see dev-plans/HOME-LAB.md):
  hass-4          always-on HAOS box at 192.168.225.112
  haos-pve        throwaway HAOS VM on the `pve` Proxmox host
  standalone-pve  plain Docker host `docker-pve` running docker-compose

Image flow: GitHub Actions (publish-addon.yml / publish-server.yml /
publish-client.yml) already builds and pushes the three GHCR images on
every develop push — keyed off ha-addon/VERSION, which bump-dev.sh
changes every turn. This script waits for those tags to appear, then
deploys. No laptop-side GHCR write auth required.

End-of-turn sequence is therefore:
  bump-dev.sh → git commit + push → python scripts/test-matrix.py

Usage:
  scripts/test-matrix.py                    # all targets (default)
  scripts/test-matrix.py --targets hass-4   # single target
  scripts/test-matrix.py --no-wait          # skip the GHCR poll
  scripts/test-matrix.py --seq-tests        # serialize Playwright runs
  scripts/test-matrix.py --list             # show targets and exit
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import http.server
import json
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "ha-addon" / "VERSION"
LOG_ROOT = REPO_ROOT / "build" / "test-matrix"
GHCR_OWNER = "weirded"

# Matches the upstream publish-addon.yml IMAGE_NAME pattern: one per arch
# with the arch prefixed. {arch} gets substituted to "amd64" here since
# all three targets are x86_64.
IMG_ADDON = f"ghcr.io/{GHCR_OWNER}/amd64-addon-esphome-dist-server"
# Standalone compose consumes these two unprefixed images
# (docker-compose.yml at repo root).
IMG_SERVER = f"ghcr.io/{GHCR_OWNER}/esphome-dist-server"
IMG_CLIENT = f"ghcr.io/{GHCR_OWNER}/esphome-dist-client"


# ANSI colors for per-target prefixes. Falls back to plain text when stdout
# isn't a TTY (pipes, CI logs). 38;5;N = 256-color.
COLORS = {
    "hass-4":         "\033[38;5;42m",   # green
    "haos-pve":       "\033[38;5;39m",   # blue
    "standalone-pve": "\033[38;5;170m",  # magenta
    "build":          "\033[38;5;214m",  # orange
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def color(name: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{COLORS.get(name, '')}{text}{RESET}"


# ---------------------------------------------------------------------------
# Tee: every line the matrix prints to stdout also lands in an in-memory
# ring buffer so the --web HTTP server can serve it back to a browser.
# Wrapping sys.stdout once at startup (see main()) means there's no need
# to route every `print()` through a helper.
# ---------------------------------------------------------------------------

_output_lines: collections.deque[str] = collections.deque(maxlen=5000)
_output_lock = threading.Lock()


class _TeeStdout:
    def __init__(self, original: Any) -> None:
        self._orig = original

    def write(self, s: str) -> int:
        n = self._orig.write(s)
        if s:
            with _output_lock:
                # Append each full line. A trailing partial (no \n) is held
                # under the assumption a later write completes it; keeping
                # it simple — split on any newline and drop empty trailing.
                for line in s.splitlines():
                    _output_lines.append(line)
        return n

    def flush(self) -> None:
        self._orig.flush()

    def isatty(self) -> bool:
        return self._orig.isatty()

    def fileno(self) -> int:
        return self._orig.fileno()


# ---------------------------------------------------------------------------
# Per-target state files. Each target's state.json is the single source
# of truth the --web server reads to render the status table; the matrix
# overwrites it at each phase transition.
# ---------------------------------------------------------------------------

def _write_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic enough for a reader that polls: write to tmp, rename.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _clear_state_dir() -> None:
    """Remove stale state files from a prior run so the web UI starts fresh."""
    if not LOG_ROOT.exists():
        return
    (LOG_ROOT / "build-state.json").unlink(missing_ok=True)
    for d in LOG_ROOT.iterdir():
        if d.is_dir():
            (d / "state.json").unlink(missing_ok=True)


# Images the matrix waits for. All three are published by the CI
# workflows under .github/workflows/publish-*.yml on every develop push
# whose diff touches ha-addon/VERSION (which bump-dev.sh always does).
EXPECTED_IMAGES = [IMG_ADDON, IMG_SERVER, IMG_CLIENT]

# Map image short-name (last path segment) → publish workflow filename.
# Used to render per-workflow GitHub Actions status in the --web UI.
GH_REPO = f"{GHCR_OWNER}/distributed-esphome"
WORKFLOW_BY_IMAGE = {
    "amd64-addon-esphome-dist-server": "publish-addon.yml",
    "esphome-dist-server": "publish-server.yml",
    "esphome-dist-client": "publish-client.yml",
}


@dataclass
class Target:
    name: str
    base_url: str
    # Command to deploy (with --skip-smoke appended). Run from REPO_ROOT.
    deploy_cmd: list[str]
    deploy_env: dict[str, str] = field(default_factory=dict)
    # Path the deploy script writes the add-on token to on success. Read
    # after deploy completes and passed to Playwright as FLEET_TOKEN.
    token_cache: Path = Path()
    # Extra env to pass to Playwright (FLEET_TARGET, HASS_URL/HASS_TOKEN
    # for ha-services.spec.ts, etc.).
    playwright_env: dict[str, str] = field(default_factory=dict)
    # Extra args to `npm run test:e2e:hass-4 --`, e.g.
    # ["--grep-invert=@requires-ha"].
    playwright_args: list[str] = field(default_factory=list)


def make_targets(version: str) -> dict[str, Target]:
    home = Path.home()
    tag = version  # 1:1 with VERSION; no separate --from-ghcr TAG argument

    return {
        "hass-4": Target(
            name="hass-4",
            base_url="http://192.168.225.112:8765",
            deploy_cmd=["./push-to-hass-4.sh", "--from-ghcr", "--skip-smoke"],
            token_cache=home / ".config" / "distributed-esphome" / "hass4-token",
            playwright_env={
                "HASS_URL": "http://hass-4.local:8123",
                "HASS_TOKEN": os.environ.get("HASS_TOKEN", ""),
                "FLEET_TARGET": "cyd-office-info.yaml",
            },
        ),
        "haos-pve": Target(
            name="haos-pve",
            base_url="http://192.168.226.135:8765",
            deploy_cmd=["./push-to-haos.sh", "--from-ghcr", "--skip-smoke"],
            deploy_env={"HAOS_URL": "http://192.168.226.135:8123"},
            token_cache=home / ".config" / "distributed-esphome" / "haos-addon-token",
            playwright_env={
                # The throwaway VM doesn't have the esphome_fleet HA service
                # set up, so @requires-ha specs would skip themselves on the
                # HASS_TOKEN guard anyway. Filter them out explicitly so the
                # summary row shows pass/5 not pass/6-with-skip.
                "FLEET_TARGET": "cyd-world-clock.yaml",
            },
            playwright_args=["--grep-invert=@requires-ha"],
        ),
        "standalone-pve": Target(
            name="standalone-pve",
            # IP, not the `docker-pve` SSH alias — the browser and
            # Playwright's Node client don't read ~/.ssh/config. The
            # SSH-side (STANDALONE_HOST below) still uses the alias.
            base_url="http://192.168.227.90:8765",
            deploy_cmd=["bash", "scripts/standalone/deploy.sh"],
            deploy_env={"TAG": tag, "STANDALONE_HOST": "docker-pve"},
            token_cache=home / ".config" / "distributed-esphome" / "standalone-token",
            playwright_env={
                "FLEET_TARGET": "cyd-world-clock.yaml",
            },
            playwright_args=["--grep-invert=@requires-ha"],
        ),
    }


@dataclass
class TargetResult:
    target: str
    deploy_ok: bool = False
    deploy_elapsed: float = 0.0
    tests_passed: int = 0
    tests_total: int = 0
    tests_ok: bool = False
    total_elapsed: float = 0.0
    report_dir: Path = Path()
    error: str = ""


# ---------------------------------------------------------------------------
# Subprocess plumbing: run a command, tee stdout+stderr to prefixed terminal
# output AND a per-target log file, return the exit code.
# ---------------------------------------------------------------------------

async def run_streaming(
    cmd: list[str],
    *,
    prefix: str,
    log_path: Path,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> int:
    """Run ``cmd``, streaming output prefixed with ``[prefix]`` AND appending
    to ``log_path``. Returns the exit code.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Mark the start of this command in the log so post-mortems can tell
    # where each phase begins.
    with log_path.open("a") as log:
        log.write(f"\n===== $ {' '.join(cmd)} =====\n")

    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    # Line-buffered stdout for Python children. Bash children generally flush
    # on newline when stdio is a pipe, but this makes the live view snappier
    # when any step is a Python script.
    full_env.setdefault("PYTHONUNBUFFERED", "1")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=full_env,
        cwd=str(cwd) if cwd else None,
    )

    tag = color(prefix, f"[{prefix:<14}]")
    assert proc.stdout is not None
    with log_path.open("a") as log:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            log.write(line + "\n")
            log.flush()
            print(f"{tag} {line}", flush=True)

    return await proc.wait()


# ---------------------------------------------------------------------------
# Preflight checks — fail fast with actionable errors.
# ---------------------------------------------------------------------------

def preflight(skip_wait: bool) -> None:
    problems: list[str] = []

    if not VERSION_FILE.exists():
        problems.append(f"VERSION file missing at {VERSION_FILE}")

    if not skip_wait and shutil.which("docker") is None:
        problems.append(
            "`docker` not found on PATH (needed for `docker buildx imagetools inspect` "
            "against GHCR)"
        )

    for script in ("push-to-hass-4.sh", "push-to-haos.sh"):
        if not (REPO_ROOT / script).exists():
            problems.append(f"missing {script} at repo root")

    if problems:
        sys.stderr.write("Preflight failed:\n")
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        sys.exit(2)


# ---------------------------------------------------------------------------
# Step 1: wait for CI-published images on GHCR.
# ---------------------------------------------------------------------------

async def _tag_exists(image: str, version: str) -> bool:
    """Return True iff ghcr.io/<image>:<version> currently resolves.

    Uses `docker buildx imagetools inspect`, which hits the registry API
    (no pull) and returns exit 0 iff the tag is present.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", "buildx", "imagetools", "inspect", f"{image}:{version}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return (await proc.wait()) == 0


def _head_sha() -> str:
    """HEAD commit on the current branch, used to look up the GitHub
    Actions run that built this dev-tag. Empty string if git fails.
    """
    try:
        import subprocess as _sp
        r = _sp.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


async def _workflow_run(workflow_file: str, head_sha: str) -> dict[str, Any]:
    """Fetch the latest GitHub Actions run for ``workflow_file`` on
    commit ``head_sha``. Returns {status, conclusion, url}. Falls back
    to ``status='not_started'`` when no run matches, ``status='unknown'``
    when `gh api` fails (not authed, offline, etc.) — either way the
    matrix still proceeds on GHCR tag presence, so this is just for the
    UI.
    """
    if not head_sha:
        return {"status": "unknown", "conclusion": None, "url": None}
    # Query string goes in the URL — `gh api -f key=val` sends a form
    # body on GET, which the API ignores / rejects as a bad request.
    path = (
        f"/repos/{GH_REPO}/actions/workflows/{workflow_file}/runs"
        f"?head_sha={head_sha}&per_page=1"
    )
    cmd = ["gh", "api", path, "--jq", ".workflow_runs[0] // empty"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout_b, _ = await proc.communicate()
    if proc.returncode != 0:
        return {"status": "unknown", "conclusion": None, "url": None}
    out = stdout_b.decode("utf-8", errors="replace").strip()
    if not out:
        return {"status": "not_started", "conclusion": None, "url": None}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"status": "unknown", "conclusion": None, "url": None}
    return {
        "status": data.get("status") or "unknown",  # queued | in_progress | completed
        "conclusion": data.get("conclusion"),        # success | failure | cancelled | None
        "url": data.get("html_url"),
    }


async def wait_for_ghcr_tags(version: str, timeout_s: int = 600) -> bool:
    """Poll both the GitHub Actions publish workflows AND the GHCR
    registry for the three dev-tagged images. Returns True once every
    image is published on GHCR (the authoritative signal for downstream
    deploys). Workflow status is collected for the --web UI; a workflow
    failure short-circuits the wait so we don't sit out the full timeout.
    """
    head_sha = _head_sha()
    print(color(
        "build",
        f"==> Waiting for CI build (commit {head_sha[:7] or '?'}, tag {version}, "
        f"timeout {timeout_s}s) ...",
    ), flush=True)
    start = time.monotonic()
    published: set[str] = set()
    workflows: dict[str, dict[str, Any]] = {}
    last_progress = 0.0

    short_names = [img.rsplit("/", 1)[-1] for img in EXPECTED_IMAGES]

    def snapshot(phase: str) -> None:
        _write_state(LOG_ROOT / "build-state.json", {
            "version": version,
            "phase": phase,  # waiting | ready | failed
            "head_sha": head_sha[:7],
            "repo": GH_REPO,
            "started_at": start,
            "elapsed": time.monotonic() - start,
            "images_total": len(EXPECTED_IMAGES),
            "images_published": sorted(i.rsplit("/", 1)[-1] for i in published),
            "workflows": workflows,
        })

    snapshot("waiting")
    while True:
        # Poll workflows and GHCR tags together each round.
        wf_results = await asyncio.gather(*[
            _workflow_run(WORKFLOW_BY_IMAGE[n], head_sha) for n in short_names
        ])
        for name, result in zip(short_names, wf_results):
            workflows[name] = result

        tag_checks = await asyncio.gather(*[
            _tag_exists(img, version) for img in EXPECTED_IMAGES if img not in published
        ])
        for img, ok in zip([i for i in EXPECTED_IMAGES if i not in published], tag_checks):
            if ok:
                published.add(img)
                short = img.rsplit("/", 1)[-1]
                print(color(
                    "build",
                    f"[ghcr          ] ✔ {short}:{version} ({fmt_duration(time.monotonic() - start)})",
                ), flush=True)
        snapshot("waiting")

        if len(published) == len(EXPECTED_IMAGES):
            snapshot("ready")
            return True

        # Short-circuit on any workflow failure — image won't appear.
        failed = [
            n for n, w in workflows.items()
            if w.get("status") == "completed" and w.get("conclusion") not in (None, "success")
        ]
        if failed:
            print(color(
                "build",
                f"[ghcr          ] ✖ workflow(s) failed: {', '.join(failed)} — aborting wait",
            ), flush=True)
            snapshot("failed")
            return False

        elapsed = time.monotonic() - start
        if elapsed >= timeout_s:
            missing = [i.rsplit("/", 1)[-1] for i in EXPECTED_IMAGES if i not in published]
            print(color(
                "build",
                f"[ghcr          ] ✖ timed out after {fmt_duration(elapsed)}; "
                f"still missing: {', '.join(missing)}",
            ), flush=True)
            print(color(
                "build",
                "[ghcr          ]   hint: did you `git push` to develop? The publish-*.yml "
                "workflows only fire on develop pushes that change ha-addon/VERSION.",
            ), flush=True)
            snapshot("failed")
            return False

        # Status line every 30s so the terminal doesn't look frozen.
        # Include per-workflow status so the terminal mirrors what the
        # --web UI shows.
        if elapsed - last_progress >= 30:
            parts = []
            for n in short_names:
                if any(n in img for img in published):
                    parts.append(f"{n}:✔")
                else:
                    w = workflows.get(n, {})
                    status = w.get("status") or "pending"
                    concl = w.get("conclusion")
                    label = f"{status}" if not concl else f"{status}/{concl}"
                    parts.append(f"{n}:{label}")
            print(color(
                "build",
                f"[ghcr          ] ⧗ {'  '.join(parts)} ({fmt_duration(elapsed)})",
            ), flush=True)
            last_progress = elapsed

        await asyncio.sleep(10)


# ---------------------------------------------------------------------------
# Step 2: per-target chain — deploy → read token → playwright.
# ---------------------------------------------------------------------------

async def run_target_chain(target: Target, sem: asyncio.Semaphore | None) -> TargetResult:
    result = TargetResult(target=target.name)
    target_dir = LOG_ROOT / target.name
    target_dir.mkdir(parents=True, exist_ok=True)
    result.report_dir = target_dir / "playwright-report"
    deploy_log = target_dir / "deploy.log"
    test_log = target_dir / "playwright.log"
    state_file = target_dir / "state.json"

    target_start = time.monotonic()

    def snapshot(**overrides: Any) -> None:
        """Persist current target state for the --web UI."""
        _write_state(state_file, {
            "name": target.name,
            "url": target.base_url,
            "started_at": target_start,
            "deploy_ok": result.deploy_ok,
            "deploy_elapsed": result.deploy_elapsed or None,
            "tests_passed": result.tests_passed,
            "tests_total": result.tests_total,
            "tests_ok": result.tests_ok,
            "total_elapsed": time.monotonic() - target_start,
            "error": result.error,
            **overrides,
        })

    # -- Deploy ------------------------------------------------------------
    snapshot(phase="deploying")
    deploy_start = time.monotonic()
    code = await run_streaming(
        target.deploy_cmd,
        prefix=target.name,
        log_path=deploy_log,
        env=target.deploy_env,
        cwd=REPO_ROOT,
    )
    result.deploy_elapsed = time.monotonic() - deploy_start
    if code != 0:
        result.error = f"deploy exited {code} (see {deploy_log})"
        result.total_elapsed = time.monotonic() - target_start
        snapshot(phase="deploy-failed")
        return result
    result.deploy_ok = True
    snapshot(phase="testing")

    # -- Resolve the add-on token the deploy script just cached ------------
    token = ""
    if target.token_cache.exists():
        token = target.token_cache.read_text().strip()
    if not token:
        # Warn but don't abort — the suite can still exercise unauthed
        # paths. Any Bearer-gated test will surface its own failure.
        print(color(
            target.name,
            f"[{target.name:<14}] ⚠ no token at {target.token_cache} — Bearer-gated tests will 401",
        ), flush=True)

    # -- Playwright --------------------------------------------------------
    npm_env = {
        "FLEET_URL": target.base_url,
        "FLEET_TOKEN": token,
        # Per-target report dir so parallel runs don't collide.
        "PLAYWRIGHT_HTML_REPORT": str(result.report_dir),
        # JSON reporter output path for post-run collation.
        "PLAYWRIGHT_JSON_OUTPUT_NAME": str(target_dir / "results.json"),
    }
    npm_env.update(target.playwright_env)

    # npm run test:e2e:hass-4 -- <extra args>. The config auto-adds the
    # JSON reporter when PLAYWRIGHT_JSON_OUTPUT_NAME is set (which it is,
    # below), so we don't need a --reporter override.
    npm_cmd = ["npm", "run", "test:e2e:hass-4", "--"]
    npm_cmd += target.playwright_args

    if sem is None:
        code = await run_streaming(
            npm_cmd,
            prefix=target.name,
            log_path=test_log,
            env=npm_env,
            cwd=REPO_ROOT / "ha-addon" / "ui",
        )
    else:
        async with sem:
            code = await run_streaming(
                npm_cmd,
                prefix=target.name,
                log_path=test_log,
                env=npm_env,
                cwd=REPO_ROOT / "ha-addon" / "ui",
            )

    # -- Parse Playwright JSON --------------------------------------------
    results_json = target_dir / "results.json"
    if results_json.exists():
        try:
            data = json.loads(results_json.read_text())
            stats = data.get("stats", {})
            # Playwright's JSON reporter surfaces expected/unexpected counts.
            # tests_total = expected + unexpected + flaky + skipped.
            expected = stats.get("expected", 0)
            unexpected = stats.get("unexpected", 0)
            flaky = stats.get("flaky", 0)
            skipped = stats.get("skipped", 0)
            result.tests_passed = expected + flaky  # flaky still count as passed
            result.tests_total = expected + unexpected + flaky + skipped
            result.tests_ok = (code == 0)
        except (json.JSONDecodeError, OSError) as e:
            result.error = f"couldn't parse playwright results.json: {e}"
            result.tests_ok = False
    else:
        result.tests_ok = (code == 0)
        if not result.tests_ok:
            result.error = f"playwright exited {code} with no results.json (see {test_log})"

    result.total_elapsed = time.monotonic() - target_start
    snapshot(phase="done" if (result.deploy_ok and result.tests_ok) else "failed")
    return result


# ---------------------------------------------------------------------------
# Summary rendering.
# ---------------------------------------------------------------------------

def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def print_summary(results: list[TargetResult], targets: dict[str, Target]) -> None:
    print()
    print(f"{BOLD}===== Test matrix summary ====={RESET}" if sys.stdout.isatty() else "===== Test matrix summary =====")
    print()

    # Compute column widths.
    rows = []
    for r in results:
        if not r.deploy_ok:
            deploy_cell = "✖"
            tests_cell = "—"
        else:
            deploy_cell = f"✔ {fmt_duration(r.deploy_elapsed)}"
            if r.tests_ok and r.tests_total > 0:
                tests_cell = f"✔ {r.tests_passed}/{r.tests_total}"
            elif r.tests_total > 0:
                tests_cell = f"✖ {r.tests_passed}/{r.tests_total}"
            else:
                tests_cell = "✖"
        rows.append((
            r.target,
            deploy_cell,
            tests_cell,
            fmt_duration(r.total_elapsed),
            str(r.report_dir.relative_to(REPO_ROOT)) if r.report_dir else "",
        ))

    headers = ("Target", "Deploy", "Tests", "Elapsed", "Report")
    widths = [max(len(str(row[i])) for row in (rows + [headers])) for i in range(5)]

    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    print(line(headers))
    print(line(tuple("─" * w for w in widths)))
    for row in rows:
        print(line(row))

    print()
    print("Open:")
    for r in results:
        url = targets[r.target].base_url
        status = "✔" if (r.deploy_ok and r.tests_ok) else "✖"
        print(f"  {status} {r.target:<14}  {url}")

    # Per-target error lines for anything that failed. One line each so
    # the summary stays compact; the full log path is right there.
    errors = [r for r in results if r.error]
    if errors:
        print()
        print(f"{BOLD}Failures:{RESET}" if sys.stdout.isatty() else "Failures:")
        for r in errors:
            print(f"  {r.target}: {r.error}")

    print()


# ---------------------------------------------------------------------------
# --web HTTP server: serves a live status page + JSON feed the page polls.
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _read_target_states() -> list[dict[str, Any]]:
    if not LOG_ROOT.exists():
        return []
    states: list[dict[str, Any]] = []
    for d in sorted(LOG_ROOT.iterdir()):
        if not d.is_dir() or d.name == "build":
            continue
        sf = d / "state.json"
        if not sf.exists():
            continue
        try:
            states.append(json.loads(sf.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    return states


def _read_build_state() -> dict[str, Any]:
    sf = LOG_ROOT / "build-state.json"
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


_HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>test-matrix</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 0; background: #0f0f11; color: #e5e5e5; }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
  h1 { font: 600 16px/1 inherit; margin: 0 0 6px; letter-spacing: 0.02em; }
  .sub { color: #888; font-size: 12px; margin-bottom: 20px; }
  .sub .v { color: #aaa; }
  .sub .sep { color: #444; margin: 0 8px; }
  .card { background: #18181b; border: 1px solid #27272a; border-radius: 6px;
          padding: 14px 16px; margin-bottom: 16px; }
  .card h2 { font: 600 11px/1 inherit; color: #888; text-transform: uppercase;
             letter-spacing: 0.08em; margin: 0 0 10px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 7px 10px; text-align: left; border-bottom: 1px solid #27272a; }
  tr:last-child td { border-bottom: 0; }
  th { color: #888; font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }
  td.name { font-weight: 500; color: #e5e5e5; }
  td.url a { color: #60a5fa; text-decoration: none; }
  td.url a:hover { text-decoration: underline; }
  .phase { display: inline-block; padding: 2px 8px; border-radius: 10px;
           font-size: 11px; letter-spacing: 0.02em; }
  .phase-pending       { color: #a1a1aa; background: #27272a; }
  .phase-deploying     { color: #fde68a; background: #3f2d00; }
  .phase-testing       { color: #93c5fd; background: #1e3a5f; }
  .phase-waiting       { color: #fde68a; background: #3f2d00; }
  .phase-ready         { color: #86efac; background: #14532d; }
  .phase-done          { color: #86efac; background: #14532d; }
  .phase-failed        { color: #fca5a5; background: #5c1a1a; }
  .phase-deploy-failed { color: #fca5a5; background: #5c1a1a; }
  .ok   { color: #86efac; }
  .fail { color: #fca5a5; }
  .dim  { color: #666; }
  .progress { height: 4px; background: #27272a; border-radius: 2px; overflow: hidden; }
  .progress .fill { height: 100%; background: #60a5fa; transition: width 0.3s; }
  pre#output { background: #050506; padding: 14px; border-radius: 6px; border: 1px solid #27272a;
               max-height: 50vh; overflow: auto; white-space: pre-wrap; word-break: break-all;
               font: 12px/1.45 "SF Mono", Menlo, Consolas, monospace; margin: 0; }
  .disconnected { color: #fca5a5; margin-left: 6px; }
  .disconnected.ok { color: #666; }
</style>
</head>
<body>
<div class="wrap">
  <h1>test-matrix</h1>
  <div class="sub" id="sub">loading&hellip;</div>

  <div class="card">
    <h2>Build</h2>
    <div id="build-card">—</div>
  </div>

  <div class="card">
    <h2>Targets</h2>
    <table>
      <thead><tr><th>Target</th><th>Phase</th><th>Deploy</th><th>Tests</th><th>Elapsed</th><th>URL</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>

  <div class="card">
    <h2>Output <span id="conn" class="disconnected ok">live</span></h2>
    <pre id="output"></pre>
  </div>
</div>
<script>
  const fmtDur = (s) => {
    if (s == null) return '';
    if (s < 60) return Math.round(s) + 's';
    const m = Math.floor(s / 60), r = Math.round(s - m * 60);
    return m + 'm ' + String(r).padStart(2, '0') + 's';
  };
  const phaseLabel = (p) => p || 'pending';
  const deployCell = (t) => {
    if (t.deploy_ok === true)  return '<span class="ok">&#x2714; ' + fmtDur(t.deploy_elapsed) + '</span>';
    if (t.deploy_ok === false) return '<span class="fail">&#x2716;</span>';
    return '<span class="dim">&mdash;</span>';
  };
  const testsCell = (t) => {
    if (t.tests_total != null && t.tests_total > 0) {
      const cls = t.tests_ok === true ? 'ok' : (t.tests_ok === false ? 'fail' : '');
      const mark = t.tests_ok === true ? '&#x2714;' : (t.tests_ok === false ? '&#x2716;' : '');
      return '<span class="' + cls + '">' + mark + ' ' + t.tests_passed + '/' + t.tests_total + '</span>';
    }
    return '<span class="dim">&mdash;</span>';
  };

  async function tick() {
    try {
      const r = await fetch('/status.json', { cache: 'no-store' });
      const s = await r.json();
      document.getElementById('conn').classList.add('ok');
      document.getElementById('conn').textContent = 'live';

      const b = s.build || {};
      const subParts = [];
      if (b.version) subParts.push('<span class="v">' + b.version + '</span>');
      subParts.push((s.targets || []).length + ' targets');
      if (b.phase) subParts.push(b.phase);
      document.getElementById('sub').innerHTML = subParts.join('<span class="sep">&middot;</span>');

      let buildHtml;
      if (!b.phase) {
        buildHtml = '<span class="dim">pending&hellip;</span>';
      } else {
        const pct = b.images_total ? Math.round(100 * (b.images_published || []).length / b.images_total) : 0;
        buildHtml =
          '<div style="display:flex;align-items:center;gap:12px;">' +
          '<span class="phase phase-' + b.phase + '">' + b.phase + '</span>' +
          '<div style="flex:1;"><div class="progress"><div class="fill" style="width:' + pct + '%"></div></div></div>' +
          '<span class="dim">' + ((b.images_published || []).length) + '/' + (b.images_total || '?') + '</span>' +
          '<span class="dim">' + fmtDur(b.elapsed) + '</span>' +
          '</div>';
        if (b.head_sha) {
          buildHtml += '<div style="margin-top:6px;font-size:11px;color:#666;">commit ' + b.head_sha + '</div>';
        }
        // Per-workflow status table. The matrix polls the GitHub Actions
        // API for each publish workflow keyed on HEAD SHA; displayed
        // alongside the GHCR tag check so it's obvious when CI is
        // running vs when it simply hasn't started.
        const wf = b.workflows || {};
        const wfRows = Object.keys(wf).map(name => {
          const w = wf[name] || {};
          const status = w.status || 'pending';
          const concl = w.conclusion;
          const pubbed = (b.images_published || []).includes(name);
          // Derive a phase chip: published → done; otherwise map workflow states.
          let chipPhase = 'pending';
          if (pubbed || concl === 'success') chipPhase = 'done';
          else if (concl && concl !== 'success') chipPhase = 'failed';
          else if (status === 'in_progress') chipPhase = 'testing';
          else if (status === 'queued') chipPhase = 'waiting';
          else if (status === 'not_started') chipPhase = 'pending';
          const label = concl ? status + ' / ' + concl : status;
          const link = w.url ? ' <a href="' + w.url + '" target="_blank" style="font-size:11px;">run&#x2197;</a>' : '';
          const pubMark = pubbed ? ' <span class="ok">&#x2714; on ghcr</span>' : '';
          return '<tr>' +
            '<td class="name" style="font-size:12px;">' + name + '</td>' +
            '<td><span class="phase phase-' + chipPhase + '">' + label + '</span></td>' +
            '<td style="font-size:11px; color:#888;">' + link + pubMark + '</td>' +
          '</tr>';
        }).join('');
        if (wfRows) {
          buildHtml += '<table style="margin-top:10px;font-size:12px;">' +
            '<thead><tr><th>Image</th><th>Workflow</th><th></th></tr></thead>' +
            '<tbody>' + wfRows + '</tbody></table>';
        }
      }
      document.getElementById('build-card').innerHTML = buildHtml;

      const rows = (s.targets || []).map(t => {
        const phase = phaseLabel(t.phase);
        return '<tr>' +
          '<td class="name">' + t.name + '</td>' +
          '<td><span class="phase phase-' + phase + '">' + phase + '</span></td>' +
          '<td>' + deployCell(t) + '</td>' +
          '<td>' + testsCell(t) + '</td>' +
          '<td>' + fmtDur(t.total_elapsed) + '</td>' +
          '<td class="url">' + (t.url ? '<a href="' + t.url + '" target="_blank">' + t.url + '</a>' : '') + '</td>' +
        '</tr>';
      }).join('');
      document.getElementById('rows').innerHTML = rows || '<tr><td colspan="6" class="dim">no targets yet</td></tr>';

      const out = document.getElementById('output');
      const pinned = out.scrollHeight - out.scrollTop - out.clientHeight < 60;
      out.textContent = (s.output || []).join('\\n');
      if (pinned) out.scrollTop = out.scrollHeight;
    } catch (e) {
      document.getElementById('conn').classList.remove('ok');
      document.getElementById('conn').textContent = 'disconnected';
    }
  }
  setInterval(tick, 1500);
  tick();
</script>
</body>
</html>
"""


class _StatusHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (http.server convention)
        if self.path == "/" or self.path == "/index.html":
            body = _HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/status.json":
            with _output_lock:
                lines = [_strip_ansi(line) for line in _output_lines]
            payload = {
                "build": _read_build_state(),
                "targets": _read_target_states(),
                "output": lines,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Suppress default BaseHTTPRequestHandler access logging; the matrix
        # already has plenty of output.
        return


def start_web_server(port: int) -> None:
    """Start the status server on a background daemon thread."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(color("build", f"==> Web UI: http://localhost:{port}/"), flush=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def run(args: argparse.Namespace) -> int:
    version = VERSION_FILE.read_text().strip()
    all_targets = make_targets(version)

    if args.list:
        print("Available targets:")
        for name, t in all_targets.items():
            print(f"  {name:<16} {t.base_url}")
        return 0

    if args.targets:
        names = [n.strip() for n in args.targets.split(",")]
        unknown = [n for n in names if n not in all_targets]
        if unknown:
            sys.stderr.write(f"Unknown target(s): {', '.join(unknown)}\n")
            sys.stderr.write(f"Available: {', '.join(all_targets)}\n")
            return 2
    else:
        names = list(all_targets)

    selected = {n: all_targets[n] for n in names}

    print(color("build", f"==> test-matrix.py v{version}  targets: {', '.join(names)}"), flush=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)

    # -- Wait for CI-published images ----------------------------------
    if not args.no_wait:
        ok = await wait_for_ghcr_tags(version, timeout_s=args.wait_timeout)
        if not ok:
            sys.stderr.write(
                "GHCR tags not available — skipping all target deploys.\n"
            )
            return 1

    # -- Run target chains ----------------------------------------------
    # Deploy always parallel. Playwright parallel by default; --seq-tests
    # serializes Playwright to one target at a time (escape hatch for
    # memory pressure). Implemented via a shared semaphore that only the
    # Playwright step inside each chain acquires.
    test_sem = asyncio.Semaphore(1) if args.seq_tests else None

    start = time.monotonic()
    results = await asyncio.gather(
        *[run_target_chain(t, test_sem) for t in selected.values()],
    )
    print(color("build", f"==> All targets done in {fmt_duration(time.monotonic() - start)}"), flush=True)

    # -- Summary --------------------------------------------------------
    print_summary(results, selected)

    # Exit code = non-zero if ANY target failed.
    return 0 if all(r.deploy_ok and r.tests_ok for r in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See dev-plans/HOME-LAB.md for target infrastructure.",
    )
    parser.add_argument(
        "--targets",
        help="Comma-separated target names (default: all). See --list.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Skip the GHCR-tag wait and go straight to deploy. Useful when "
             "you know the CI publish workflows have already finished.",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=600,
        help="Seconds to wait for GHCR tags to appear (default: 600 = 10min).",
    )
    parser.add_argument(
        "--seq-tests",
        action="store_true",
        help="Run Playwright one target at a time (deploys still parallel).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available targets and exit.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch a local HTTP server that streams live progress to "
             "a browser (see --web-port). Server stays up after the run "
             "finishes so the final state remains viewable until Ctrl-C.",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8099,
        help="Port for --web (default 8099).",
    )
    args = parser.parse_args()

    preflight(skip_wait=args.no_wait or args.list)

    # Tee stdout into the ring buffer so the --web server can replay it.
    # Safe to do unconditionally — cost is one deque append per line.
    sys.stdout = _TeeStdout(sys.stdout)  # type: ignore[assignment]

    if args.web and not args.list:
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        _clear_state_dir()
        start_web_server(args.web_port)

    try:
        rc = asyncio.run(run(args))
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        return 130

    if args.web and not args.list:
        print(color("build", f"==> Web UI still at http://localhost:{args.web_port}/  (Ctrl-C to exit)"), flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass

    return rc


if __name__ == "__main__":
    sys.exit(main())
