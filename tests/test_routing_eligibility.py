"""TG.3 wiring — :mod:`routing_eligibility.re_evaluate_routing` integrates the
queue + registry + scanner against the routing rule store.

These tests stand up a synthetic aiohttp Application with the same app
keys main.py wires up, then drive the sweep directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web

from job_queue import Job, JobQueue, JobState
from registry import WorkerRegistry
from routing import Clause, Rule, RoutingRuleStore
from routing_eligibility import re_evaluate_routing


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    return d


def _write_yaml(d: Path, target: str, *, tags: list[str] | None = None,
                routing_extra: list[dict] | None = None) -> None:
    """Write a minimal YAML with an `# esphome-fleet:` metadata block."""
    lines = ["# esphome-fleet:"]
    if tags is not None:
        lines.append(f"#   tags: {','.join(tags)}")
    if routing_extra is not None:
        # Embed YAML for routing_extra inside the comment block.
        import yaml as _y
        rendered = _y.dump({"routing_extra": routing_extra}, default_flow_style=False).rstrip()
        for line in rendered.splitlines():
            lines.append(f"#   {line}")
    lines.append("")
    lines.append("esphome:")
    lines.append(f"  name: {target.replace('.yaml', '')}")
    (d / target).write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _make_app(tmp_path: Path, config_dir: Path) -> web.Application:
    """Stand up a minimal app with the keys re_evaluate_routing reads."""
    from app_config import AppConfig
    app = web.Application()
    app["config"] = AppConfig(config_dir=str(config_dir), port=0)
    app["queue"] = JobQueue(queue_file=tmp_path / "queue.json")
    app["registry"] = WorkerRegistry()
    app["routing_rule_store"] = RoutingRuleStore(path=tmp_path / "routing-rules.json")
    return app


async def _enqueue(app: web.Application, target: str = "kitchen.yaml") -> Job:
    job = await app["queue"].enqueue(
        target=target,
        esphome_version="2026.3.2",
        run_id="r1",
        timeout_seconds=300,
    )
    assert job is not None
    return job


def _add_worker(app: web.Application, *, hostname: str, tags: list[str]) -> str:
    """Register a worker into the in-memory registry, return client_id."""
    cid = app["registry"].register(
        hostname=hostname,
        platform="linux",
        client_version="dev",
        max_parallel_jobs=2,
        system_info=None,
        tags=tags,
    )
    return cid


# ---------------------------------------------------------------------------
# Empty/no-op cases
# ---------------------------------------------------------------------------


async def test_re_eval_no_rules_no_op(tmp_path: Path, config_dir: Path) -> None:
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "kitchen.yaml", tags=["kitchen"])
    _add_worker(app, hostname="w1", tags=["kitchen"])
    job = await _enqueue(app, "kitchen.yaml")
    assert job.state == JobState.PENDING

    changed = await re_evaluate_routing(app)
    assert changed == 0
    assert job.state == JobState.PENDING


async def test_re_eval_skips_terminal_jobs(tmp_path: Path, config_dir: Path) -> None:
    """SUCCESS / FAILED / CANCELLED jobs aren't touched even if a rule would block."""
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "k.yaml", tags=["kitchen"])
    job = await _enqueue(app, "k.yaml")
    job.state = JobState.SUCCESS

    # Add a rule that would otherwise block this device.
    app["routing_rule_store"].create_rule(Rule(
        id="kitchen-only",
        name="Kitchen only",
        severity="required",
        device_match=[Clause(op="all_of", tags=["kitchen"])],
        worker_match=[Clause(op="all_of", tags=["nonexistent"])],
    ))

    changed = await re_evaluate_routing(app)
    assert changed == 0
    assert job.state == JobState.SUCCESS


# ---------------------------------------------------------------------------
# PENDING → BLOCKED transitions
# ---------------------------------------------------------------------------


