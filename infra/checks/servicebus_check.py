"""Run from the repo root with the backend venv:

    backend/.venv/Scripts/python infra/checks/servicebus_check.py

Not part of `pytest`: these need an emulator running, and the default test run
must not assume one is.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

import asyncio
import os

CONN = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)
os.environ["QUEUE_BACKEND"] = "servicebus"
os.environ["SERVICEBUS_CONNECTION_STRING"] = CONN
os.environ["SERVICEBUS_QUEUE"] = "aiforge-events"
os.environ["QUEUE_MAX_DELIVERY_ATTEMPTS"] = "3"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.queue import Event, EventType, build_queue, reset_queue  # noqa: E402
from app.queue import consumer as consumer_module  # noqa: E402
from app.queue.consumer import run_servicebus_consumer  # noqa: E402


def head(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


async def main():
    reset_queue()
    queue = build_queue(get_settings())
    print(f"backend: {queue.name} -> {queue.queue_name}")

    head("1. HEALTHCHECK")
    healthy, detail = await queue.healthcheck()
    print(f"   {healthy} - {detail}")
    assert healthy, detail

    head("2. PUBLISH AND CONSUME")
    received = []

    async def record(event):
        received.append(event)

    saved = dict(consumer_module._HANDLERS)
    consumer_module._HANDLERS.clear()
    consumer_module._HANDLERS[EventType.SUBMISSION_GRADED] = [record]
    try:
        stop = asyncio.Event()
        task = asyncio.create_task(run_servicebus_consumer(queue, stop))

        await queue.publish(
            Event(
                type=EventType.SUBMISSION_GRADED,
                partition_key="player-1",
                payload={"profile_id": "player-1", "challenge_slug": "py-dedupe", "score": 0.9},
            )
        )
        for _ in range(60):
            if received:
                break
            await asyncio.sleep(0.5)
        stop.set()
        await asyncio.sleep(0.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        print(f"   received: {len(received)}")
        assert received, "nothing arrived from the broker"
        event = received[0]
        print(f"   type    : {event.type}")
        print(f"   payload : {event.payload}")
        print(f"   key     : {event.partition_key}")
        assert event.payload["challenge_slug"] == "py-dedupe"
        assert event.partition_key == "player-1"
        print("   round-tripped through a real broker")
    finally:
        consumer_module._HANDLERS.clear()
        consumer_module._HANDLERS.update(saved)

    head("3. A FAILING HANDLER IS RETRIED, THEN DEAD-LETTERED BY THE BROKER")
    attempts = []

    async def always_fails(event):
        attempts.append(event.event_id)
        raise RuntimeError("handler is broken")

    saved = dict(consumer_module._HANDLERS)
    consumer_module._HANDLERS.clear()
    consumer_module._HANDLERS[EventType.MISSION_COMPLETED] = [always_fails]
    try:
        stop = asyncio.Event()
        task = asyncio.create_task(run_servicebus_consumer(queue, stop))
        await queue.publish(
            Event(
                type=EventType.MISSION_COMPLETED,
                partition_key="player-2",
                payload={"profile_id": "player-2"},
            )
        )
        for _ in range(60):
            if len(attempts) >= 3:
                break
            await asyncio.sleep(0.5)
        stop.set()
        await asyncio.sleep(0.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        print(f"   delivery attempts: {len(attempts)}")
        assert len(attempts) >= 2, f"broker did not redeliver: {len(attempts)}"
        assert len(set(attempts)) == 1, "redelivery changed the event id"
        print("   same event id each time, so dedupe still applies")
    finally:
        consumer_module._HANDLERS.clear()
        consumer_module._HANDLERS.update(saved)

    head("4. THE DEAD-LETTER SUB-QUEUE HAS IT")
    from azure.servicebus.aio import ServiceBusClient

    async with ServiceBusClient.from_connection_string(CONN) as client:
        async with client.get_queue_receiver(
            "aiforge-events", sub_queue="deadletter", max_wait_time=10
        ) as receiver:
            dead = await receiver.receive_messages(max_message_count=10, max_wait_time=10)
            print(f"   dead-lettered messages: {len(dead)}")
            for message in dead:
                print(
                    f"     reason={message.dead_letter_reason!r} "
                    f"desc={(message.dead_letter_error_description or '')[:60]!r}"
                )
                await receiver.complete_message(message)
            assert dead, "nothing reached the dead-letter queue"

    await queue.close()
    print()
    print("SERVICE BUS VERIFIED AGAINST THE EMULATOR")


asyncio.run(main())
