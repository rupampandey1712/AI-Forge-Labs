"""Shared schema building blocks.

WHY a custom base: ``from_attributes`` is needed on almost every response model
(we serialise ORM objects directly), and ``populate_by_name`` lets us expose
camelCase to TypeScript while keeping snake_case in Python. Setting these once
beats repeating ``model_config`` in fifty classes and forgetting it in the
fifty-first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Schema(BaseModel):
    """Request/response base."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
        ser_json_timedelta="float",
    )


class Page(Schema, Generic[T]):
    """Offset pagination envelope.

    TRADEOFF vs. cursor pagination: offset is O(n) deep into a table and can
    skip/duplicate rows when data shifts mid-scroll. We use it because every
    paginated list here is bounded (a player's own attempts, a filtered content
    list) and jump-to-page matters more than deep-scroll stability. The
    leaderboard, which *is* unbounded, is served from a snapshot table instead.
    """

    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))


class PaginationParams(Schema):
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class ErrorDetail(Schema):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(Schema):
    error: ErrorDetail


class Message(Schema):
    message: str
    ok: bool = True


class HealthStatus(Schema):
    status: str
    version: str
    environment: str
    database: str
    cache: str
    sandbox: str
    checked_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)
