"""Job queue with persistence, state machine, and timeout tracking."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

QUEUE_FILE = Path("/data/queue.json")
MAX_RETRIES = 3


class JobState(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
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
    assigned_at: Optional[datetime] = None
    worker_id: Optional[int] = None
    timeout_seconds: int = 600
    created_at: datetime = field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    retry_count: int = 0
    log: Optional[str] = None
    ota_result: Optional[str] = None
    ota_only: bool = False  # skip compile, just re-run OTA upload
    pinned_client_id: Optional[str] = None  # only this client can claim the job
    status_text: Optional[str] = None  # transient; not persisted

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "target": self.target,
            "esphome_version": self.esphome_version,
            "state": self.state.value,
            "run_id": self.run_id,
            "assigned_client_id": self.assigned_client_id,
            "assigned_at": _iso(self.assigned_at),
            "worker_id": self.worker_id,
            "timeout_seconds": self.timeout_seconds,
            "created_at": _iso(self.created_at),
            "finished_at": _iso(self.finished_at),
            "retry_count": self.retry_count,
            "log": self.log,
            "ota_result": self.ota_result,
            "ota_only": self.ota_only,
            "pinned_client_id": self.pinned_client_id,
            "status_text": self.status_text,
            "duration_seconds": self.duration_seconds(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(
            id=d["id"],
            target=d["target"],
            esphome_version=d["esphome_version"],
            state=JobState(d["state"]),
            run_id=d.get("run_id", ""),
            assigned_client_id=d.get("assigned_client_id"),
            assigned_at=_from_iso(d.get("assigned_at")),
            worker_id=d.get("worker_id"),
            timeout_seconds=d.get("timeout_seconds", 600),
            created_at=_from_iso(d.get("created_at")) or _utcnow(),
            finished_at=_from_iso(d.get("finished_at")),
            retry_count=d.get("retry_count", 0),
            log=d.get("log"),
            ota_result=d.get("ota_result"),
            ota_only=d.get("ota_only", False),
            pinned_client_id=d.get("pinned_client_id"),
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

        for d in data:
            job = Job.from_dict(d)
            # Restart recovery: assigned/running reset to pending
            if job.state in (JobState.ASSIGNED, JobState.RUNNING):
                job.state = JobState.PENDING
                job.assigned_client_id = None
                job.assigned_at = None
            self._jobs[job.id] = job

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
    ) -> Optional[Job]:
        """
        Create and enqueue a new job for *target*.

        Returns the new Job, or None if a job for this target is already
        pending/assigned/running (deduplication).

        Any existing terminal (success/failed/timed_out) jobs for the same
        target are removed so the queue stays tidy.
        """
        async with self._lock:
            # Deduplication: only one active job per target
            for job in self._jobs.values():
                if job.target == target and job.state in (
                    JobState.PENDING,
                    JobState.ASSIGNED,
                    JobState.RUNNING,
                ):
                    logger.debug("Skipping duplicate job for target %s", target)
                    return None

            # Clear old terminal jobs for this target before adding the new one
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

            job = Job(
                id=str(uuid.uuid4()),
                target=target,
                esphome_version=esphome_version,
                state=JobState.PENDING,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
            )
            self._jobs[job.id] = job
            self._persist()
            logger.info("Enqueued job %s for target %s", job.id, target)
            return job

    async def claim_next(self, client_id: str, worker_id: int = 1) -> Optional[Job]:
        """
        Atomically claim the next pending job for *client_id*.

        Returns the claimed Job or None if the queue is empty.
        """
        async with self._lock:
            for job in self._jobs.values():
                if job.state != JobState.PENDING:
                    continue
                # Pinned jobs can only be claimed by the designated client
                if job.pinned_client_id and job.pinned_client_id != client_id:
                    continue
                job.state = JobState.ASSIGNED
                job.assigned_client_id = client_id
                job.assigned_at = _utcnow()
                job.worker_id = worker_id
                self._persist()
                logger.info("Job %s assigned to client %s worker %d", job.id, client_id, worker_id)
                return job
            return None

    async def update_to_running(self, job_id: str, client_id: str) -> bool:
        """Transition an ASSIGNED job to RUNNING."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.state != JobState.ASSIGNED or job.assigned_client_id != client_id:
                logger.warning(
                    "update_to_running: job %s not in expected state (state=%s, client=%s)",
                    job_id,
                    job.state,
                    job.assigned_client_id,
                )
                return False
            job.state = JobState.RUNNING
            self._persist()
            return True

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
                if log is not None:
                    job.log = (job.log or "") + "\n" + log
                job.status_text = None
                self._persist()
                logger.info("Job %s OTA result: %s", job_id, ota_result)
                return True

            if job.state not in (JobState.ASSIGNED, JobState.RUNNING):
                logger.warning(
                    "submit_result: job %s in unexpected state %s", job_id, job.state
                )
                return False
            job.state = JobState.SUCCESS if status == "success" else JobState.FAILED
            job.log = log
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
        Find timed-out jobs (ASSIGNED/RUNNING past deadline).

        Re-enqueues as PENDING if retry_count < MAX_RETRIES, otherwise
        marks FAILED permanently.  Returns the list of affected jobs.
        """
        async with self._lock:
            now = _utcnow()
            affected: list[Job] = []
            for job in self._jobs.values():
                if job.state not in (JobState.ASSIGNED, JobState.RUNNING):
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
        """Re-enqueue failed/timed_out jobs as new PENDING jobs. Returns new jobs.

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
                if not (is_failed or is_ota_failed):
                    continue
                target = job.target
                # Pin OTA retries to the client that compiled the firmware
                pin_to = job.assigned_client_id if is_ota_failed else None
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

    def get_all(self) -> list[Job]:
        """Return a snapshot of all jobs."""
        return list(self._jobs.values())

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def queue_size(self) -> int:
        """Return number of pending/assigned/running jobs."""
        return sum(
            1
            for j in self._jobs.values()
            if j.state in (JobState.PENDING, JobState.ASSIGNED, JobState.RUNNING)
        )

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
