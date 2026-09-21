"""The event contract shared by both queue backends.

WHY A QUEUE EXISTS NOW, when `workers/scheduler.py` argues against one: they
carry different work, and the distinction is the whole justification.

  * The **scheduler** runs periodic, idempotent, whole-table jobs on a timer.
    Nothing triggers them, nothing waits for them, and a missed tick is
    invisible. A queue would add a broker to run five functions on a clock.
  * The **queue** carries per-player events produced by a request: a submission
    landed, a mission completed, a figure needs storing. These are triggered by
    something a person did, and dropping one loses freshness they would notice.

The second class did not exist when the scheduler was written — those effects
ran inline in the request, which is why the leaderboard was up to fifteen
minutes stale and why a slow rollup made a submission feel slow. Moving them
off the request path is the reason for the queue; "we might need a broker" is
not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class EventType(StrEnum):
    """Every event the game publishes.

    A closed enum rather than free strings: a consumer that silently ignores a
    typo'd event type is a bug that shows up as "the leaderboard stopped
    updating" three weeks later.
    """

    SUBMISSION_GRADED = "submission.graded"
    MISSION_COMPLETED = "mission.completed"
    CONCEPT_PRACTISED = "concept.practised"
    INTERVIEW_FINISHED = "interview.finished"


@dataclass(frozen=True, slots=True)
class Event:
    """One message.

    ``dedupe_key`` exists because both backends deliver *at least* once. A
    consumer that is not idempotent will eventually double-count, and the one
    thing worse than a stale leaderboard is a wrong one.
    """

    type: EventType
    payload: dict[str, Any]
    #: The player id. A logical grouping key, not an ordering guarantee — see
    #: the note in ``backends.py``: every handler recomputes from current state
    #: rather than applying a delta, so out-of-order processing yields the same
    #: result and the queue deliberately does not use sessions. This is here so
    #: that a future handler which *does* apply a delta has the key it would
    #: need to turn FIFO on.
    partition_key: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    attempt: int = 1

    @property
    def dedupe_key(self) -> str:
        return f"{self.type}:{self.event_id}"

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": str(self.type),
            "payload": self.payload,
            "partition_key": self.partition_key,
            "occurred_at": self.occurred_at.isoformat(),
            "attempt": self.attempt,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            type=EventType(data["type"]),
            payload=data.get("payload", {}),
            partition_key=data.get("partition_key", ""),
            event_id=data.get("event_id", str(uuid.uuid4())),
            occurred_at=datetime.fromisoformat(data["occurred_at"])
            if data.get("occurred_at")
            else datetime.now(UTC),
            attempt=int(data.get("attempt", 1)),
        )

    def retry(self) -> Event:
        """The same event, one delivery later. Same id, so dedupe still works."""
        return Event(
            type=self.type,
            payload=self.payload,
            partition_key=self.partition_key,
            event_id=self.event_id,
            occurred_at=self.occurred_at,
            attempt=self.attempt + 1,
        )


class QueueError(RuntimeError):
    """Publishing or consuming failed at the transport level."""


@runtime_checkable
class EventQueue(Protocol):
    """Publish and consume. Deliberately no `peek`, no `ack` in the signature —
    acknowledgement is handled by the consumer loop so a handler cannot forget
    it, which is the most common way a queue quietly loses messages."""

    name: str

    async def publish(self, event: Event) -> None: ...

    async def publish_many(self, events: list[Event]) -> None: ...

    async def healthcheck(self) -> tuple[bool, str]: ...

    async def close(self) -> None: ...
