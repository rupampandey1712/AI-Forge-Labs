"""The two queue backends.

Both must give the consumer the same guarantees, or switching backends changes
behaviour in ways nothing tests:

  * at-least-once delivery (so handlers must be idempotent, and the dedupe key
    exists to let them be)
  * bounded retry, then dead-letter rather than infinite redelivery
  * a failing handler never kills the consumer loop

``MemoryQueue`` is not a mock. It is what the zero-setup path uses, so it
implements retry and dead-lettering for real — a development backend that
silently drops a failed message teaches you nothing until production.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque

from app.core.logging import get_logger
from app.queue.base import Event, QueueError

log = get_logger(__name__)


class MemoryQueue:
    """An in-process asyncio queue.

    The honest limitation, stated rather than discovered: messages live in this
    process. A restart loses whatever is in flight, and a second API replica has
    its own separate queue. That is acceptable for the single-player default —
    every consumer here recomputes derived data that the next periodic job would
    rebuild anyway — and it is exactly why the Service Bus backend exists for
    anything else.
    """

    name = "memory"

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        #: Bounded: a dead-letter list that grows without limit is a memory leak
        #: dressed up as an audit trail.
        self.dead_letters: deque[tuple[Event, str]] = deque(maxlen=200)

    async def publish(self, event: Event) -> None:
        try:
            # Never block a request handler on a full queue. Dropping with a
            # loud log is better than making a submission hang because a
            # background consumer fell behind.
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            log.error("queue.full", event_type=str(event.type), dropped=event.event_id)
            raise QueueError("Event queue is full.") from None

    async def publish_many(self, events: list[Event]) -> None:
        for event in events:
            await self.publish(event)

    async def receive(self) -> Event:
        """Wait for the next event.

        No timeout parameter by design (ruff ASYNC109): the caller owns
        cancellation, so the consumer loop wraps this in ``asyncio.timeout`` to
        get its periodic stop-check. Accepting a timeout here would mean two
        places could impose one and neither would compose.
        """
        return await self._queue.get()

    async def requeue(self, event: Event) -> None:
        await self.publish(event)

    async def dead_letter(self, event: Event, reason: str) -> None:
        self.dead_letters.append((event, reason))
        log.error(
            "queue.dead_lettered",
            event_type=str(event.type),
            event_id=event.event_id,
            attempts=event.attempt,
            reason=reason[:200],
        )

    def depth(self) -> int:
        return self._queue.qsize()

    async def healthcheck(self) -> tuple[bool, str]:
        return True, f"in-process queue, depth {self.depth()}, {len(self.dead_letters)} dead"

    async def close(self) -> None:
        return None


class ServiceBusQueue:
    """Azure Service Bus, against the local emulator.

    The SDK is imported lazily so the default install stays free of it.

    Note the emulator is not a stub either: it is the real broker behaviour
    (sessions, lock renewal, dead-letter queues) running locally against MSSQL,
    which is why it is worth targeting rather than pretending a dict is a queue.
    """

    name = "servicebus"

    def __init__(self, connection_string: str, queue_name: str) -> None:
        self.connection_string = connection_string
        self.queue_name = queue_name
        self._client = None

    def _service_bus_client(self):
        try:
            from azure.servicebus.aio import ServiceBusClient
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise QueueError(
                "QUEUE_BACKEND=servicebus needs the azure extra: pip install -e '.[azure]'"
            ) from exc
        if self._client is None:
            self._client = ServiceBusClient.from_connection_string(
                self.connection_string,
                # The emulator speaks AMQP over a plain socket; TLS is off
                # locally and must never be off against a real namespace.
                logging_enable=False,
            )
        return self._client

    def _to_message(self, event: Event):
        from azure.servicebus import ServiceBusMessage

        return ServiceBusMessage(
            json.dumps(event.to_json_dict()),
            content_type="application/json",
            # The broker's own dedupe window uses this, which is a second line
            # of defence behind idempotent handlers rather than a replacement
            # for them.
            message_id=event.event_id,
            # NO session_id, deliberately — and this is a correction to the
            # first version of this file, which set one.
            #
            # Sessions buy per-key FIFO at the cost of serialising consumption
            # for that key. Every handler here recomputes derived state from
            # the current database rather than applying a delta, so processing
            # two of a player's events out of order produces the same answer as
            # in order: whichever runs last reads the latest rows and writes the
            # correct result. Paying for ordering nothing needs would be a
            # throughput cost for a guarantee that changes no outcome.
            #
            # `partition_key` still travels on the event and still groups
            # logically — it is what a session-enabled queue would key on if a
            # future handler ever did apply a delta and genuinely needed FIFO.
            subject=str(event.type),
        )

    async def publish(self, event: Event) -> None:
        client = self._service_bus_client()
        try:
            async with client.get_queue_sender(self.queue_name) as sender:
                await sender.send_messages(self._to_message(event))
        except Exception as exc:
            log.error("queue.publish_failed", event_type=str(event.type), error=str(exc))
            raise QueueError(f"Could not publish to Service Bus: {exc}") from exc

    async def publish_many(self, events: list[Event]) -> None:
        if not events:
            return
        client = self._service_bus_client()
        try:
            async with client.get_queue_sender(self.queue_name) as sender:
                await sender.send_messages([self._to_message(e) for e in events])
        except Exception as exc:
            raise QueueError(f"Could not publish batch to Service Bus: {exc}") from exc

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            client = self._service_bus_client()
            async with client.get_queue_sender(self.queue_name):
                return True, f"service bus queue {self.queue_name!r}"
        except Exception as exc:
            return False, f"service bus unreachable: {type(exc).__name__}: {exc}"

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
