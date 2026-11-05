"""Frozen, ordered SQLite schema migrations; no dependency on model metadata."""

from __future__ import annotations

from app.migrations.webhooks import migrate_webhooks
from app.migrations.calendar_inbound import migrate_calendar_inbound

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.migrations.task_classification import migrate_task_classification
from app.migrations.task_null_tags import migrate_task_null_tags
from app.migrations.baseline import STATEMENTS
from app.migrations.calendar_import import migrate_calendar_import
from app.migrations.calendar_sync_status import migrate_calendar_sync_status
from app.migrations.calendar_dispatches import migrate_calendar_dispatches
from app.migrations.calendar_credentials import migrate_calendar_credentials
from app.migrations.calendar_queue import migrate_calendar_queue
from app.migrations.calendar_sync import migrate_calendar_sync
from app.migrations.time_block_shapes import migrate_time_block_shapes


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


async def _task_deadlines(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "ALTER TABLE tasks ADD COLUMN deadline_date DATE "
        "CONSTRAINT ck_task_deadline_exclusive "
        "CHECK (due_date IS NULL OR deadline_date IS NULL)"
    )
    await conn.exec_driver_sql("CREATE INDEX ix_tasks_deadline_date ON tasks (deadline_date)")


async def _time_blocks(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "CREATE TABLE time_blocks ("
        "id VARCHAR NOT NULL PRIMARY KEY, task_id VARCHAR NOT NULL, "
        "start_at DATETIME NOT NULL, end_at DATETIME NOT NULL, "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
        "CONSTRAINT ck_time_block_interval CHECK (end_at > start_at), "
        "FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE)"
    )
    for column in ("task_id", "start_at", "end_at"):
        await conn.exec_driver_sql(f"CREATE INDEX ix_time_blocks_{column} ON time_blocks ({column})")


MIGRATIONS: tuple[Callable[[AsyncConnection], Awaitable[None]], ...] = (
    _baseline,
    _recurrence_identity,
    _search_vector_state,
    _review_jobs,
    _task_deadlines,
    _time_blocks,
    migrate_time_block_shapes,
    migrate_calendar_sync,
    migrate_calendar_credentials,
    migrate_calendar_dispatches,
    migrate_calendar_queue,
    migrate_calendar_sync_status,
    migrate_calendar_import,
    migrate_webhooks,
    migrate_calendar_inbound,
    migrate_task_classification,
    migrate_task_null_tags,
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
