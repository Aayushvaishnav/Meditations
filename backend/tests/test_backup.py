from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
import re
import sqlite3
import tempfile
import threading

import aiosqlite
import pytest
import sqlite_vec
from sqlalchemy.ext.asyncio import create_async_engine

from app import db
from app.backup import create_backup
from app.models import (
    AppSetting, DailyScore, FocusSession, Habit, HabitLog, JournalEntry,
    MonthlySummary, Task, TaskList, WeeklySummary,
)
from app.routers import backup


def track_directories(monkeypatch):
    directories = []
    original = tempfile.TemporaryDirectory

    def tracked(*args, **kwargs):
        directory = original(*args, **kwargs)
        directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(backup, "TemporaryDirectory", tracked)
    return directories


def test_download_complete_database(client, monkeypatch):
    directories = track_directories(monkeypatch)

    async def seed():
        async with db.get_sessionmaker()() as session:
            session.add(TaskList(id="list", name="Work"))
            session.add(Habit(id="habit", name="Walk"))
            session.add(JournalEntry(date=date(2026, 1, 1), raw_markdown="Journal", mood=4, energy=3))
            await session.commit()
            session.add(Task(id="task", list_id="list", title="Parent"))
            await session.commit()
            session.add_all([
                Task(id="child", parent_id="task", title="Child"),
                FocusSession(task_id="task", duration_minutes=25),
                HabitLog(habit_id="habit", date=date(2026, 1, 1)),
                DailyScore(date=date(2026, 1, 1), deterministic_score=80, final_score=81,
                           rubric_breakdown_json="{}", feedback="Feedback", insight="Insight"),
                WeeklySummary(week_start=date(2025, 12, 29), avg_score=81, trend="stable", wins="Win", misses="Miss"),
                MonthlySummary(month="2026-01", avg_score=81, trend="stable", narrative="Review"),
                AppSetting(key="ai_api_key", value="synthetic-test-credential"),
            ])
            await session.commit()
        async with db.get_engine().begin() as connection:
            await connection.exec_driver_sql("INSERT INTO fts_entries (content, kind, doc_id) VALUES ('Journal', 'journal', '2026-01-01')")
            return (await connection.exec_driver_sql("PRAGMA user_version")).scalar_one()

    version = client.portal.call(seed)
    response = client.post("/api/backup")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.sqlite3"
    assert response.headers["cache-control"] == "no-store"
    assert re.fullmatch(r'attachment; filename="journal-backup-\d{8}T\d{12}Z.db"', response.headers["content-disposition"])
    assert directories and all(not path.exists() for path in directories)
    with sqlite3.connect(":memory:") as snapshot:
        snapshot.deserialize(response.content)
        snapshot.enable_load_extension(True)
        sqlite_vec.load(snapshot)
        snapshot.enable_load_extension(False)
        assert snapshot.execute("PRAGMA foreign_key_check").fetchall() == []
        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert snapshot.execute("SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='tasks'").fetchall()
        assert snapshot.execute("SELECT name FROM sqlite_schema WHERE name IN ('fts_entries', 'vec_entries') ORDER BY name").fetchall() == [("fts_entries",), ("vec_entries",)]
        assert snapshot.execute("SELECT doc_id FROM fts_entries WHERE fts_entries MATCH 'Journal'").fetchall()
        assert snapshot.execute("PRAGMA user_version").fetchone() == (version,)
        assert snapshot.execute("SELECT title, parent_id FROM tasks WHERE id='child'").fetchone() == ("Child", "task")
        assert snapshot.execute("SELECT list_id FROM tasks WHERE id='task'").fetchone() == ("list",)
        assert snapshot.execute("SELECT raw_markdown, mood, energy FROM journal_entries").fetchone() == ("Journal", 4, 3)
        assert snapshot.execute("SELECT final_score FROM daily_scores").fetchone() == (81,)
        assert snapshot.execute("SELECT wins FROM weekly_summaries").fetchone() == ("Win",)
        assert snapshot.execute("SELECT narrative FROM monthly_summaries").fetchone() == ("Review",)
        assert snapshot.execute("SELECT task_id, duration_minutes FROM focus_sessions").fetchone() == ("task", 25)
        assert snapshot.execute("SELECT habit_id, completed FROM habit_logs").fetchone() == ("habit", 1)
        assert snapshot.execute("SELECT value FROM app_settings WHERE key='ai_api_key'").fetchone() == ("synthetic-test-credential",)


@pytest.mark.parametrize("partial_file", [False, True])
def test_creation_failure_cleans_directory(client, monkeypatch, partial_file):
    directories = track_directories(monkeypatch)

    async def fail(engine, destination):
        if partial_file:
            destination.write_bytes(b"partial")
        raise RuntimeError("backup failed")

    monkeypatch.setattr(backup, "create_backup", fail)
    with pytest.raises(RuntimeError, match="backup failed"):
        client.post("/api/backup")
    assert directories and all(not path.exists() for path in directories)


def test_send_failure_cleans_directory():
    async def run():
        directory = tempfile.TemporaryDirectory(prefix="journal-backup-test-")
        path = Path(directory.name)
        (path / "backup.db").write_bytes(b"snapshot")
        response = backup.BackupResponse(directory, "backup.db")

        async def send(message):
            raise RuntimeError("disconnected")

        async def receive():
            return {"type": "http.disconnect"}

        with pytest.raises(RuntimeError, match="disconnected"):
            await response({"type": "http", "method": "POST", "headers": []}, receive, send)
        assert not path.exists()

    asyncio.run(run())