async def test_re_eval_pending_to_blocked_when_no_eligible_worker(
    tmp_path: Path, config_dir: Path,
) -> None:
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "kitchen.yaml", tags=["kitchen"])
    # Worker exists but lacks the required "kitchen" tag.
    _add_worker(app, hostname="w1", tags=["office"])
    job = await _enqueue(app, "kitchen.yaml")

    app["routing_rule_store"].create_rule(Rule(
        id="kitchen-only",
        name="Kitchen build only",
        severity="required",
        device_match=[Clause(op="all_of", tags=["kitchen"])],
        worker_match=[Clause(op="all_of", tags=["kitchen"])],
    ))

    changed = await re_evaluate_routing(app)
    assert changed == 1
    assert job.state == JobState.BLOCKED
    assert job.blocked_reason is not None
    assert job.blocked_reason["rule_id"] == "kitchen-only"
    assert job.blocked_reason["rule_name"] == "Kitchen build only"
    assert "kitchen" in job.blocked_reason["summary"]


async def test_re_eval_blocked_to_pending_when_eligible_worker_arrives(
    tmp_path: Path, config_dir: Path,
) -> None:
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "kitchen.yaml", tags=["kitchen"])
    _add_worker(app, hostname="office-only", tags=["office"])
    job = await _enqueue(app, "kitchen.yaml")
    app["routing_rule_store"].create_rule(Rule(
        id="kitchen-only",
        name="Kitchen build only",
        severity="required",
        device_match=[Clause(op="all_of", tags=["kitchen"])],
        worker_match=[Clause(op="all_of", tags=["kitchen"])],
    ))
    # First sweep blocks.
    await re_evaluate_routing(app)
    assert job.state == JobState.BLOCKED

    # A new eligible worker registers.
    _add_worker(app, hostname="kitchen-w", tags=["kitchen"])

    changed = await re_evaluate_routing(app)
    assert changed == 1
    assert job.state == JobState.PENDING
    assert job.blocked_reason is None


async def test_re_eval_idempotent_on_steady_state(
    tmp_path: Path, config_dir: Path,
) -> None:
    """Sequential sweeps don't churn — second call sees zero changes."""
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "kitchen.yaml", tags=["kitchen"])
    _add_worker(app, hostname="w", tags=["office"])
    await _enqueue(app, "kitchen.yaml")
    app["routing_rule_store"].create_rule(Rule(
        id="kitchen-only",
        name="Kitchen build only",
        severity="required",
        device_match=[Clause(op="all_of", tags=["kitchen"])],
        worker_match=[Clause(op="all_of", tags=["kitchen"])],
    ))

    first = await re_evaluate_routing(app)
    second = await re_evaluate_routing(app)
    assert first == 1
    assert second == 0


# ---------------------------------------------------------------------------
# Per-device routing_extra
# ---------------------------------------------------------------------------


async def test_re_eval_honours_per_device_routing_extra(
    tmp_path: Path, config_dir: Path,
) -> None:
    """A device's own additive rule blocks even when the global list is empty."""
    app = await _make_app(tmp_path, config_dir)
    # Device demands a worker tagged "fast" via per-device routing_extra.
    _write_yaml(
        config_dir,
        "kitchen.yaml",
        tags=["kitchen"],
        routing_extra=[{
            "name": "needs fast",
            "device_match": [{"op": "all_of", "tags": ["kitchen"]}],
            "worker_match": [{"op": "all_of", "tags": ["fast"]}],
        }],
    )
    # Worker has kitchen but not fast.
    _add_worker(app, hostname="slow-kitchen", tags=["kitchen"])
    job = await _enqueue(app, "kitchen.yaml")

    changed = await re_evaluate_routing(app)
    assert changed == 1
    assert job.state == JobState.BLOCKED
    assert job.blocked_reason is not None
    assert job.blocked_reason["rule_name"] == "needs fast"


# ---------------------------------------------------------------------------
# Offline-worker handling
# ---------------------------------------------------------------------------


async def test_re_eval_ignores_offline_workers(
    tmp_path: Path, config_dir: Path,
) -> None:
    """An offline worker can't unblock a job, even if its tags would match."""
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "kitchen.yaml", tags=["kitchen"])
    cid = _add_worker(app, hostname="kitchen-w", tags=["kitchen"])
    job = await _enqueue(app, "kitchen.yaml")
    app["routing_rule_store"].create_rule(Rule(
        id="kitchen-only",
        name="Kitchen build only",
        severity="required",
        device_match=[Clause(op="all_of", tags=["kitchen"])],
        worker_match=[Clause(op="all_of", tags=["kitchen"])],
    ))

    # Force the worker offline by backdating its last_seen past the
    # default 30 s threshold.
    w = app["registry"].get(cid)
    assert w is not None
    from datetime import timedelta
    w.last_seen = w.last_seen - timedelta(seconds=120)

    changed = await re_evaluate_routing(app)
    assert changed == 1
    assert job.state == JobState.BLOCKED


