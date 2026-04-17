"""Server-side event bus (#41).

Thin pub/sub for "state changed" notifications that feed the HA custom
integration's real-time push path. Mutation points in the server call
:func:`broadcast` with a lightweight event type; each connected
WebSocket client (see the ``/ui/api/ws/events`` endpoint in ``ui_api``)
wakes up and gets the event delivered to its own async queue.

Kept deliberately simple — no persistence, no replay, no event history.
HA's coordinator still polls every 30 s as a safety net, so a missed
event just means up-to-30-s-delay on a single update rather than stale
state forever.

Event types (all producers MUST use these constants):

  EVENT_QUEUE_CHANGED   — a job was added, claimed, completed, or
                          removed. Triggered from ``job_queue`` state
                          transitions and queue mutations.
  EVENT_WORKERS_CHANGED — a worker registered, heartbeated with a new
                          status, or was removed.
  EVENT_TARGETS_CHANGED — the scanner picked up a new/removed/renamed
                          YAML file, or device metadata was mutated via
                          ``/ui/api/targets/*``.
  EVENT_DEVICES_CHANGED — the device poller transitioned a device's
                          online state or picked up a new address /
                          running version.

Each event payload is a small dict that travels to the client verbatim.
The integration treats any message as "refresh now"; the event type is
carried for future use (e.g. partial updates in UE.*).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

EVENT_QUEUE_CHANGED = "queue_changed"
EVENT_WORKERS_CHANGED = "workers_changed"
EVENT_TARGETS_CHANGED = "targets_changed"
EVENT_DEVICES_CHANGED = "devices_changed"

# Subscriber queues. Each WebSocket client owns one. A set makes
# unsubscribe O(1) without needing IDs. The queues are bounded so a
# slow consumer can't blow up memory; overflow drops the OLDEST event
# (the client will re-sync on the next poll anyway).
_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_QUEUE_MAX = 64


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    """Register a new subscriber. Returns the queue the caller reads from."""
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(q)
    logger.debug("event_bus: +subscriber (total=%d)", len(_subscribers))
    return q


def unsubscribe(q: asyncio.Queue[dict[str, Any]]) -> None:
    """Remove a subscriber queue. Safe to call twice."""
    _subscribers.discard(q)
    logger.debug("event_bus: -subscriber (total=%d)", len(_subscribers))


def broadcast(event_type: str, **payload: Any) -> None:
    """Deliver an event to every subscriber, non-blocking.

    CR.22: **must be called from the aiohttp event loop** — `asyncio.Queue.put_nowait`
    is loop-affine, so calling this from a thread pool (e.g. from a
    ``loop.run_in_executor`` worker) would silently enqueue against the
    wrong loop's queue and subscribers would never receive the event.
    If you ever need to broadcast from a thread, wrap the call in
    ``hass.loop.call_soon_threadsafe(broadcast, event_type, **payload)``.

    If a subscriber's queue is full, drops the OLDEST event from that
    queue and retries once, so a slow-draining client loses the cheapest
    events first.

    ## SLA against missed events

    Two recovery paths for a dropped or missed event, by consumer:

    - **Browser UI** — recovers within ~1 s via the SWR poll cadence
      (the UI doesn't rely exclusively on WebSocket events; events just
      force an earlier refetch).
    - **HA integration** — recovers within up to 30 s via the coordinator
      poll interval (``DEFAULT_POLL_INTERVAL_SECONDS`` in
      ``custom_integration/esphome_fleet/const.py``).

    So "I dropped an event" is never a user-visible bug, just a latency
    penalty on the affected consumer.
    """
    if not _subscribers:
        return
    message = {"type": event_type, **payload}
    # Snapshot to avoid mutation-during-iteration if a handler
    # unsubscribes in response.
    for q in tuple(_subscribers):
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(message)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                logger.debug("event_bus: dropping event %s on full queue", event_type)


def subscriber_count() -> int:
    """Diagnostic helper for tests and logs."""
    return len(_subscribers)
