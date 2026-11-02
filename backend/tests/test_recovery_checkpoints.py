from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app import migrations


async def legacy_database(path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await migrations.MIGRATIONS[0](conn)
        await conn.exec_driver_sql("PRAGMA user_version=1")
        await conn.exec_driver_sql(
            "INSERT INTO app_settings VALUES ('setting', 'preserved', '2026-01-01')"
        )
    return engine


def snapshot_contents(path):
    with sqlite3.connect(path) as conn:
        return (
            conn.execute("PRAGMA user_version").fetchone()[0],
            conn.execute("SELECT value FROM app_settings").fetchone()[0],
        )


@pytest.mark.anyio
async def test_upgrade_saves_old_version_and_data_once(tmp_path):
    path = tmp_path / "journal.db"
    engine = await legacy_database(path)
    try:
        await migrations.migrate(engine)
        checkpoints = list((tmp_path / "recovery").glob("*.db"))
        assert len(checkpoints) == 1
        assert snapshot_contents(checkpoints[0]) == (1, "preserved")
        assert snapshot_contents(path) == (migrations.LATEST_VERSION, "preserved")
        await migrations.migrate(engine)
        assert list((tmp_path / "recovery").glob("*.db")) == checkpoints
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_failed_upgrade_retains_checkpoint_and_retries(tmp_path, monkeypatch):
    path = tmp_path / "journal.db"
    engine = await legacy_database(path)
    original = migrations.MIGRATIONS

    async def fail(conn):
        await original[1](conn)
        raise ValueError("injected migration failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(migrations, "MIGRATIONS", (original[0], fail, *original[2:]))
            with pytest.raises(migrations.MigrationError, match="database intact at version 1"):
                await migrations.migrate(engine)
        assert snapshot_contents(path) == (1, "preserved")
        checkpoint, = (tmp_path / "recovery").glob("*.db")
        assert snapshot_contents(checkpoint) == (1, "preserved")
        await migrations.migrate(engine)
        assert snapshot_contents(path) == (migrations.LATEST_VERSION, "preserved")
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_checkpoint_failure_prevents_any_schema_changes(tmp_path, monkeypatch):
    from app import recovery

    path = tmp_path / "journal.db"
    engine = await legacy_database(path)

    def fail(*args):
        raise OSError("checkpoint storage unavailable")

    monkeypatch.setattr(recovery, "checkpoint_database", fail)
    try:
        with pytest.raises(migrations.MigrationError, match="checkpoint storage unavailable"):
            await migrations.migrate(engine)
        assert snapshot_contents(path) == (1, "preserved")
        with sqlite3.connect(path) as conn:
            assert "recurrence_series_id" not in {
                row[1] for row in conn.execute("PRAGMA table_info(tasks)")
            }
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_fresh_and_newer_databases_do_not_create_checkpoints(tmp_path):
    path = tmp_path / "journal.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        await migrations.migrate(engine)
        assert not (tmp_path / "recovery").exists()
        async with engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA user_version=999")
        with pytest.raises(migrations.MigrationError, match="newer"):
            await migrations.migrate(engine)
        assert not (tmp_path / "recovery").exists()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_cancelled_startup_drains_checkpoint_before_releasing_ownership(tmp_path, monkeypatch):
    import asyncio
    import threading
    from app import db, recovery
    from app.database_lock import DatabaseInUseError, DatabaseLock
    from app.main import app, lifespan

    path = tmp_path / "journal.db"
    engine = await legacy_database(path)
    await engine.dispose()
    db.init_engine(f"sqlite+aiosqlite:///{path}")
    original = recovery.checkpoint_database
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def suspended(*args):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(15), "checkpoint was not released"
        return original(*args)

    async def startup():
        async with lifespan(app):
            pytest.fail("Cancelled startup must not serve requests")

    monkeypatch.setattr(recovery, "checkpoint_database", suspended)
    task = asyncio.create_task(startup())
    await started.wait()
    task.cancel()
    turn = asyncio.Event()
    loop.call_soon(turn.set)
    await turn.wait()
    try:
        assert db.engine_initialized()
        with pytest.raises(DatabaseInUseError):
            with DatabaseLock(path):
                pass
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not db.engine_initialized()
    assert snapshot_contents(path) == (1, "preserved")
    checkpoint, = (tmp_path / "recovery").glob("*.db")
    assert snapshot_contents(checkpoint) == (1, "preserved")
    with DatabaseLock(path):
        pass
