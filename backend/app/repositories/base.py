"""A deliberately thin generic repository.

WHY a repository at all — the honest answer
-------------------------------------------
The usual justification ("so we can swap the database") is a fantasy; nobody
swaps Postgres for MongoDB behind an interface. The repository earns its place
here for two concrete reasons:

1. **Query reuse.** ``get_by_slug``, ``list_page`` and the eager-loading
   options for a given aggregate would otherwise be copy-pasted into every
   service, and the copy that forgets ``selectinload`` is the one that ships the
   N+1 to production.
2. **Testability.** Services take a repository, so a unit test can pass a fake
   without standing up a database.

What it deliberately does NOT do: hide SQLAlchemy. Services are free to write a
bespoke ``select()`` when a query is genuinely one-off. A repository that forces
every query through ``find_by(**kwargs)`` ends up reimplementing SQL badly —
that is the abstraction tax this codebase refuses to pay (spec §49).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import strategy_options

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reads ────────────────────────────────────────────────────────────
    async def get(
        self, entity_id: uuid.UUID, *options: strategy_options._AbstractLoad
    ) -> ModelT | None:
        stmt = select(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        if options:
            stmt = stmt.options(*options)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by(self, **filters: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**filters).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by(
        self,
        *,
        order_by: Any = None,
        limit: int | None = None,
        offset: int = 0,
        options: Sequence[strategy_options._AbstractLoad] = (),
        **filters: Any,
    ) -> list[ModelT]:
        stmt: Select = select(self.model).filter_by(**filters)
        if options:
            stmt = stmt.options(*options)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        return int((await self.session.execute(stmt)).scalar_one())

    async def exists(self, **filters: Any) -> bool:
        stmt = select(func.count()).select_from(self.model).filter_by(**filters).limit(1)
        return bool((await self.session.execute(stmt)).scalar_one())

    async def paginate(
        self,
        stmt: Select,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ModelT], int]:
        """Run a query and its COUNT in one round of work.

        NOTE the ``order_by(None)`` on the count query: Postgres will happily
        sort rows it is only going to count, and on a large table that dominates
        the query time. This is the kind of detail the Database missions teach.
        """
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        rows = (
            (await self.session.execute(stmt.limit(page_size).offset((page - 1) * page_size)))
            .scalars()
            .all()
        )
        return list(rows), total

    # ── Writes ───────────────────────────────────────────────────────────
    def add(self, entity: ModelT) -> ModelT:
        """Stage an insert.

        Not ``async`` and it does not commit: the *request* owns the transaction
        boundary (see ``app/db/session.py``). A repository that commits per call
        makes atomic multi-step operations impossible.
        """
        self.session.add(entity)
        return entity

    def add_all(self, entities: Sequence[ModelT]) -> None:
        self.session.add_all(list(entities))

    async def flush(self) -> None:
        """Push pending SQL so server-generated values are readable — still no commit."""
        await self.session.flush()

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)

    async def delete_by(self, **filters: Any) -> int:
        result = await self.session.execute(delete(self.model).filter_by(**filters))
        return int(result.rowcount or 0)
