"""Frozen, ordered SQLite schema migrations; no dependency on model metadata."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.migrations.baseline import STATEMENTS


class MigrationError(RuntimeError):
    """Startup cannot safely use this database schema."""


async def _baseline(conn: AsyncConnection) -> None:
    for statement in STATEMENTS:
        await conn.exec_driver_sql(statement)


async def _recurrence_identity(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN recurrence_series_id VARCHAR")
    await conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN recurrence_occurrence INTEGER")
    await conn.exec_driver_sql(
        "UPDATE tasks SET recurrence_series_id = id, recurrence_occurrence = 0 "
        "WHERE recurrence_rule IS NOT NULL AND recurrence_rule != ''"
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX uq_task_recurrence_occurrence "
        "ON tasks (recurrence_series_id, recurrence_occurrence)"
    )


async def _search_vector_state(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "CREATE TABLE search_vector_state ("
        "doc_id VARCHAR NOT NULL PRIMARY KEY, state VARCHAR NOT NULL)"
    )


async def _review_jobs(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "CREATE TABLE review_jobs (kind VARCHAR NOT NULL, period VARCHAR NOT NULL, "
        "state VARCHAR NOT NULL, PRIMARY KEY (kind, period))"
    )


MIGRATIONS: tuple[Callable[[AsyncConnection], Awaitable[None]], ...] = (
    _baseline,
    _recurrence_identity,
    _search_vector_state,
    _review_jobs,
)
LATEST_VERSION = len(MIGRATIONS)


async def migrate(engine: AsyncEngine, *, checkpoint: bool = True) -> None:
    """Serialize startup writers and atomically apply every pending migration."""
    async with engine.connect() as conn:
        version = 0
        target = 0
        try:
            # SQLite legacy transaction mode does not BEGIN for DDL; force it
            await conn.exec_driver_sql("BEGIN IMMEDIATE")
            version = int((await conn.exec_driver_sql("PRAGMA user_version")).scalar_one())
            if version > LATEST_VERSION:
                raise MigrationError(
                    f"Database schema version {version} is newer than supported version "
                    f"{LATEST_VERSION}; upgrade Journal before opening this database."
                )
            has_tables = (await conn.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%')"
            )).scalar_one()
            if (checkpoint and version < LATEST_VERSION and has_tables
                    and engine.url.database not in (None, "", ":memory:")):
                from app.recovery import checkpoint_database

                worker = asyncio.create_task(asyncio.to_thread(
                    checkpoint_database, Path(engine.url.database), "pre-upgrade"
                ))
                cancelled = False
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        cancelled = True
                recovery_path = worker.result()
                if cancelled:
                    raise asyncio.CancelledError
                logging.getLogger(__name__).warning(
                    "Pre-upgrade database checkpoint saved: %s", recovery_path
                )
            for target in range(version + 1, LATEST_VERSION + 1):
                await MIGRATIONS[target - 1](conn)
                await conn.exec_driver_sql(f"PRAGMA user_version = {target}")
            await conn.commit()
        except Exception as exc:
            await conn.rollback()
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError(
                f"Database migration v{target or version} failed; database intact "
                f"at version {version}. Resolve the cause and retry startup: {exc}"
            ) from exc
