"""Alembic environment — async-aware, single source of truth for the URL.

WHY ``run_sync``: Alembic's migration machinery is synchronous. The standard
async recipe opens an async connection and hands its *sync* facade to Alembic
via ``connection.run_sync``. Fighting that and writing raw asyncpg migrations
buys nothing and loses autogenerate.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy import types as sa_types
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings

# Importing the registry populates Base.metadata for autogenerate.
from app.models import Base  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context) -> str | bool:  # noqa: ANN001
    """Render our custom column types as *self-contained* SQLAlchemy expressions.

    WHY: by default Alembic emits ``app.db.types.UTCDateTime()`` into the
    migration, which couples a historical migration to today's application code.
    Delete or rename that class in six months and every old migration breaks.
    Migrations must be replayable against an empty database using nothing but
    SQLAlchemy, so we flatten our decorators to their underlying types here.
    """
    from app.db.types import UTCDateTime

    if type_ == "type":
        if isinstance(obj, UTCDateTime):
            return "sa.DateTime(timezone=True)"
        if isinstance(obj, sa_types.Variant) or getattr(obj, "_variant_mapping", None):
            autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
            return 'sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")'
    return False


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Detect column type changes (e.g. String(50) -> String(80)); off by
        # default in Alembic and a frequent source of "the migration ran but
        # the column is still wrong".
        compare_type=True,
        compare_server_default=True,
        render_item=render_item,
        # SQLite cannot ALTER most things; batch mode rewrites the table.
        render_as_batch=settings.is_sqlite,
        include_schemas=False,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_item=render_item,
        render_as_batch=settings.is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
