from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database_lock import DatabaseLock

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_database_lock: DatabaseLock | None = None


def _is_memory(url: str) -> bool:
    return ":memory:" in url


def init_engine(db_url: str) -> AsyncEngine:
    """(Re)create the global engine. Called on app startup and by tests."""
    global _engine, _sessionmaker, _database_lock

    if _database_lock is not None:
        raise RuntimeError("Dispose the current database engine before replacing it")
    kwargs: dict = {"poolclass": StaticPool} if _is_memory(db_url) else {}
    engine = create_async_engine(db_url, **kwargs)
    if engine.url.get_backend_name() == "sqlite" and not _is_memory(db_url):
        database = engine.url.database
        if database:
            lock = DatabaseLock(Path(database))
            try:
                lock.__enter__()
            except BaseException:
                engine.sync_engine.dispose()
                raise
            _database_lock = lock

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
        _load_vec_extension(dbapi_connection)

    _engine = engine
    _sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine


def _load_vec_extension(dbapi_connection) -> None:  # noqa: ANN001
    """Load sqlite-vec on each pooled connection; degrade silently if unavailable."""
    try:
        import sqlite_vec

        conn = dbapi_connection.driver_connection  # aiosqlite.Connection
        dbapi_connection.await_(conn.enable_load_extension(True))
        dbapi_connection.await_(conn.load_extension(sqlite_vec.loadable_path()))
        dbapi_connection.await_(conn.enable_load_extension(False))
    except Exception:  # noqa: BLE001 — search degrades to FTS-only
        pass


def engine_initialized() -> bool:
    return _engine is not None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised; call init_engine() first")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database engine not initialised; call init_engine() first")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def init_db() -> None:
    from app import search
    from app.migrations import migrate

    await migrate(get_engine())
    async with get_engine().begin() as conn:
        await search.init_search(conn)


async def dispose_engine() -> None:
    global _engine, _sessionmaker, _database_lock
    cancelled = False
    if _engine is not None:
        worker = asyncio.create_task(_engine.dispose())
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
        worker.result()
    _engine = None
    _sessionmaker = None
    if _database_lock is not None:
        _database_lock.__exit__()
        _database_lock = None
    if cancelled:
        raise asyncio.CancelledError