# ---------------------------------------------------------------------------
# Bug #95 — build_claim_eligibility: per-worker predicate for claim_next
# ---------------------------------------------------------------------------


async def test_build_claim_eligibility_no_rules_short_circuits(
    tmp_path: Path, config_dir: Path,
) -> None:
    """When no global rules and no routing_extra exist, every worker is
    eligible for every job — the predicate must return True without
    touching the YAML metadata block (the cache walks `_resolve` only
    when needed)."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "kitchen.yaml", tags=["kitchen"])
    job = await _enqueue(app, "kitchen.yaml")

    check = build_claim_eligibility(app, worker_tags=["any"])
    assert check(job) is True


async def test_build_claim_eligibility_rejects_ineligible_worker(
    tmp_path: Path, config_dir: Path,
) -> None:
    """The reproduction of the user-reported bug: the rule says ratgdo
    devices need a ``windows``-tagged worker; a debian worker calling
    claim_next must be told no."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "garage-door-big.yaml", tags=["ratgdo"])
    job = await _enqueue(app, "garage-door-big.yaml")
    app["routing_rule_store"].create_rule(Rule(
        id="garage-rule",
        name="Garage doors on Windows",
        severity="required",
        device_match=[Clause(op="any_of", tags=["ratgdo"])],
        worker_match=[Clause(op="all_of", tags=["windows"])],
    ))

    debian_check = build_claim_eligibility(app, worker_tags=["debian"])
    assert debian_check(job) is False

    windows_check = build_claim_eligibility(app, worker_tags=["windows"])
    assert windows_check(job) is True


async def test_build_claim_eligibility_honours_routing_extra(
    tmp_path: Path, config_dir: Path,
) -> None:
    """Per-device additive rule (``routing_extra`` in the YAML metadata
    block) must also gate the per-worker claim — same composition rule
    re_evaluate_routing follows."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    # No global rules; the per-device routing_extra alone constrains.
    _write_yaml(
        config_dir, "garage-door-big.yaml",
        tags=["ratgdo"],
        routing_extra=[{
            "id": "extra1",
            "name": "Per-device rule",
            "severity": "required",
            "device_match": [{"op": "any_of", "tags": ["ratgdo"]}],
            "worker_match": [{"op": "all_of", "tags": ["windows"]}],
        }],
    )
    job = await _enqueue(app, "garage-door-big.yaml")

    debian_check = build_claim_eligibility(app, worker_tags=["debian"])
    assert debian_check(job) is False

    windows_check = build_claim_eligibility(app, worker_tags=["windows"])
    assert windows_check(job) is True


async def test_build_claim_eligibility_caches_target_meta_within_call(
    tmp_path: Path, config_dir: Path,
) -> None:
    """A single claim_next call may iterate many PENDING jobs; the
    closure cache must avoid re-reading the same target's YAML for
    each one. We assert the cache by counting ``read_device_meta``
    calls via monkeypatch."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "garage-door-big.yaml", tags=["ratgdo"])
    app["routing_rule_store"].create_rule(Rule(
        id="r", name="r", severity="required",
        device_match=[Clause(op="any_of", tags=["ratgdo"])],
        worker_match=[Clause(op="all_of", tags=["windows"])],
    ))

    job = await _enqueue(app, "garage-door-big.yaml")

    import scanner
    call_count = {"n": 0}
    real = scanner.read_device_meta

    def counting(*args, **kwargs):
        call_count["n"] += 1
        return real(*args, **kwargs)

    # build_claim_eligibility does ``from scanner import read_device_meta``
    # inside the closure each call; patch the scanner module attribute so
    # the rebound name resolves to our counter.
    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(scanner, "read_device_meta", counting)
    try:
        check = build_claim_eligibility(app, worker_tags=["debian"])
        assert check(job) is False
        # Second evaluation against the same target — cache must hit.
        assert check(job) is False
    finally:
        monkeypatch.undo()

    assert call_count["n"] == 1, \
        f"read_device_meta called {call_count['n']} times for one target — cache miss"


