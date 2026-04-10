"""Job queue with persistence, state machine, and timeout tracking."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

QUEUE_FILE = Path("/data/queue.json")
MAX_RETRIES = 3
MAX_LOG_BYTES = 512 * 1024  # 512 KB per job
LOG_TRUNCATED_MARKER = "\n\n--- LOG TRUNCATED (exceeded 512 KB) ---\n"


class JobState(str, Enum):
    PENDING = "pending"
    WORKING = "working"
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    return datetime.fromisoformat(s)


@dataclass
class Job:
    id: str
    target: str
    esphome_version: str
    state: JobState
    run_id: str
    assigned_client_id: Optional[str] = None
    assigned_hostname: Optional[str] = None  # persisted so UI works after worker deregisters
    assigned_at: Optional[datetime] = None
    worker_id: Optional[int] = None
    timeout_seconds: int = 600
    created_at: datetime = field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    retry_count: int = 0
    log: Optional[str] = None
    ota_result: Optional[str] = None
    ota_only: bool = False  # skip compile, just re-run OTA upload
    validate_only: bool = False  # run esphome config (validation) instead of compile+OTA
    ota_address: Optional[str] = None  # override OTA target address (used after rename)
    pinned_client_id: Optional[str] = None  # only this client can claim the job
    # #23: True if this job is a coalesced "follow-up" — created while another
    # job for the same target was already WORKING. Follow-ups are not eligible
    # to be claimed until their predecessor reaches a terminal state. Surfaced
    # in the UI so the user can see "queued behind running" without inferring
    # it from state. At most one follow-up per target at a time; subsequent
    # enqueue calls update the existing follow-up's esphome_version /
    # pinned_client_id rather than creating new entries.
    is_followup: bool = False
    status_text: Optional[str] = None  # transient; not persisted
    _streaming_log: str = field(default="", repr=False)  # transient; not persisted

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "target": self.target,
            "esphome_version": self.esphome_version,
            "state": self.state.value,
            "run_id": self.run_id,
            "assigned_client_id": self.assigned_client_id,
            "assigned_hostname": self.assigned_hostname,
            "assigned_at": _iso(self.assigned_at),
            "worker_id": self.worker_id,
            "timeout_seconds": self.timeout_seconds,
            "created_at": _iso(self.created_at),
            "finished_at": _iso(self.finished_at),
            "retry_count": self.retry_count,
            "log": self.log,
            "ota_result": self.ota_result,
            "ota_only": self.ota_only,
            "validate_only": self.validate_only,
            "ota_address": self.ota_address,
            "pinned_client_id": self.pinned_client_id,
            "is_followup": self.is_followup,
            "status_text": self.status_text,
            "duration_seconds": self.duration_seconds(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        # Backwards compatibility: old "assigned"/"running" states map to WORKING
        raw_state = d["state"]
        if raw_state in ("assigned", "running"):
            raw_state = "working"
        return cls(
            id=d["id"],
            target=d["target"],
            esphome_version=d["esphome_version"],
            state=JobState(raw_state),
            run_id=d.get("run_id", ""),
            assigned_client_id=d.get("assigned_client_id"),
            assigned_hostname=d.get("assigned_hostname"),
            assigned_at=_from_iso(d.get("assigned_at")),
            worker_id=d.get("worker_id"),
            timeout_seconds=d.get("timeout_seconds", 600),
            created_at=_from_iso(d.get("created_at")) or _utcnow(),
            finished_at=_from_iso(d.get("finished_at")),
            retry_count=d.get("retry_count", 0),
            log=d.get("log"),
            ota_result=d.get("ota_result"),
            ota_only=d.get("ota_only", False),
            validate_only=d.get("validate_only", False),
            ota_address=d.get("ota_address"),
            pinned_client_id=d.get("pinned_client_id"),
            is_followup=d.get("is_followup", False),
        )

    def duration_seconds(self) -> Optional[float]:
        if self.assigned_at is None:
            return None
        end = self.finished_at or _utcnow()
        return (end - self.assigned_at).total_seconds()


class JobQueue:
    """Thread-safe (asyncio) job queue with JSON persistence."""

    def __init__(self, queue_file: Path = QUEUE_FILE) -> None:
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = asyncio.Lock()
        self._queue_file = queue_file

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Write current queue state to disk. Called after every mutation."""
        try:
            self._queue_file.parent.mkdir(parents=True, exist_ok=True)
            data = [job.to_dict() for job in self._jobs.values()]
            tmp = self._queue_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self._queue_file)
        except Exception:
            logger.exception("Failed to persist queue to %s", self._queue_file)

    def load(self) -> None:
        """Load queue from disk on server startup, applying restart recovery rules."""
        if not self._queue_file.exists():
            return
        try:
            data = json.loads(self._queue_file.read_text())
        except Exception:
            logger.exception("Failed to load queue from %s; starting fresh", self._queue_file)
            return

        if not isinstance(data, list):
            logger.error(
                "Queue file %s is not a JSON array (got %s); starting fresh",
                self._queue_file, type(data).__name__,
            )
            return

        pruned = 0
        skipped = 0
        cutoff = datetime.now(timezone.utc)
        for d in data:
            if not isinstance(d, dict):
                logger.error("Skipping non-dict entry in queue file: %r", d)
                skipped += 1
                continue
            try:
                job = Job.from_dict(d)
            except Exception:
                # A single bad entry must not take down the whole queue —
                # log the failure at ERROR (so it's visible in production logs)
                # and continue with the rest of the file. B.6 regression guard.
                logger.error(
                    "Failed to parse job entry %r from queue file; skipping",
                    d.get("id", "<no id>"),
                    exc_info=True,
                )
                skipped += 1
                continue
            # Restart recovery: working jobs reset to pending (worker is gone)
            if job.state == JobState.WORKING:
                job.state = JobState.PENDING
                job.assigned_client_id = None
                job.assigned_at = None
            # Prune terminal jobs older than 1 hour on startup
            if job.state in (JobState.SUCCESS, JobState.FAILED, JobState.TIMED_OUT):
                try:
                    created = job.created_at
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if (cutoff - created).total_seconds() > 3600:
                        pruned += 1
                        continue  # skip adding to queue
                except Exception:
                    pruned += 1
                    continue
            self._jobs[job.id] = job

        if pruned:
            logger.info("Pruned %d old terminal jobs on startup", pruned)
            self._persist()
        if skipped:
            logger.warning("Skipped %d unparseable job entries on startup", skipped)
        logger.info("Loaded %d jobs from %s", len(self._jobs), self._queue_file)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        target: str,
        esphome_version: str,
        run_id: str,
        timeout_seconds: int,
        validate_only: bool = False,
        ota_address: Optional[str] = None,
        pinned_client_id: Optional[str] = None,
    ) -> Optional[Job]:
        """
        Create and enqueue a new job for *target*.

        Coalescing rules (#23) — at most ONE active + ONE follow-up per target:
          - No PENDING/WORKING for target → create new active job (PENDING).
          - PENDING for target (not yet WORKING) → no-op, return None.
            The user's edits will be picked up when the existing job claims
            (the bundle is generated at claim time, not enqueue time).
          - WORKING for target, no follow-up → create a follow-up (PENDING,
            ``is_followup=True``). It will be skipped by ``claim_next`` until
            the WORKING predecessor reaches a terminal state.
          - WORKING for target AND follow-up exists → update the follow-up's
            ``esphome_version``, ``pinned_client_id``, ``ota_address``, and
            ``timeout_seconds`` from the new request, then return it. Lets
            the user "change their mind" about the next compile without
            piling up queue entries.

        Validate-only jobs intentionally bypass coalescing — they're cheap,
        independent, and the user explicitly asked for that specific run.

        Any existing terminal (success/failed/timed_out) jobs for the same
        target are removed so the queue stays tidy.
        """
        async with self._lock:
            # Find current active + follow-up state for this target.
            active: Optional[Job] = None
            followup: Optional[Job] = None
            for job in self._jobs.values():
                if job.target != target:
                    continue
                if job.state == JobState.WORKING:
                    active = job
                elif job.state == JobState.PENDING:
                    if job.is_followup:
                        followup = job
                    else:
                        active = job  # PENDING-but-not-yet-claimed counts as active

            # Validate-only jobs bypass coalescing — see docstring.
            if validate_only:
                pass  # fall through to "create new" path
            elif followup is not None:
                # 1 active + 1 follow-up → update the follow-up in place.
                # Preserves the order in _jobs but reflects the latest user
                # intent (version override, worker pin, etc.).
                followup.esphome_version = esphome_version
                followup.pinned_client_id = pinned_client_id
                followup.ota_address = ota_address
                followup.timeout_seconds = timeout_seconds
                followup.run_id = run_id  # belongs to the latest request
                self._persist()
                logger.info(
                    "Updated existing follow-up job %s for target %s "
                    "(version=%s pinned=%s)",
                    followup.id, target, esphome_version, pinned_client_id,
                )
                return followup
            elif active is not None and active.state == JobState.PENDING:
                # Active is queued but not yet running — no follow-up needed.
                logger.debug(
                    "Target %s already has a pending job %s; skipping enqueue",
                    target, active.id,
                )
                return None
            # else: active is WORKING (or None) → fall through to create.
            # When active is WORKING the new job becomes a follow-up.

            # Clear old terminal jobs for this target before adding the new one.
            stale = [
                jid for jid, j in self._jobs.items()
                if j.target == target and j.state in (
                    JobState.SUCCESS, JobState.FAILED, JobState.TIMED_OUT
                )
            ]
            for jid in stale:
                del self._jobs[jid]
            if stale:
                logger.debug("Removed %d stale job(s) for target %s", len(stale), target)

            is_followup = active is not None and active.state == JobState.WORKING and not validate_only
            job = Job(
                id=str(uuid.uuid4()),
                target=target,
                esphome_version=esphome_version,
                state=JobState.PENDING,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                validate_only=validate_only,
                ota_address=ota_address,
                pinned_client_id=pinned_client_id,
                is_followup=is_followup,
            )
            self._jobs[job.id] = job
            self._persist()
            if is_followup:
                logger.info(
                    "Enqueued follow-up job %s for target %s "
                    "(behind running job %s)",
                    job.id, target, active.id if active else "?",
                )
            else:
                logger.info("Enqueued job %s for target %s", job.id, target)
            return job

    async def claim_next(
        self,
        client_id: str,
        worker_id: int = 1,
        hostname: Optional[str] = None,
        faster_idle_worker_exists: bool = False,
    ) -> Optional[Job]:
        """
        Atomically claim the next pending job for *client_id*.

        If *faster_idle_worker_exists* is True, returns None so the
        faster worker can claim on its next poll cycle.

        Returns the claimed Job or None if the queue is empty.
        """
        now = _utcnow()
        async with self._lock:
            # #23: a follow-up job is blocked until its predecessor for the
            # same target reaches a terminal state. Pre-compute the set of
            # targets that currently have a WORKING job so we can skip
            # follow-ups for those targets in O(1).
            blocked_targets = {
                j.target for j in self._jobs.values() if j.state == JobState.WORKING
            }
            for job in self._jobs.values():
                if job.state != JobState.PENDING:
                    continue
                # Pinned jobs can only be claimed by the designated worker
                if job.pinned_client_id and job.pinned_client_id != client_id:
                    continue
                # Defer to faster workers — but never defer pinned jobs
                if faster_idle_worker_exists and not job.pinned_client_id:
                    continue
                # Skip follow-ups whose predecessor is still WORKING.
                if job.is_followup and job.target in blocked_targets:
                    continue
                job.state = JobState.WORKING
                # Once claimed, a follow-up is no longer "queued behind
                # running" — it IS the running job. Clear the flag so the
                # UI badge disappears at the right moment.
                job.is_followup = False
                job.assigned_client_id = client_id
                job.assigned_hostname = hostname
                job.assigned_at = now
                job.worker_id = worker_id
                self._persist()
                logger.info("Job %s claimed by client %s worker %d", job.id, client_id, worker_id)
                return job
            return None

    async def submit_result(
        self,
        job_id: str,
        status: str,
        log: Optional[str] = None,
        ota_result: Optional[str] = None,
    ) -> bool:
        """Record the final result of a job.

        Also handles OTA-only updates: if the job is already SUCCESS/FAILED
        and only ota_result is provided (no log), just patch ota_result.
        """
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False

            # OTA update on an already-finished job (ota_result required; log is appended if provided)
            if job.state in (JobState.SUCCESS, JobState.FAILED) and ota_result is not None:
                job.ota_result = ota_result
                # Append OTA log from streaming buffer or explicit log
                ota_log = log if log is not None else (job._streaming_log or None)
                if ota_log:
                    job.log = (job.log or "") + "\n" + ota_log
                job._streaming_log = ""
                job.status_text = None
                self._persist()
                logger.info("Job %s OTA result: %s", job_id, ota_result)
                return True

            if job.state != JobState.WORKING:
                logger.warning(
                    "submit_result: job %s in unexpected state %s", job_id, job.state
                )
                return False
            job.state = JobState.SUCCESS if status == "success" else JobState.FAILED
            # Use the streamed log if the worker didn't send a final log
            job.log = log if log is not None else (job._streaming_log or None)
            job._streaming_log = ""  # free memory
            job.status_text = None
            if ota_result is not None:
                job.ota_result = ota_result
            job.finished_at = _utcnow()
            self._persist()
            logger.info("Job %s finished with status %s", job_id, status)
            return True

    async def cancel(self, job_ids: list[str]) -> int:
        """Cancel jobs by id; transitions any non-terminal job to FAILED."""
        async with self._lock:
            cancelled = 0
            for job_id in job_ids:
                job = self._jobs.get(job_id)
                if job is None:
                    continue
                if job.state not in (JobState.SUCCESS, JobState.FAILED):
                    job.state = JobState.FAILED
                    job.finished_at = _utcnow()
                    job.log = (job.log or "") + "\nCancelled by user."
                    cancelled += 1
            if cancelled:
                self._persist()
            return cancelled

    async def check_timeouts(self) -> list[Job]:
        """
        Find timed-out jobs (WORKING past deadline).

        Re-enqueues as PENDING if retry_count < MAX_RETRIES, otherwise
        marks FAILED permanently.  Returns the list of affected jobs.
        """
        async with self._lock:
            now = _utcnow()
            affected: list[Job] = []
            for job in self._jobs.values():
                if job.state != JobState.WORKING:
                    continue
                if job.assigned_at is None:
                    continue
                elapsed = (now - job.assigned_at).total_seconds()
                if elapsed < job.timeout_seconds:
                    continue

                job.retry_count += 1
                logger.warning(
                    "Job %s timed out after %.0fs (retry %d/%d)",
                    job.id,
                    elapsed,
                    job.retry_count,
                    MAX_RETRIES,
                )
                if job.retry_count >= MAX_RETRIES:
                    job.state = JobState.FAILED
                    job.finished_at = now
                    job.log = (job.log or "") + f"\nPermanently failed after {MAX_RETRIES} timeouts."
                else:
                    job.state = JobState.TIMED_OUT
                    # Re-enqueue: reset to pending
                    job.state = JobState.PENDING
                    job.assigned_client_id = None
                    job.assigned_at = None

                affected.append(job)

            if affected:
                self._persist()
            return affected

    async def retry(
        self,
        job_ids: list[str],
        esphome_version: str,
        run_id: str,
        timeout_seconds: int,
    ) -> list["Job"]:
        """Re-enqueue failed/timed_out/success jobs as new PENDING jobs. Returns new jobs.

        The old job being retried is removed; any other terminal jobs for the
        same target are also cleared (same semantics as enqueue).
        """
        async with self._lock:
            new_jobs: list[Job] = []
            for job_id in job_ids:
                job = self._jobs.get(job_id)
                if job is None:
                    continue
                is_failed = job.state in (JobState.FAILED, JobState.TIMED_OUT)
                is_ota_failed = job.state == JobState.SUCCESS and job.ota_result == "failed"
                is_success = job.state == JobState.SUCCESS
                if not (is_failed or is_ota_failed or is_success):
                    continue
                target = job.target
                # Pin OTA retries to the worker that compiled the firmware.
                # Also preserve any user-requested pin from "Upgrade on..." action.
                pin_to = job.assigned_client_id if is_ota_failed else job.pinned_client_id
                # Remove all terminal jobs for this target (including the one being retried)
                stale = [
                    jid for jid, j in self._jobs.items()
                    if j.target == target and j.state in (
                        JobState.SUCCESS, JobState.FAILED, JobState.TIMED_OUT
                    )
                ]
                for jid in stale:
                    del self._jobs[jid]
                new_job = Job(
                    id=str(uuid.uuid4()),
                    target=target,
                    esphome_version=esphome_version,
                    state=JobState.PENDING,
                    run_id=run_id,
                    timeout_seconds=timeout_seconds,
                    ota_only=is_ota_failed,
                    pinned_client_id=pin_to,
                )
                self._jobs[new_job.id] = new_job
                new_jobs.append(new_job)
                logger.info(
                    "Retrying → new job %s for %s (ota_only=%s, pinned=%s)",
                    new_job.id, target, is_ota_failed, pin_to or "any",
                )
            if new_jobs:
                self._persist()
            return new_jobs

    async def update_status(self, job_id: str, status_text: str) -> bool:
        """Update the in-progress status text for a running job (not persisted)."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.status_text = status_text
            return True

    async def append_log(self, job_id: str, text: str) -> bool:
        """Append streaming log text to a running job (transient; not persisted).

        Caps the streaming log at MAX_LOG_BYTES to prevent OOM from
        runaway build output.
        """
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            current_len = len(job._streaming_log)
            if current_len >= MAX_LOG_BYTES:
                return True  # silently drop — already truncated
            # Reserve space for the truncation marker so the final log
            # never exceeds MAX_LOG_BYTES, and never concatenate the full
            # incoming text first (which would itself risk OOM).
            budget = MAX_LOG_BYTES - current_len
            if len(text) <= budget:
                job._streaming_log += text
            else:
                # Truncating. Final log must not exceed MAX_LOG_BYTES,
                # including the marker — trim the existing log if needed.
                marker_len = len(LOG_TRUNCATED_MARKER)
                if budget >= marker_len:
                    job._streaming_log += text[: budget - marker_len] + LOG_TRUNCATED_MARKER
                else:
                    trim_to = max(0, MAX_LOG_BYTES - marker_len)
                    job._streaming_log = job._streaming_log[:trim_to] + LOG_TRUNCATED_MARKER
            return True

    def get_all(self) -> list[Job]:
        """Return a snapshot of all jobs."""
        return list(self._jobs.values())

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def queue_size(self) -> int:
        """Return number of pending/working jobs."""
        return sum(
            1
            for j in self._jobs.values()
            if j.state in (JobState.PENDING, JobState.WORKING)
        )

    async def prune_old_terminal(self, max_age_seconds: int = 3600) -> int:
        """Remove terminal jobs older than *max_age_seconds*. Returns count removed."""
        terminal = {JobState.SUCCESS, JobState.FAILED, JobState.TIMED_OUT}
        cutoff = datetime.now(timezone.utc)
        async with self._lock:
            to_remove = []
            for job_id, job in self._jobs.items():
                if job.state not in terminal:
                    continue
                try:
                    created = job.created_at if isinstance(job.created_at, datetime) else datetime.fromisoformat(str(job.created_at))
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    age = (cutoff - created).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(job_id)
                except Exception:
                    to_remove.append(job_id)  # can't parse date → prune it
            for job_id in to_remove:
                del self._jobs[job_id]
            if to_remove:
                self._persist()
            return len(to_remove)

    async def remove_jobs(self, job_ids: list[str]) -> int:
        """Remove terminal jobs by ID. Returns count removed."""
        terminal = {JobState.SUCCESS, JobState.FAILED, JobState.TIMED_OUT}
        async with self._lock:
            removed = 0
            for job_id in job_ids:
                job = self._jobs.get(job_id)
                if job and job.state in terminal:
                    del self._jobs[job_id]
                    removed += 1
            if removed:
                self._persist()
            return removed

    async def clear(self, states: list[str], require_ota_success: bool = False) -> int:
        """Remove terminal jobs whose state is in *states*. Returns count removed.

        If *require_ota_success* is True, jobs with ota_result == 'failed' are
        kept even if their state matches (so "Clear Succeeded" leaves OTA-failed jobs).
        """
        terminal = {JobState.SUCCESS, JobState.FAILED, JobState.TIMED_OUT}
        target_states = {JobState(s) for s in states if JobState(s) in terminal}
        async with self._lock:
            to_remove = []
            for job_id, job in self._jobs.items():
                if job.state not in target_states:
                    continue
                if require_ota_success and job.ota_result == "failed":
                    continue
                to_remove.append(job_id)
            for job_id in to_remove:
                del self._jobs[job_id]
            if to_remove:
                self._persist()
            return len(to_remove)
