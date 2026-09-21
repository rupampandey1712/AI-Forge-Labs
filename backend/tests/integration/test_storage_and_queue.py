"""Storage and the event queue.

These test the properties that are the same across both backends, because the
whole value of the seam is that swapping the backend changes nothing a caller
can see. The emulator-backed legs (Azurite, Service Bus) are verified by the
scripts in `infra/`; what is here runs with nothing installed and nothing
running, which is the path most people will use.
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from app.queue import consumer as consumer_module
from app.queue.backends import MemoryQueue
from app.queue.base import Event, EventType, QueueError
from app.queue.consumer import dispatch, run_memory_consumer
from app.storage.backends import MAX_OBJECT_BYTES, LocalStorage
from app.storage.base import StorageError, content_hash, validate_key
from app.storage.service import figure_key

pytestmark = [pytest.mark.integration]

PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "artifacts")


@pytest.fixture
def isolated_handlers():
    """Swap the global registry out and back.

    The registry is module-level by design — handlers register at import — so a
    test that appends to it leaks into every later test in the session.
    """
    saved = dict(consumer_module._HANDLERS)
    consumer_module._HANDLERS.clear()
    yield consumer_module._HANDLERS
    consumer_module._HANDLERS.clear()
    consumer_module._HANDLERS.update(saved)


class TestStorageKeysAreNotAttackerControlled:
    """Keys are built from a challenge slug and a profile id, so they are user
    input by the time they reach the filesystem."""

    @pytest.mark.parametrize(
        "key",
        [
            "../../etc/passwd",
            "figures/../../../secrets.txt",
            "/absolute/path.png",
            "figures//double.png",
            "figures/\x00null.png",
            "",
            "a" * 300,
        ],
    )
    def test_traversal_and_junk_are_rejected(self, key):
        with pytest.raises(StorageError):
            validate_key(key)

    async def test_a_crafted_key_cannot_escape_the_root(self, storage, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("do not overwrite me", encoding="utf-8")
        with pytest.raises(StorageError):
            await storage.put("../outside.txt", b"overwritten")
        assert outside.read_text(encoding="utf-8") == "do not overwrite me"


class TestLocalStorageIsNotAStub:
    async def test_round_trips(self, storage):
        ref = await storage.put("figures/p1/c1/a.png", PNG, content_type="image/png")
        assert ref.size_bytes == len(PNG)
        assert ref.content_type == "image/png"
        assert await storage.get("figures/p1/c1/a.png") == PNG
        assert await storage.exists("figures/p1/c1/a.png")

    async def test_a_missing_object_is_none_not_an_error(self, storage):
        """The distinction the whole error model rests on: absent is normal,
        broken is an incident."""
        assert await storage.get("figures/p1/c1/nope.png") is None
        assert await storage.exists("figures/p1/c1/nope.png") is False
        assert await storage.delete("figures/p1/c1/nope.png") is False

    async def test_oversized_objects_are_refused(self, storage):
        with pytest.raises(StorageError, match="over the"):
            await storage.put("figures/p1/c1/big.png", b"x" * (MAX_OBJECT_BYTES + 1))

    async def test_no_temporary_files_are_left_behind(self, storage, tmp_path):
        """The atomic write uses a temp file; leaving them would fill the disk
        with `.tmp` slowly enough that nobody notices until it is full."""
        await storage.put("figures/p1/c1/a.png", PNG)
        leftovers = list((tmp_path / "artifacts").rglob("*.tmp"))
        assert leftovers == [], leftovers

    async def test_the_url_is_the_api_path_not_a_storage_path(self, storage):
        """Swapping backends must change nothing the browser sees."""
        ref = await storage.put("figures/p1/c1/a.png", PNG)
        assert ref.url == "/api/v1/artifacts/figures/p1/c1/a.png"
        assert str(storage.root) not in ref.url


class TestContentAddressing:
    def test_identical_bytes_give_identical_keys(self):
        """This is what makes redelivery idempotent rather than duplicating."""
        assert figure_key("p1", "c1", PNG) == figure_key("p1", "c1", PNG)

    def test_different_bytes_give_different_keys(self):
        assert figure_key("p1", "c1", PNG) != figure_key("p1", "c1", PNG + b"x")

    def test_the_key_is_scoped_to_the_player(self):
        """Ownership is enforced by the key layout, so it has to be in there."""
        assert figure_key("p1", "c1", PNG).split("/")[1] == "p1"

    def test_hashes_are_short_and_stable(self):
        assert len(content_hash(PNG)) == 20
        assert content_hash(PNG) == content_hash(PNG)


class TestEventSerialisation:
    def test_round_trips_through_json(self):
        original = Event(
            type=EventType.SUBMISSION_GRADED,
            partition_key="p1",
            payload={"profile_id": "p1", "score": 0.83},
        )
        restored = Event.from_json_dict(original.to_json_dict())
        assert restored.type == original.type
        assert restored.payload == original.payload
        assert restored.event_id == original.event_id
        assert restored.partition_key == original.partition_key

    def test_a_retry_keeps_the_event_id(self):
        """Dedupe is keyed on the id, so a retry that minted a new one would
        make every handler's idempotency guard useless."""
        original = Event(type=EventType.SUBMISSION_GRADED, payload={})
        retried = original.retry()
        assert retried.event_id == original.event_id
        assert retried.attempt == original.attempt + 1
        assert retried.dedupe_key == original.dedupe_key

    def test_an_unknown_event_type_is_rejected(self):
        with pytest.raises(ValueError):
            Event.from_json_dict({"type": "not.a.real.event", "payload": {}})


