from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from app.database_lock import DatabaseInUseError, DatabaseLock


def acquire_in_child(database: str, result) -> None:
    try:
        with DatabaseLock(Path(database)):
            result.put("acquired")
    except DatabaseInUseError:
        result.put("in-use")


def test_lock_excludes_other_process_and_releases_after_exit(tmp_path):
    database = tmp_path / "journal.db"
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    with DatabaseLock(database):
        child = context.Process(target=acquire_in_child, args=(str(database), result))
        child.start()
        assert result.get(timeout=15) == "in-use"
        child.join(timeout=15)
        assert child.exitcode == 0
    with DatabaseLock(database):
        pass
    assert Path(f"{database}.lock").exists()


def test_lock_resolves_symlink_alias(tmp_path):
    database = tmp_path / "journal.db"
    database.touch()
    alias = tmp_path / "alias.db"
    alias.symlink_to(database)
    with DatabaseLock(database):
        with pytest.raises(DatabaseInUseError):
            with DatabaseLock(alias):
                pass


@pytest.mark.anyio
async def test_engine_holds_lock_until_disposed(tmp_path):
    from app import db

    database = tmp_path / "journal.db"
    db.init_engine(f"sqlite+aiosqlite:///{database}")
    try:
        with pytest.raises(DatabaseInUseError):
            with DatabaseLock(database):
                pass
    finally:
        await db.dispose_engine()
    with DatabaseLock(database):
        pass


@pytest.mark.anyio
async def test_failed_startup_disposes_engine_and_releases_lock(tmp_path, monkeypatch):
    from app import db
    from app.main import app, lifespan

    database = tmp_path / "journal.db"
    db.init_engine(f"sqlite+aiosqlite:///{database}")

    async def fail():
        raise RuntimeError("injected startup failure")

    monkeypatch.setattr(db, "init_db", fail)
    with pytest.raises(RuntimeError, match="injected"):
        async with lifespan(app):
            pytest.fail("Startup must not succeed")
    assert not db.engine_initialized()
    with DatabaseLock(database):
        pass


@pytest.mark.anyio
async def test_cancelled_disposal_retains_lock_until_connections_close(tmp_path, monkeypatch):
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncEngine
    from app import db

    database = tmp_path / "journal.db"
    engine = db.init_engine(f"sqlite+aiosqlite:///{database}")
    original = AsyncEngine.dispose
    started, release = asyncio.Event(), asyncio.Event()

    async def suspended(self):
        started.set()
        await release.wait()
        await original(self)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(AsyncEngine, "dispose", suspended)
            task = asyncio.create_task(db.dispose_engine())
            await started.wait()
            task.cancel()
            turn = asyncio.Event()
            asyncio.get_running_loop().call_soon(turn.set)
            await turn.wait()
            try:
                with pytest.raises(DatabaseInUseError):
                    with DatabaseLock(database):
                        pass
                assert db.engine_initialized()
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
        assert not db.engine_initialized()
        with DatabaseLock(database):
            pass
    finally:
        await db.dispose_engine()
        await original(engine)


@pytest.mark.anyio
async def test_disposal_error_keeps_engine_and_lock_for_retry(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncEngine
    from app import db

    database = tmp_path / "journal.db"
    engine = db.init_engine(f"sqlite+aiosqlite:///{database}")

    async def fail(self):
        raise RuntimeError("connection disposal failed")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(AsyncEngine, "dispose", fail)
            with pytest.raises(RuntimeError, match="connection disposal failed"):
                await db.dispose_engine()
            assert db.get_engine() is engine
            with pytest.raises(DatabaseInUseError):
                with DatabaseLock(database):
                    pass
    finally:
        await db.dispose_engine()
    with DatabaseLock(database):
        pass
