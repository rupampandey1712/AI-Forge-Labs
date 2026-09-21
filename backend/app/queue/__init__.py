"""Event queue: per-player work moved off the request path.

See ``base.py`` for why this exists alongside the periodic scheduler rather
than replacing it — they carry different classes of work, and conflating them
is how you end up with either a broker running a cron job or a cron job
pretending to be an event bus.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.queue.base import Event, EventQueue, EventType, QueueError
from app.queue.consumer import dispatch, handlers_for, on, registered_types

log = get_logger(__name__)

_queue: EventQueue | None = None


def build_queue(cfg: Settings) -> EventQueue:
    from app.queue.backends import MemoryQueue, ServiceBusQueue

    if cfg.queue_backend == "servicebus":
        if not cfg.servicebus_connection_string:
            # Loud rather than a silent downgrade to in-process: a deployment
            # that thinks its events survive a restart and does not is a data
            # loss you find out about during an incident.
            raise QueueError("QUEUE_BACKEND=servicebus requires SERVICEBUS_CONNECTION_STRING.")
        return ServiceBusQueue(cfg.servicebus_connection_string, cfg.servicebus_queue)
    return MemoryQueue()


def get_queue() -> EventQueue:
    global _queue
    if _queue is None:
        _queue = build_queue(get_settings())
        log.info("queue.initialised", backend=_queue.name)
    return _queue


def reset_queue() -> None:
    """Drop the cached instance. For tests that switch backends."""
    global _queue
    _queue = None


async def publish(event: Event) -> None:
    """Fire and forget, and *never* fail the caller.

    A submission must not 500 because a background analytics event could not be
    queued. The player's grade is already committed; the derived data this
    event rebuilds is also rebuilt by the periodic jobs, so dropping one is a
    freshness problem rather than a correctness one — and that is exactly the
    trade that makes swallowing the error the right call here rather than a
    shrug.
    """
    try:
        await get_queue().publish(event)
    except Exception as exc:
        log.error(
            "queue.publish_swallowed",
            event_type=str(event.type),
            error=str(exc)[:200],
        )


__all__ = [
    "Event",
    "EventQueue",
    "EventType",
    "QueueError",
    "build_queue",
    "dispatch",
    "get_queue",
    "handlers_for",
    "on",
    "publish",
    "registered_types",
    "reset_queue",
]