class TestTheConsumerOwnsDelivery:
    async def test_one_failing_handler_does_not_stop_the_others(self, isolated_handlers):
        """Handlers are independent: analytics failing must not cost you the
        leaderboard update."""
        ran = []

        async def fails(event):
            raise RuntimeError("nope")

        async def works(event):
            ran.append(event.event_id)

        isolated_handlers[EventType.SUBMISSION_GRADED] = [fails, works]
        succeeded, failures = await dispatch(Event(type=EventType.SUBMISSION_GRADED, payload={}))
        assert ran, "the second handler never ran"
        assert succeeded == 1
        assert len(failures) == 1

    async def test_an_event_with_no_handlers_is_not_an_error(self, isolated_handlers):
        succeeded, failures = await dispatch(Event(type=EventType.INTERVIEW_FINISHED, payload={}))
        assert (succeeded, failures) == (0, [])

    async def test_retries_are_bounded_then_dead_lettered(self, isolated_handlers, monkeypatch):
        """The property that matters: a broken handler must not redeliver
        forever, and the message must not vanish either."""
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "queue_max_delivery_attempts", 3)
        attempts = []

        async def always_fails(event):
            attempts.append(event.attempt)
            raise RuntimeError("handler is broken")

        isolated_handlers[EventType.SUBMISSION_GRADED] = [always_fails]

        queue = MemoryQueue()
        stop = asyncio.Event()
        task = asyncio.create_task(run_memory_consumer(queue, stop))
        await queue.publish(Event(type=EventType.SUBMISSION_GRADED, payload={}))

        for _ in range(40):
            if queue.dead_letters:
                break
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=3)

        assert attempts == [1, 2, 3], attempts
        assert len(queue.dead_letters) == 1
        _event, reason = queue.dead_letters[0]
        assert "handler is broken" in reason

    async def test_a_successful_event_is_not_retried(self, isolated_handlers):
        calls = []

        async def works(event):
            calls.append(event.event_id)

        isolated_handlers[EventType.SUBMISSION_GRADED] = [works]

        queue = MemoryQueue()
        stop = asyncio.Event()
        task = asyncio.create_task(run_memory_consumer(queue, stop))
        await queue.publish(Event(type=EventType.SUBMISSION_GRADED, payload={}))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(task, timeout=3)

        assert len(calls) == 1, calls
        assert not queue.dead_letters

    async def test_an_idle_consumer_still_shuts_down(self):
        """`receive` blocks; without the timeout wrapping it, shutdown hangs
        until something happens to be published."""
        queue = MemoryQueue()
        stop = asyncio.Event()
        task = asyncio.create_task(run_memory_consumer(queue, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, timeout=3)
        assert task.done()


class TestPublishingNeverFailsTheCaller:
    async def test_a_full_queue_raises_at_the_backend(self):
        queue = MemoryQueue(maxsize=1)
        await queue.publish(Event(type=EventType.SUBMISSION_GRADED, payload={}))
        with pytest.raises(QueueError):
            await queue.publish(Event(type=EventType.SUBMISSION_GRADED, payload={}))

    async def test_but_the_module_level_publish_swallows_it(self, monkeypatch):
        """A submission must never 500 because a background event could not be
        queued — the grade is already committed and the derived data is rebuilt
        by the periodic jobs anyway."""
        from app import queue as queue_module

        class Broken:
            name = "broken"

            async def publish(self, event):
                raise QueueError("broker is down")

        monkeypatch.setattr(queue_module, "_queue", Broken())
        await queue_module.publish(Event(type=EventType.SUBMISSION_GRADED, payload={}))


class TestBackendSelectionFailsLoudly:
    def test_blob_without_a_connection_string_raises(self):
        from app.core.config import Settings
        from app.storage.service import build_storage

        with pytest.raises(StorageError, match="BLOB_CONNECTION_STRING"):
            build_storage(Settings(storage_backend="blob", blob_connection_string=""))

    def test_servicebus_without_a_connection_string_raises(self):
        from app.core.config import Settings
        from app.queue import build_queue

        with pytest.raises(QueueError, match="SERVICEBUS_CONNECTION_STRING"):
            build_queue(Settings(queue_backend="servicebus", servicebus_connection_string=""))

    def test_the_defaults_need_nothing_running(self):
        """The zero-setup path: no emulator, no connection string, no extra."""
        from app.core.config import Settings
        from app.queue import build_queue
        from app.storage.service import build_storage

        cfg = Settings()
        assert build_storage(cfg).name == "local"
        assert build_queue(cfg).name == "memory"
