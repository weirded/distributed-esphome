"""Build worker registry — in-memory, no persistence needed."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Worker:
    client_id: str
    hostname: str
    platform: str
    last_seen: datetime = field(default_factory=_utcnow)
    current_job_id: Optional[str] = None
    disabled: bool = False
    client_version: Optional[str] = None
    max_parallel_jobs: int = 1
    requested_max_parallel_jobs: Optional[int] = None  # set via UI, pushed in heartbeat
    pending_clean: bool = False  # set via UI, pushed in heartbeat
    system_info: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id,
            "hostname": self.hostname,
            "platform": self.platform,
            "last_seen": self.last_seen.isoformat(),
            "current_job_id": self.current_job_id,
            "disabled": self.disabled,
            "client_version": self.client_version,
            "max_parallel_jobs": self.max_parallel_jobs,
            "requested_max_parallel_jobs": self.requested_max_parallel_jobs,
            "pending_clean": self.pending_clean,
            "system_info": self.system_info,
        }


class WorkerRegistry:
    """Tracks connected build workers."""

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}

    def register(
        self,
        hostname: str,
        platform: str,
        client_version: Optional[str] = None,
        existing_client_id: Optional[str] = None,
        max_parallel_jobs: int = 1,
        system_info: Optional[dict] = None,
    ) -> str:
        """Register a worker. Returns client_id.

        If *existing_client_id* is provided and that worker is still in the
        registry, update it in place (preserves the entry across auto-updates).
        Otherwise create a new entry.
        """
        if existing_client_id and existing_client_id in self._workers:
            worker = self._workers[existing_client_id]
            worker.hostname = hostname
            worker.platform = platform
            worker.client_version = client_version
            worker.max_parallel_jobs = max_parallel_jobs
            # Clear the request once the worker has applied the new value
            if worker.requested_max_parallel_jobs == max_parallel_jobs:
                worker.requested_max_parallel_jobs = None
            worker.last_seen = _utcnow()
            if system_info is not None:
                worker.system_info = system_info
            logger.info(
                "Re-registered worker %s (%s / %s / v%s / %d slots)",
                existing_client_id, hostname, platform, client_version or "?", max_parallel_jobs,
            )
            return existing_client_id

        client_id = str(uuid.uuid4())
        worker = Worker(
            client_id=client_id,
            hostname=hostname,
            platform=platform,
            client_version=client_version,
            max_parallel_jobs=max_parallel_jobs,
            system_info=system_info,
        )
        self._workers[client_id] = worker
        logger.info(
            "Registered worker %s (%s / %s / v%s / %d slots)",
            client_id, hostname, platform, client_version or "?", max_parallel_jobs,
        )
        return client_id

    def heartbeat(self, client_id: str, system_info: Optional[dict] = None) -> bool:
        """Update last_seen for *client_id*. Returns False if unknown."""
        worker = self._workers.get(client_id)
        if worker is None:
            return False
        worker.last_seen = _utcnow()
        if system_info is not None:
            worker.system_info = system_info
        return True

    def set_job(self, client_id: str, job_id: Optional[str]) -> bool:
        """Set the current job for a worker. Returns False if unknown."""
        worker = self._workers.get(client_id)
        if worker is None:
            return False
        worker.current_job_id = job_id
        return True

    def get_all(self) -> list[Worker]:
        return list(self._workers.values())

    def is_online(self, client_id: str, threshold_secs: int = 30) -> bool:
        worker = self._workers.get(client_id)
        if worker is None:
            return False
        elapsed = (_utcnow() - worker.last_seen).total_seconds()
        return elapsed <= threshold_secs

    def set_disabled(self, client_id: str, disabled: bool) -> bool:
        """Enable or disable a worker. Returns False if unknown."""
        worker = self._workers.get(client_id)
        if worker is None:
            return False
        worker.disabled = disabled
        logger.info("Worker %s (%s) %s", client_id, worker.hostname, "disabled" if disabled else "enabled")
        return True

    def remove(self, client_id: str) -> bool:
        """Remove a worker from the registry. Returns False if unknown."""
        worker = self._workers.pop(client_id, None)
        if worker is None:
            return False
        logger.info("Removed worker %s (%s)", client_id, worker.hostname)
        return True

    def get(self, client_id: str) -> Optional[Worker]:
        return self._workers.get(client_id)


# Backwards-compatible alias — keeps any code that imports ClientRegistry working
ClientRegistry = WorkerRegistry