def test_online_wal_backup_is_nonblocking_and_transactionally_consistent(tmp_path, monkeypatch):
    async def run():
        source = tmp_path / "source.db"
        destination = tmp_path / "snapshot.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
        paused = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = aiosqlite.Connection.backup
        intercepted = False

        async def controlled_backup(connection, target, **kwargs):
            def progress(status, remaining, total):
                nonlocal intercepted
                if remaining and not intercepted:
                    intercepted = True
                    loop.call_soon_threadsafe(paused.set)
                    assert release.wait(10), "writer did not release backup"

            await original(connection, target, pages=1, progress=progress, sleep=0)

        monkeypatch.setattr(aiosqlite.Connection, "backup", controlled_backup)
        try:
            async with aiosqlite.connect(source) as writer:
                await writer.execute("PRAGMA journal_mode=WAL")
                await writer.execute("PRAGMA wal_autocheckpoint=0")
                await writer.execute("CREATE TABLE related (id INTEGER PRIMARY KEY, generation INTEGER, payload BLOB)")
                await writer.executemany("INSERT INTO related VALUES (?, 0, zeroblob(8192))", [(i,) for i in range(64)])
                await writer.commit()
                task = asyncio.create_task(create_backup(engine, destination))
                try:
                    await asyncio.wait_for(paused.wait(), 10)
                    # This write runs on the event loop while the backup worker is paused.
                    await writer.execute("BEGIN IMMEDIATE")
                    await writer.execute("UPDATE related SET generation=1 WHERE id=0")
                    await writer.execute("UPDATE related SET generation=1 WHERE id=1")
                    await writer.commit()
                    await writer.execute("BEGIN IMMEDIATE")
                    await writer.execute("UPDATE related SET generation=2 WHERE id=0")
                    assert Path(f"{source}-wal").stat().st_size > 0
                    release.set()
                    await asyncio.wait_for(task, 10)
                    with sqlite3.connect(destination) as snapshot:
                        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                        assert snapshot.execute("SELECT generation FROM related WHERE id IN (0,1) ORDER BY id").fetchall() == [(1,), (1,)]
                    await writer.rollback()
                finally:
                    release.set()
                    if not task.done():
                        await asyncio.wait_for(task, 10)
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("worker_error", [False, True])
def test_cancellation_drains_worker_before_connections_close(tmp_path, monkeypatch, worker_error):
    from sqlalchemy import event

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'source.db'}")
        paused = asyncio.Event()
        release = threading.Event()
        worker_finished = asyncio.Event()
        loop = asyncio.get_running_loop()
        original_backup = aiosqlite.Connection.backup
        original_close = aiosqlite.Connection.close
        closed = []
        checked_in = []

        @event.listens_for(engine.sync_engine, "checkin")
        def checkin(*args):
            checked_in.append(True)

        async def controlled(connection, target, **kwargs):
            def progress(*args):
                loop.call_soon_threadsafe(paused.set)
                assert release.wait(10), "backup worker was not released"

            native = asyncio.create_task(original_backup(connection, target, progress=progress))
            try:
                await asyncio.shield(native)
            except asyncio.CancelledError:
                release.set()
                await native
                raise
            finally:
                worker_finished.set()
            if worker_error:
                raise RuntimeError("worker failed after cancellation")

        async def close(connection):
            # Release before closing if the implementation regresses; avoid a native race.
            if not release.is_set():
                release.set()
            closed.append(True)
            await worker_finished.wait()
            await original_close(connection)

        try:
            async with engine.begin() as connection:
                await connection.exec_driver_sql("CREATE TABLE example (id INTEGER)")
            checked_in.clear()
            monkeypatch.setattr(aiosqlite.Connection, "backup", controlled)
            monkeypatch.setattr(aiosqlite.Connection, "close", close)
            task = asyncio.create_task(create_backup(engine, tmp_path / "snapshot.db"))
            try:
                await asyncio.wait_for(paused.wait(), 10)
                for attempt in range(3):
                    task.cancel("original cancellation" if attempt == 0 else "repeated cancellation")
                    await asyncio.sleep(0)
                    await asyncio.sleep(0)
                    assert not closed and not checked_in and not task.done()
                release.set()
                with pytest.raises(asyncio.CancelledError, match="original cancellation"):
                    await asyncio.wait_for(task, 10)
                assert closed and checked_in
            finally:
                release.set()
                if not task.done():
                    try:
                        await asyncio.wait_for(task, 10)
                    except asyncio.CancelledError:
                        pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_creation_cancellation_cleans_directory(client, monkeypatch):
    directories = track_directories(monkeypatch)

    async def cancel(engine, destination):
        destination.write_bytes(b"partial")
        raise asyncio.CancelledError

    monkeypatch.setattr(backup, "create_backup", cancel)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await backup.download_backup()

    client.portal.call(run)
    assert directories and all(not path.exists() for path in directories)


def test_send_cancellation_cleans_directory():
    async def run():
        directory = tempfile.TemporaryDirectory(prefix="journal-backup-test-")
        path = Path(directory.name)
        (path / "backup.db").write_bytes(b"snapshot")
        response = backup.BackupResponse(directory, "backup.db")

        async def send(message):
            raise asyncio.CancelledError

        async def receive():
            return {"type": "http.disconnect"}

        with pytest.raises(asyncio.CancelledError):
            await response({"type": "http", "method": "POST", "headers": []}, receive, send)
        assert not path.exists()

    asyncio.run(run())
