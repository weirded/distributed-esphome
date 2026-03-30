"""Build client registry — in-memory, no persistence needed."""

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
class Client:
    client_id: str
    hostname: str
    platform: str
    last_seen: datetime = field(default_factory=_utcnow)
    current_job_id: Optional[str] = None
    disabled: bool = False
    client_version: Optional[str] = None
    max_parallel_jobs: int = 1
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
            "system_info": self.system_info,
        }


class ClientRegistry:
    """Tracks connected build clients."""

    def __init__(self) -> None:
        self._clients: dict[str, Client] = {}

    def register(
        self,
        hostname: str,
        platform: str,
        client_version: Optional[str] = None,
        existing_client_id: Optional[str] = None,
        max_parallel_jobs: int = 1,
        system_info: Optional[dict] = None,
    ) -> str:
        """Register a client. Returns client_id.

        If *existing_client_id* is provided and that client is still in the
        registry, update it in place (preserves the entry across auto-updates).
        Otherwise create a new entry.
        """
        if existing_client_id and existing_client_id in self._clients:
            client = self._clients[existing_client_id]
            client.hostname = hostname
            client.platform = platform
            client.client_version = client_version
            client.max_parallel_jobs = max_parallel_jobs
            client.last_seen = _utcnow()
            if system_info is not None:
                client.system_info = system_info
            logger.info(
                "Re-registered client %s (%s / %s / v%s / %d slots)",
                existing_client_id, hostname, platform, client_version or "?", max_parallel_jobs,
            )
            return existing_client_id

        client_id = str(uuid.uuid4())
        client = Client(
            client_id=client_id,
            hostname=hostname,
            platform=platform,
            client_version=client_version,
            max_parallel_jobs=max_parallel_jobs,
            system_info=system_info,
        )
        self._clients[client_id] = client
        logger.info(
            "Registered client %s (%s / %s / v%s / %d slots)",
            client_id, hostname, platform, client_version or "?", max_parallel_jobs,
        )
        return client_id

    def heartbeat(self, client_id: str, system_info: Optional[dict] = None) -> bool:
        """Update last_seen for *client_id*. Returns False if unknown."""
        client = self._clients.get(client_id)
        if client is None:
            return False
        client.last_seen = _utcnow()
        if system_info is not None:
            client.system_info = system_info
        return True

    def set_job(self, client_id: str, job_id: Optional[str]) -> bool:
        """Set the current job for a client. Returns False if unknown."""
        client = self._clients.get(client_id)
        if client is None:
            return False
        client.current_job_id = job_id
        return True

    def get_all(self) -> list[Client]:
        return list(self._clients.values())

    def is_online(self, client_id: str, threshold_secs: int = 30) -> bool:
        client = self._clients.get(client_id)
        if client is None:
            return False
        elapsed = (_utcnow() - client.last_seen).total_seconds()
        return elapsed <= threshold_secs

    def set_disabled(self, client_id: str, disabled: bool) -> bool:
        """Enable or disable a client. Returns False if unknown."""
        client = self._clients.get(client_id)
        if client is None:
            return False
        client.disabled = disabled
        logger.info("Client %s (%s) %s", client_id, client.hostname, "disabled" if disabled else "enabled")
        return True

    def remove(self, client_id: str) -> bool:
        """Remove a client from the registry. Returns False if unknown."""
        client = self._clients.pop(client_id, None)
        if client is None:
            return False
        logger.info("Removed client %s (%s)", client_id, client.hostname)
        return True

    def get(self, client_id: str) -> Optional[Client]:
        return self._clients.get(client_id)
