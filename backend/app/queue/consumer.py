"""The consumer loop and the handler registry.

WHY ACKNOWLEDGEMENT IS NOT A HANDLER'S JOB: the single most common way a queue
loses messages is a handler that returns early without acking, or acks before
the work commits. Here the loop owns it — a handler that returns has succeeded,
a handler that raises gets retried, and a handler that raises too many times is
dead-lettered. There is no ack in the handler signature to get wrong.

Handlers must be idempotent. Both backends deliver at least once, so every
handler will eventually run twice on the same event.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.config import get_settings
from app.core.logging import get_logger
from app.queue.base import Event, EventType

log = get_logger("consumer")

Handler = Callable[[Event], Awaitable[None]]

#: Several handlers may react to one event, and they are independent: an
#: analytics handler failing must not stop the leaderboard one.
_HANDLERS: dict[EventType, list[Handler]] = {}


def on(event_type: EventType) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        _HANDLERS.setdefault(event_type, []).append(handler)
        return handler

    return register


def handlers_for(event_type: EventType) -> list[Handler]:
    return list(_HANDLERS.get(event_type, []))


def registered_types() -> list[str]:
    return sorted(str(t) for t in _HANDLERS)


async def dispatch(event: Event) -> tuple[int, list[str]]:
    """Run every handler for this event. Returns (succeeded, failures).

    Handlers are run in sequence rather than concurrently: they mostly write to
    the same player's rows, and concurrent writes to one row is a deadlock
    waiting to be discovered under load rather than in a test.
    """
    failures: list[str] = []
    succeeded = 0

    for handler in handlers_for(event.type):
        name = getattr(handler, "__name__", repr(handler))
        try:
            await handler(event)
            succeeded += 1
        except Exception as exc:
            # One failing handler must not prevent the others from running, so
            # this collects rather than propagates. The event is retried as a
            # whole afterwards, which is why handlers must be idempotent.
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            log.error(
                "consumer.handler_failed",
                handler=name,
                event_type=str(event.type),
                event_id=event.event_id,
                attempt=event.attempt,
                error=str(exc)[:300],
            )

    if not handlers_for(event.type):
        # Not an error — an event nobody consumes yet is fine — but it is worth
        # seeing, because it is also what a typo'd event type looks like.
        log.debug("consumer.no_handlers", event_type=str(event.type))

    return succeeded, failures


async def run_memory_consumer(queue, stop: asyncio.Event) -> None:
    """Drain an in-process queue until asked to stop.

    Retry is immediate rather than backed off: these handlers fail because of a
    transient database blip, and the periodic jobs are the safety net for
    anything that genuinely cannot be applied.
    """
    max_attempts = get_settings().queue_max_delivery_attempts
    log.info("consumer.started", backend="memory", handles=registered_types())

    while not stop.is_set():
        # The timeout is the stop-check: without it this blocks forever on an
        # idle queue and shutdown hangs until something is published.
        try:
            async with asyncio.timeout(0.5):
                event = await queue.receive()
        except TimeoutError:
            continue

        _succeeded, failures = await dispatch(event)
        if not failures:
            continue

        if event.attempt >= max_attempts:
            await queue.dead_letter(event, "; ".join(failures))
        else:
            await queue.requeue(event.retry())

    log.info("consumer.stopped", backend="memory")


async def run_servicebus_consumer(queue, stop: asyncio.Event) -> None:
    """Consume from Service Bus, letting the broker own retry and dead-letter.

    This is the difference worth seeing next to the in-process version: the
    broker already implements delivery counting, lock renewal and a real
    dead-letter sub-queue, so the loop *completes* or *abandons* a message and
    the infrastructure does the rest. Reimplementing that on top would be
    fighting it.
    """
    from azure.servicebus.exceptions import ServiceBusError

    client = queue._service_bus_client()
    max_attempts = get_settings().queue_max_delivery_attempts
    log.info("consumer.started", backend="servicebus", handles=registered_types())

    while not stop.is_set():
        try:
            async with client.get_queue_receiver(queue.queue_name, max_wait_time=5) as receiver:
                async for message in receiver:
                    if stop.is_set():
                        await receiver.abandon_message(message)
                        break

                    import json

                    try:
                        event = Event.from_json_dict(json.loads(str(message)))
                    except Exception as exc:
                        # Unparseable means no retry will ever help, so it goes
                        # straight to the dead-letter queue rather than looping
                        # until the delivery count runs out.
                        log.error("consumer.undecodable", error=str(exc)[:200])
                        await receiver.dead_letter_message(
                            message, reason="undecodable", error_description=str(exc)[:200]
                        )
                        continue

                    _succeeded, failures = await dispatch(event)
                    if not failures:
                        await receiver.complete_message(message)
                        continue

                    delivery_count = getattr(message, "delivery_count", 0) or 0
                    if delivery_count + 1 >= max_attempts:
                        await receiver.dead_letter_message(
                            message,
                            reason="handler_failed",
                            error_description="; ".join(failures)[:400],
                        )
                    else:
                        # Abandon puts it back and increments the delivery
                        # count, which is the broker's own retry budget.
                        await receiver.abandon_message(message)
        except ServiceBusError as exc:
            # A broker outage must not kill the worker. Back off and retry the
            # *connection*; the messages are still on the broker.
            log.error("consumer.transport_error", error=str(exc)[:200])
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise

    log.info("consumer.stopped", backend="servicebus")
