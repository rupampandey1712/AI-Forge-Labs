"""Declarative base and the mixins every table shares."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.db.types import GUID, UTCDateTime

# Explicit constraint naming is what makes Alembic autogenerate produce
# reversible migrations — without it, dropping an unnamed constraint on
# Postgres requires hand-written SQL.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """UUID PKs.

    TRADEOFF vs. bigint identity: UUIDs cost ~8 extra bytes per row and index,
    and random v4 values fragment B-trees. We accept that because IDs are
    generated client-side in tests/seeds, are safe to expose in URLs (no row
    count leak), and this app's tables are thousands of rows, not billions.
    """

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class SlugMixin:
    """Stable human-readable key for content rows.

    Content is authored in Python/JSON packs and re-seeded on every deploy. If
    rows were identified only by UUID, a re-seed would orphan every player's
    progress. The slug is the content's real identity; the UUID is storage.
    """

    @declared_attr
    def slug(cls) -> Mapped[str]:
        return mapped_column(unique=True, index=True, nullable=False)
