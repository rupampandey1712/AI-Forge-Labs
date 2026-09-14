"""Portable column types.

The game must run on SQLite (zero-setup first run, fast tests) *and* on
PostgreSQL (the real target, and the subject of the SQLAlchemy missions).
``with_variant`` lets one model definition compile to the best native type on
each dialect instead of forcing a lowest-common-denominator schema.
"""

from __future__ import annotations

from sqlalchemy import JSON, DateTime, Text, TypeDecorator, Uuid
from sqlalchemy.dialects import postgresql

# JSONB gives Postgres indexing + containment operators; SQLite falls back to
# JSON-as-TEXT, which is fine because we never query into JSON on SQLite.
JSONB = JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")

# SQLAlchemy 2's Uuid renders native UUID on Postgres and CHAR(32) on SQLite.
GUID = Uuid(as_uuid=True)


class UTCDateTime(TypeDecorator):
    """``DateTime(timezone=True)`` that *guarantees* aware UTC values come back.

    WHY: SQLite has no timezone support, so a value written as aware UTC reads
    back naive — and naive/aware comparisons then explode at runtime inside the
    retention engine. Normalising in one type decorator kills a whole class of
    bug instead of sprinkling ``.replace(tzinfo=UTC)`` across the codebase.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        from datetime import UTC

        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        from datetime import UTC

        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