# ---------------------------------------------------------------------------
# Bug #97 — per-job worker_tag_filter
# ---------------------------------------------------------------------------


async def test_build_claim_eligibility_honours_job_worker_tag_filter(
    tmp_path: Path, config_dir: Path,
) -> None:
    """A job created with ``worker_tag_filter`` is only claimable by a
    worker whose tags satisfy the clause — independent of any global
    routing rules. This is the data path behind the Upgrade modal's
    "Tag expression" worker-selection radio."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "anything.yaml")
    job = await app["queue"].enqueue(
        target="anything.yaml",
        esphome_version="2026.3.2",
        run_id="r1",
        timeout_seconds=300,
        worker_tag_filter={"op": "all_of", "tags": ["windows"]},
    )
    assert job is not None

    debian_check = build_claim_eligibility(app, worker_tags=["debian"])
    assert debian_check(job) is False

    windows_check = build_claim_eligibility(app, worker_tags=["windows"])
    assert windows_check(job) is True


async def test_worker_tag_filter_clause_ops(
    tmp_path: Path, config_dir: Path,
) -> None:
    """Each clause op behaves as expected: any_of, none_of, all_of."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "thing.yaml")

    async def _job_with(filter_):
        j = await app["queue"].enqueue(
            target="thing.yaml",
            esphome_version="x",
            run_id=f"r-{filter_['op']}-{','.join(filter_['tags'])}",
            timeout_seconds=300,
            worker_tag_filter=filter_,
        )
        # Coalescing returns None on the second enqueue for the same
        # target while the first is still PENDING. Mark the previous
        # job claimed so the next enqueue creates a fresh one.
        if j is None:
            for existing in app["queue"].get_all():
                if existing.target == "thing.yaml" and existing.state == JobState.PENDING:
                    existing.state = JobState.WORKING
            j = await app["queue"].enqueue(
                target="thing.yaml",
                esphome_version="x",
                run_id="retry",
                timeout_seconds=300,
                worker_tag_filter=filter_,
            )
        assert j is not None
        return j

    job_any = await _job_with({"op": "any_of", "tags": ["windows", "macos"]})
    check = build_claim_eligibility(app, worker_tags=["macos"])
    assert check(job_any) is True

    job_none = await _job_with({"op": "none_of", "tags": ["slow"]})
    check = build_claim_eligibility(app, worker_tags=["slow"])
    assert check(job_none) is False
    check = build_claim_eligibility(app, worker_tags=["fast"])
    assert check(job_none) is True


async def test_worker_tag_filter_malformed_is_permissive(
    tmp_path: Path, config_dir: Path,
) -> None:
    """A malformed filter (unknown op, empty tag list, non-list tags)
    is treated as 'no constraint' so the job doesn't strand."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "thing.yaml")
    job = await app["queue"].enqueue(
        target="thing.yaml",
        esphome_version="x",
        run_id="r",
        timeout_seconds=300,
        worker_tag_filter={"op": "garbage", "tags": ["windows"]},
    )
    assert job is not None
    check = build_claim_eligibility(app, worker_tags=["debian"])
    assert check(job) is True


# ---------------------------------------------------------------------------
# Bug #98 — should_defer must not strand a job by deferring to an
# ineligible higher-perf worker
# ---------------------------------------------------------------------------


async def test_eligibility_isolates_stalemate_when_only_one_worker_qualifies(
    tmp_path: Path, config_dir: Path,
) -> None:
    """Reproduces the live hass-4 stalemate: one rule disqualifies all
    workers except OPTIPLEX-7, but the perf-based scheduler kept
    deferring OPTIPLEX-7 to faster macos workers that were ineligible.
    The fix lives in api.py (it filters the deferral candidate list by
    routing eligibility) — but the underlying predicate must give the
    handler a clean signal: when this is the only eligible job, the
    other workers' eligibility predicates must all return False."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "garage-door-big.yaml", tags=["ratgdo"])
    job = await _enqueue(app, "garage-door-big.yaml")
    app["routing_rule_store"].create_rule(Rule(
        id="windows-only",
        name="Garage Doors on Windows",
        severity="required",
        device_match=[Clause(op="any_of", tags=["ratgdo"])],
        worker_match=[Clause(op="all_of", tags=["windows"])],
    ))

    # Build an eligibility predicate per worker tag set. The scheduler
    # would have used these to filter "other" workers in the
    # should_defer loop. None of the non-windows workers should be
    # eligible — that's exactly what the api.py-side fix relies on.
    windows_check = build_claim_eligibility(app, worker_tags=["windows"])
    macos_check = build_claim_eligibility(app, worker_tags=["macos"])
    debian_check = build_claim_eligibility(app, worker_tags=["debian"])

    assert windows_check(job) is True
    assert macos_check(job) is False
    assert debian_check(job) is False


