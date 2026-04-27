"""TG.1 — persistent store of worker tags.

Tags are user-managed strings attached to a worker (``"linux"``, ``"prod"``,
``"os:macos"``). They drive the rule-based job-routing engine added in TG.2:
a routing rule says "device tag X requires worker tag Y" and the scheduler
filters claim candidates accordingly.

Storage shape (JSON, ``/data/worker-tags.json``)::

    {"version": 1, "tags": {"<identity>": ["foo", "bar"], ...}}

``<identity>`` is the worker's hostname, falling back to its persistent
``client_id`` when hostname collides (rare — two physical workers with the
same ``HOSTNAME`` env on the same fleet). The caller resolves the identity
before reaching this module.

Seed semantics (TG.1 design): the *first* registration for an identity
seeds the entry from the worker's ``WORKER_TAGS`` env var. Every later
registration is server-side-wins — the worker's env is ignored unless it
also sets ``WORKER_TAGS_OVERWRITE=1`` (which the server sees as the
``overwrite_tags`` flag on the registration payload). This lets a user
edit a worker's tags from the UI without the worker's docker invocation
clobbering them on the next restart.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def _normalise(tags: list[str] | None) -> list[str]:
    """Trim, drop empties, dedupe (case-sensitive). Preserves first-seen order."""
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


class WorkerTagStore:
    """JSON-backed store keyed by worker identity.

    The store is small (one entry per worker the server has ever seen) and
    accessed on a slow path (worker registration, UI tag edit). A single
    coarse lock around load/save is plenty — no need for per-key locking.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._tags: dict[str, list[str]] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, list[str]]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            logger.warning("worker-tags read failed (%s) — starting empty", exc)
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("worker-tags file is corrupt — starting empty (will rewrite on next save)")
            return {}
        if not isinstance(data, dict) or data.get("version") != _SCHEMA_VERSION:
            logger.warning(
                "worker-tags file has unknown schema version %r — starting empty",
                data.get("version") if isinstance(data, dict) else None,
            )
            return {}
        tags_obj = data.get("tags")
        if not isinstance(tags_obj, dict):
            return {}
        return {
            ident: _normalise(val) if isinstance(val, list) else []
            for ident, val in tags_obj.items()
            if isinstance(ident, str)
        }

    def _save(self) -> None:
        payload = {"version": _SCHEMA_VERSION, "tags": self._tags}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self._path)
        except OSError as exc:
            logger.error("worker-tags save failed: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_or_seed(
        self,
        identity: str,
        seed_tags: list[str] | None,
        overwrite: bool,
    ) -> list[str]:
        """Resolve a worker's tags at registration time.

        - First time we see this identity: seed from ``seed_tags`` (or empty
          if the worker didn't send any). Persists.
        - Subsequent times: return the persisted tags; ignore ``seed_tags``.
          Override with ``overwrite=True`` (worker set ``WORKER_TAGS_OVERWRITE=1``).
        """
        with self._lock:
            existing = self._tags.get(identity)
            if existing is not None and not overwrite:
                if seed_tags is not None:
                    logger.debug(
                        "worker %s registered with WORKER_TAGS=%r but server already has %r; keeping server-side",
                        identity, seed_tags, existing,
                    )
                return list(existing)
            normalised = _normalise(seed_tags)
            self._tags[identity] = normalised
            self._save()
            return list(normalised)

    def set_tags(self, identity: str, tags: list[str]) -> list[str]:
        """Set tags from the UI. Authoritative; clobbers any prior entry."""
        with self._lock:
            normalised = _normalise(tags)
            self._tags[identity] = normalised
            self._save()
            return list(normalised)

    def get_tags(self, identity: str) -> list[str]:
        with self._lock:
            return list(self._tags.get(identity, []))

    def all_tags(self) -> list[str]:
        """Sorted union of every tag across every worker — fleet-wide tag pool."""
        with self._lock:
            seen: set[str] = set()
            for tags in self._tags.values():
                seen.update(tags)
            return sorted(seen)
