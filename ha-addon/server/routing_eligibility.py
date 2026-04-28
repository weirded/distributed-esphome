"""TG.3 wiring — the bridge between the routing-rule data model
(:mod:`routing`) and the live queue / registry / config-dir state.

The pure evaluator in :mod:`routing` knows nothing about the running app;
this module wires it up:

* :func:`re_evaluate_routing` — call after any state change that might
  shift a job between PENDING and BLOCKED. Triggers: job enqueue, worker
  register/deregister, worker tag update, rule create/update/delete, and
  a defensive 30-s watchdog.
* :func:`routing_watchdog` — long-running background task that calls
  :func:`re_evaluate_routing` every 30 s as a backstop against missed
  triggers (race during restart, clock skew, etc.).

Idempotent: a re-eval that finds every job already in the right state is
cheap (one read per online worker, one ``read_device_meta`` per job).
The hot path stays a pure tag-set walk.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Iterable

from routing import (
    Rule,
    RoutingRuleError,
    _clause_from_dict,
    find_blocking_rule,
    is_eligible,
)

if TYPE_CHECKING:
    from aiohttp import web

    from job_queue import Job, JobQueue
    from registry import WorkerRegistry
    from routing import RoutingRuleStore

    EligibilityPredicate = Callable[[Job], bool]

logger = logging.getLogger(__name__)


def _device_routing_extra(meta: dict) -> list[Rule]:
    """Parse a device's per-YAML ``routing_extra`` block into Rule objects.

    The YAML metadata comment block stores rules as plain dict-shaped
    lists; we round-trip them through :func:`_clause_from_dict` to get
    the same validation the global store applies. Malformed entries are
    dropped with a warning rather than poisoning the eligibility check.
    """
    extra_raw = meta.get("routing_extra")
    if not isinstance(extra_raw, list):
        return []
    out: list[Rule] = []
    for r in extra_raw:
        if not isinstance(r, dict):
            continue
        try:
            rule = Rule(
                id=str(r.get("id") or ""),
                name=str(r.get("name") or ""),
                # Per-device additive rules don't need a global id; the
                # severity defaults to "required" matching the global
                # store contract. The pure evaluator doesn't read id.
                severity=r.get("severity") or "required",
                device_match=[_clause_from_dict(c) for c in (r.get("device_match") or [])],
                worker_match=[_clause_from_dict(c) for c in (r.get("worker_match") or [])],
            )
            out.append(rule)
        except RoutingRuleError as exc:
            logger.warning("dropping malformed routing_extra rule: %s", exc)
    return out


def _device_tags_from_meta(meta: dict) -> list[str]:
    """Extract the device's tag list from the YAML metadata block.

    Stored as a comma-joined string; normalised to a list of trimmed
    non-empty strings. Returns an empty list when no tags key is set.
    """
    raw = meta.get("tags")
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []


async def re_evaluate_routing(app: "web.Application") -> int:
    """Sweep PENDING + BLOCKED jobs against the current routing rules.

    Returns the number of jobs whose state changed. Logs a single info
    line on a non-zero result; quiet otherwise (this fires from many
    triggers, including 1-Hz heartbeats).

    Skips entirely when no routing rules are defined globally — the
    common-case fleet has no rules, and re-eval is a guaranteed no-op.
    Per-device ``routing_extra`` is checked lazily inside the
    eligibility callback so a rule-free fleet doesn't pay
    ``read_device_meta`` per job on every heartbeat.
    """
    queue: "JobQueue | None" = app.get("queue")
    registry: "WorkerRegistry | None" = app.get("registry")
    rule_store: "RoutingRuleStore | None" = app.get("routing_rule_store")
    cfg = app.get("config")
    if queue is None or registry is None or rule_store is None or cfg is None:
        return 0

    global_rules = rule_store.list_rules()

    # Resolve once per re-eval call (not per job): which workers are
    # online + their current tag lists. The registry already gives us
    # the live list; tags live on the Worker record (TG.1). We feed the
    # callback only the *online* set — an offline worker is not a
    # candidate even if its tags would otherwise satisfy a rule.
    from settings import get_settings  # noqa: PLC0415
    threshold = int(get_settings().worker_offline_threshold)
    online_worker_tags: list[list[str]] = []
    for w in registry.get_all():
        if not registry.is_online(w.client_id, threshold_secs=threshold):
            continue
        # Disabled workers aren't claim candidates, so they can't unblock a job.
        if getattr(w, "disabled", False):
            continue
        online_worker_tags.append(list(w.tags or []))

    # Cache of (target -> (device_tags, effective_rules)) so jobs for the
    # same target only do one read_device_meta per re-eval pass.
    from scanner import read_device_meta  # noqa: PLC0415
    cache: dict[str, tuple[list[str], list[Rule]]] = {}

    def _resolve_target(target: str) -> tuple[list[str], list[Rule]]:
        cached = cache.get(target)
        if cached is not None:
            return cached
        try:
            meta = read_device_meta(cfg.config_dir, target)
        except Exception:
            logger.debug("read_device_meta failed for %s", target, exc_info=True)
            meta = {}
        device_tags = _device_tags_from_meta(meta)
        effective = global_rules + _device_routing_extra(meta)
        cache[target] = (device_tags, effective)
        return device_tags, effective

    def check(job: "Job") -> tuple[bool, dict | None]:
        # Bug #110: a job whose enqueuer explicitly chose to override
        # routing rules is never BLOCKED by them. Per-worker
        # ``worker_tag_filter`` and ``pinned_client_id`` still apply
        # (those are the user's explicit constraint, not a rule).
        if getattr(job, "bypass_routing_rules", False):
            return (True, None)
        device_tags, effective = _resolve_target(job.target)
        if not effective:
            return (True, None)  # no rules apply → always eligible
        if not online_worker_tags:
            # No online worker at all → blocked by *something*; surface
            # the first applicable rule so the tooltip has content.
            for rule in effective:
                # If even one rule applies to this device, it's the
                # blocker (no candidates means no one passes).
                from routing import _matches_side  # noqa: PLC0415
                if _matches_side(rule.device_match, set(device_tags)):
                    return (False, {
                        "rule_id": rule.id,
                        "rule_name": rule.name or "(unnamed rule)",
                        "summary": "no workers online",
                    })
            return (True, None)  # no applicable rule
        return find_blocking_rule(device_tags, online_worker_tags, effective)

    try:
        changed = await queue.re_evaluate_routing(check)
    except Exception:
        logger.exception("re_evaluate_routing sweep failed")
        return 0

    if changed:
        logger.info("Routing re-eval: %d job state change(s)", changed)
        # Let the UI refresh its Queue tab without waiting for the 1-Hz
        # SWR poll — the BLOCKED→PENDING transition (and vice versa) is
        # interactive feedback the user has been waiting for.
        try:
            from ui_api import _broadcast_ws  # noqa: PLC0415
            _broadcast_ws("queue_changed")
        except Exception:
            logger.debug("queue_changed broadcast failed", exc_info=True)
    return changed


async def routing_watchdog(app: "web.Application") -> None:
    """Backstop watchdog — re-evaluate routing every 30 s.

    Defence-in-depth against missed triggers (e.g. a registry mutation
    path that forgets to fire :func:`re_evaluate_routing`, or a worker
    that goes offline without deregistering — there's no event for that,
    only the heartbeat-threshold check).

    Idempotent — when the explicit triggers are doing their job, this
    sees zero state changes and stays quiet.
    """
    while True:
        await asyncio.sleep(30)
        try:
            await re_evaluate_routing(app)
        except Exception:
            logger.exception("routing watchdog failed")


def fire_and_forget(app: "web.Application") -> None:
    """Schedule a re-evaluation on the running event loop without awaiting.

    Use from sync paths (registry mutations) and from API handlers where
    the response shouldn't block on the sweep. The sweep itself is fast
    (microseconds for an empty rule list, sub-ms for a typical fleet);
    fire-and-forget is the right shape because the caller has no useful
    return value either way.

    Skips entirely when the app has no routing rules registered — saves
    every heartbeat / register / enqueue site from spawning a no-op task.
    """
    rule_store: "RoutingRuleStore | None" = app.get("routing_rule_store")
    if rule_store is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # not in an event loop (sync test harness, etc.)
    # Skip the spawn when there are no global rules AND no jobs in
    # PENDING/BLOCKED — the sweep would be a guaranteed no-op. We can't
    # cheaply tell whether any device has routing_extra without reading
    # every YAML, so when global_rules is non-empty we always sweep.
    if not rule_store.list_rules():
        # Still need to sweep when there *are* BLOCKED jobs — they may be
        # blocked from a now-deleted rule and need rescuing.
        queue = app.get("queue")
        if queue is None:
            return
        # Cheap state probe avoids an empty-sweep spawn for the
        # rule-free common case. The .get_all() snapshot is already
        # in-memory; no I/O.
        from job_queue import JobState  # noqa: PLC0415
        if not any(j.state == JobState.BLOCKED for j in queue.get_all()):
            # Also skip when all jobs are already PENDING with no
            # blocked_reason stale-state to clear. Rare edge case —
            # still cheap to skip.
            if not any(
                j.state == JobState.PENDING and j.blocked_reason is not None
                for j in queue.get_all()
            ):
                return
    loop.create_task(re_evaluate_routing(app))


def build_claim_eligibility(
    app: "web.Application", worker_tags: list[str],
) -> Callable[["Job"], bool]:
    """Bug #95 — per-worker eligibility predicate for ``JobQueue.claim_next``.

    The fleet-wide :func:`re_evaluate_routing` only decides PENDING vs.
    BLOCKED ("can ANY worker take this?"). It cannot stop the *wrong*
    worker from grabbing a PENDING job — that's the per-worker decision
    this predicate adds. ``api.py``'s claim handler builds one predicate
    per HTTP request (one closure per polling worker call) and feeds it
    to ``claim_next`` so the queue can skip jobs whose required rules
    don't match this caller.

    Cheap path: when no global rules are defined, the predicate
    short-circuits without reading any device YAML. With rules, each
    unique target is read at most once per claim_next call (the cache
    survives the inner loop because the closure captures it).
    """
    rule_store: "RoutingRuleStore | None" = app.get("routing_rule_store")
    cfg = app.get("config")
    if rule_store is None or cfg is None:
        return lambda _job: True
    global_rules = rule_store.list_rules()

    # Per-call cache so two PENDING jobs against the same target
    # don't double-read the YAML metadata block.
    cache: dict[str, tuple[list[str], list[Rule]]] = {}
    from scanner import read_device_meta  # noqa: PLC0415

    def _resolve(target: str) -> tuple[list[str], list[Rule]]:
        cached = cache.get(target)
        if cached is not None:
            return cached
        try:
            meta = read_device_meta(cfg.config_dir, target)
        except Exception:
            logger.debug("read_device_meta failed for %s", target, exc_info=True)
            meta = {}
        device_tags = _device_tags_from_meta(meta)
        effective = global_rules + _device_routing_extra(meta)
        cache[target] = (device_tags, effective)
        return device_tags, effective

    worker_tag_set = set(worker_tags)

    def _filter_matches(filter_dict: dict) -> bool:
        # Bug #97: per-job ``worker_tag_filter`` clause — same shape as
        # a routing-rule clause. Treat malformed entries as "no
        # constraint" rather than poisoning the claim path.
        op = filter_dict.get("op")
        tags = filter_dict.get("tags") or []
        if not isinstance(tags, list):
            return True
        wanted = {str(t) for t in tags if isinstance(t, str) and t}
        if not wanted:
            return True
        if op == "all_of":
            return wanted.issubset(worker_tag_set)
        if op == "any_of":
            return bool(wanted & worker_tag_set)
        if op == "none_of":
            return not (wanted & worker_tag_set)
        return True  # unknown op — be permissive rather than strand the job

    def check(job: "Job") -> bool:
        # Bug #97: per-job worker_tag_filter applies before any YAML
        # reads; reject early when the filter doesn't match this worker.
        wtf = getattr(job, "worker_tag_filter", None)
        if isinstance(wtf, dict) and not _filter_matches(wtf):
            return False
        # Bug #110: with the user's override flag set, the rule check
        # is skipped — they've explicitly accepted the warning. The
        # tag-filter check above still ran because that's a constraint
        # the user authored too (and rejecting wrong workers there
        # avoids a false claim).
        if getattr(job, "bypass_routing_rules", False):
            return True
        # Cheapest path next — most fleets have zero global rules and
        # zero per-device routing_extra, so we never touch the YAML.
        if not global_rules:
            # Still need read_device_meta to discover routing_extra; do
            # it lazily and only when no global rules narrow first.
            device_tags, effective = _resolve(job.target)
            if not effective:
                return True
            return is_eligible(device_tags, worker_tags, effective)
        device_tags, effective = _resolve(job.target)
        if not effective:
            return True
        return is_eligible(device_tags, worker_tags, effective)

    return check


# Re-export for callers that prefer the symbol on this module.
__all__ = [
    "re_evaluate_routing",
    "routing_watchdog",
    "fire_and_forget",
    "build_claim_eligibility",
]


def _online_worker_tag_lists(app: "web.Application", threshold: int = 30) -> Iterable[list[str]]:
    """Test helper — enumerate the online worker tag-lists this module would see."""
    registry: "WorkerRegistry | None" = app.get("registry")
    if registry is None:
        return []
    out: list[list[str]] = []
    for w in registry.get_all():
        if not registry.is_online(w.client_id, threshold_secs=threshold):
            continue
        out.append(list(w.tags or []))
    return out