# ---------------------------------------------------------------------------
# Bug #110 — bypass_routing_rules per-job override
# ---------------------------------------------------------------------------


async def test_bypass_routing_rules_clears_block_in_re_eval(
    tmp_path: Path, config_dir: Path,
) -> None:
    """A job with ``bypass_routing_rules=True`` must never go BLOCKED in
    the fleet-wide re-eval sweep, even when the active rule disqualifies
    every online worker."""
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "garage.yaml", tags=["ratgdo"])
    _add_worker(app, hostname="macdaddy", tags=["macos"])
    app["routing_rule_store"].create_rule(Rule(
        id="windows-only",
        name="Garage Doors on Windows",
        severity="required",
        device_match=[Clause(op="any_of", tags=["ratgdo"])],
        worker_match=[Clause(op="all_of", tags=["windows"])],
    ))
    # Without the override, the job would flip to BLOCKED on re-eval.
    job = await _enqueue(app, "garage.yaml")
    job.bypass_routing_rules = True
    changed = await re_evaluate_routing(app)
    # No change because the job is allowed to stay PENDING.
    assert changed == 0
    assert job.state == JobState.PENDING
    assert job.blocked_reason is None


async def test_bypass_routing_rules_lets_ineligible_worker_claim(
    tmp_path: Path, config_dir: Path,
) -> None:
    """Per-worker claim_next predicate ignores routing rules when
    ``bypass_routing_rules`` is set, but still honours the user's
    explicit ``worker_tag_filter`` constraint."""
    from routing_eligibility import build_claim_eligibility
    app = await _make_app(tmp_path, config_dir)
    _write_yaml(config_dir, "garage.yaml", tags=["ratgdo"])
    app["routing_rule_store"].create_rule(Rule(
        id="windows-only",
        name="Garage Doors on Windows",
        severity="required",
        device_match=[Clause(op="any_of", tags=["ratgdo"])],
        worker_match=[Clause(op="all_of", tags=["windows"])],
    ))

    job = await _enqueue(app, "garage.yaml")
    macos_check = build_claim_eligibility(app, worker_tags=["macos"])
    # Without bypass: macOS worker is rejected by the rule.
    assert macos_check(job) is False
    # With bypass: macOS worker is now allowed to claim.
    job.bypass_routing_rules = True
    macos_check = build_claim_eligibility(app, worker_tags=["macos"])
    assert macos_check(job) is True

    # Bypass does NOT override an explicit user tag filter — the
    # filter is the user's other constraint, not the rule's.
    job.worker_tag_filter = {"op": "all_of", "tags": ["linux"]}
    macos_check = build_claim_eligibility(app, worker_tags=["macos"])
    assert macos_check(job) is False
    # Linux worker satisfies both the (bypassed) rule and the filter.
    linux_check = build_claim_eligibility(app, worker_tags=["linux"])
    assert linux_check(job) is True


def test_bypass_field_round_trips_through_to_dict(tmp_path: Path) -> None:
    """``bypass_routing_rules`` survives a queue persist/load cycle."""
    q = JobQueue(queue_file=tmp_path / "queue.json")
    job = Job(
        id="job-1",
        target="kitchen.yaml",
        esphome_version="2026.3.2",
        state=JobState.PENDING,
        run_id="r1",
        bypass_routing_rules=True,
    )
    d = job.to_dict()
    assert d["bypass_routing_rules"] is True
    revived = Job.from_dict(d)
    assert revived.bypass_routing_rules is True
    # Persisted shape: a fresh queue load picks up the flag.
    q._jobs[job.id] = job
    q._persist()
    q2 = JobQueue(queue_file=tmp_path / "queue.json")
    q2.load()
    assert q2._jobs[job.id].bypass_routing_rules is True
