import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import stat

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import LATEST_VERSION, MIGRATIONS
from app.recovery import RecoveryError, checkpoint_database, restore_database


def database(path: Path, version: int = LATEST_VERSION, label: str = "backup") -> Path:
    async def create():
        engine = create_async_engine("sqlite+aiosqlite:///" + str(path))
        try:
            async with engine.begin() as conn:
                for migration in MIGRATIONS[:max(version, 1)]:
                    await migration(conn)
                await conn.exec_driver_sql(f"PRAGMA user_version={version}")
                await conn.exec_driver_sql(
                    "INSERT INTO app_settings VALUES ('label', ?, '2026-01-01')", (label,)
                )
        finally:
            await engine.dispose()
    asyncio.run(create())
    return path


def label(path: Path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT value FROM app_settings WHERE key='label'").fetchone()[0]


@pytest.mark.parametrize("version", [0, 1, 2, 3, LATEST_VERSION])
def test_restore_migrates_private_copy(tmp_path, version):
    backup = database(tmp_path / "backup.db", version)
    original = backup.read_bytes()
    target = database(tmp_path / "current.db", label="current")
    checkpoint = asyncio.run(restore_database(backup, target))
    assert label(target) == "backup"
    assert label(checkpoint) == "current"
    assert backup.read_bytes() == original
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    assert stat.S_IMODE(checkpoint.parent.stat().st_mode) == 0o700
    with closing(sqlite3.connect(target)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
    assert not list(tmp_path.glob(".restore-*"))


@pytest.mark.parametrize("damage", ["newer", "missing_table", "missing_column", "unrelated", "malformed", "foreign_key"])
def test_rejects_backup_without_changing_destination(tmp_path, damage):
    backup = database(tmp_path / "backup.db")
    target = database(tmp_path / "current.db", label="current")
    if damage == "malformed":
        backup.write_bytes(b"not sqlite")
    else:
        with sqlite3.connect(backup) as conn:
            if damage == "newer":
                conn.execute(f"PRAGMA user_version={LATEST_VERSION + 1}")
            elif damage == "missing_table":
                conn.execute("DROP TABLE review_jobs")
            elif damage == "missing_column":
                conn.execute("DROP TRIGGER calendar_queue_task_update")
                conn.execute("ALTER TABLE tasks DROP COLUMN title")
            elif damage == "unrelated":
                for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    conn.execute(f'DROP TABLE "{table}"')
            else:
                conn.execute("INSERT INTO habit_logs VALUES ('orphan','missing','2026-01-01',1)")
    before = target.read_bytes()
    with pytest.raises(RecoveryError):
        asyncio.run(restore_database(backup, target))
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".restore-*"))


def test_missing_backup_does_not_create_source(tmp_path):
    backup = tmp_path / "absent.db"
    with pytest.raises(RecoveryError):
        asyncio.run(restore_database(backup, tmp_path / "target.db"))
    assert not backup.exists()
    assert not (tmp_path / "target.db").exists()


def test_checkpoint_includes_wal_and_never_overwrites(tmp_path):
    source = database(tmp_path / "current.db")
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE app_settings SET value='wal'")
        conn.commit()
        first = checkpoint_database(source, "upgrade")
        second = checkpoint_database(source, "upgrade")
        assert first != second
        assert label(first) == label(second) == "wal"
        assert Path(str(source) + "-wal").exists()


def test_replace_failure_preserves_current_and_checkpoint(tmp_path, monkeypatch):
    backup = database(tmp_path / "backup.db")
    target = database(tmp_path / "current.db", label="current")
    def fail(*args):
        raise OSError("replacement failed")
    monkeypatch.setattr("app.recovery.os.replace", fail)
    with pytest.raises(OSError, match="replacement failed"):
        asyncio.run(restore_database(backup, target))
    assert label(target) == "current"
    checkpoints = list((tmp_path / "recovery").glob("*.db"))
    assert len(checkpoints) == 1
    assert label(checkpoints[0]) == "current"
    assert not list(tmp_path.glob(".restore-*"))


def test_restore_refuses_cooperative_lock_contention(tmp_path):
    from app.database_lock import DatabaseLock
    backup = database(tmp_path / "backup.db")
    target = database(tmp_path / "current.db", label="current")
    with DatabaseLock(target):
        with pytest.raises(RuntimeError):
            asyncio.run(restore_database(backup, target))
    assert label(target) == "current"


def test_restore_wal_current_checkpoint(tmp_path):
    backup = database(tmp_path / "backup.db")
    target = database(tmp_path / "current.db")
    # A crashed process leaves committed frames in WAL without a closing checkpoint
    import subprocess
    import sys
    subprocess.run([sys.executable, "-c", """
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute('PRAGMA journal_mode=WAL')
conn.execute("UPDATE app_settings SET value='wal-current'")
conn.commit()
os._exit(0)
""", str(target)], check=True)
    assert Path(str(target) + "-wal").stat().st_size > 0
    checkpoint = asyncio.run(restore_database(backup, target))
    assert label(checkpoint) == "wal-current"
    assert label(target) == "backup"


def test_virtual_tables_and_older_migration(tmp_path):
    import sqlite_vec
    backup = database(tmp_path / "backup.db", version=1)
    with closing(sqlite3.connect(backup)) as conn:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("CREATE VIRTUAL TABLE vectors USING vec0(embedding float[2])")
        conn.execute("INSERT INTO vectors VALUES (1, '[1, 0]')")
        conn.execute("CREATE VIRTUAL TABLE search_fts USING fts5(content)")
        conn.execute("INSERT INTO search_fts VALUES ('hello')")
        conn.commit()
    target = tmp_path / "target.db"
    assert asyncio.run(restore_database(backup, target)) is None
    with closing(sqlite3.connect(target)) as conn:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        assert conn.execute("SELECT count(*) FROM vectors").fetchone()[0] == 1
        assert conn.execute("SELECT content FROM search_fts").fetchone()[0] == 'hello'


def test_migration_failure_leaves_destination_untouched(tmp_path, monkeypatch):
    backup = database(tmp_path / "backup.db", version=1)
    target = database(tmp_path / "current.db", label="current")
    before = target.read_bytes()
    async def fail(*args, **kwargs):
        raise RuntimeError("migration failed")
    monkeypatch.setattr("app.recovery.migrate", fail)
    with pytest.raises(RuntimeError, match="migration failed"):
        asyncio.run(restore_database(backup, target))
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".restore-*"))


def test_cli(tmp_path, capsys):
    from app.recovery import main
    backup = database(tmp_path / "backup.db")
    target = tmp_path / "target.db"
    main(["restore", str(backup), "--database", str(target)])
    assert label(target) == "backup"
    assert str(target) in capsys.readouterr().out


@pytest.mark.parametrize('damage', ['unique', 'foreign_key', 'collation'])
def test_rejects_missing_schema_constraints(tmp_path, damage):
    backup = database(tmp_path / 'backup.db')
    with sqlite3.connect(backup) as conn:
        if damage in ('unique', 'collation'):
            conn.execute('DROP INDEX uq_task_recurrence_occurrence')
            if damage == 'collation':
                conn.execute('CREATE UNIQUE INDEX uq_task_recurrence_occurrence ON tasks '
                             '(recurrence_series_id COLLATE NOCASE, recurrence_occurrence)')
        else:
            conn.execute('ALTER TABLE habit_logs RENAME TO old_logs')
            conn.execute('CREATE TABLE habit_logs (id VARCHAR NOT NULL PRIMARY KEY, '
                         'habit_id VARCHAR NOT NULL, date DATE NOT NULL, completed BOOLEAN NOT NULL, '
                         'UNIQUE(habit_id, date))')
            conn.execute('DROP TABLE old_logs')
    with pytest.raises(RecoveryError, match='incompatible schema'):
        asyncio.run(restore_database(backup, tmp_path / 'target.db'))


def test_missing_search_indexes_rebuilt_after_restore(tmp_path, monkeypatch):
    from app import search
    from app.db import _load_vec_extension
    from sqlalchemy import event, text
    from sqlmodel.ext.asyncio.session import AsyncSession
    backup = database(tmp_path / 'backup.db')
    with sqlite3.connect(backup) as conn:
        conn.execute("INSERT INTO monthly_summaries VALUES ('2026-01',80,'stable',"
                     "'mountain expedition','2026-01-01')")
    target = tmp_path / 'target.db'
    asyncio.run(restore_database(backup, target))
    monkeypatch.setattr(search, 'embed_texts', lambda texts: [[1.0] + [0.0] * 383 for _ in texts])
    monkeypatch.setattr(search, '_vec_ready', False)
    async def rebuild():
        engine = create_async_engine('sqlite+aiosqlite:///' + str(target))
        event.listen(engine.sync_engine, 'connect', lambda conn, _: _load_vec_extension(conn))
        try:
            async with engine.begin() as conn:
                await search.init_search(conn)
            async with AsyncSession(engine) as session:
                assert await search.backfill_missing(session) == 1
                hits = await search.search(session, 'mountain')
                assert len(hits) == 1
                assert set(hits[0].sources) == {'fts', 'semantic'}
                assert (await session.execute(text('SELECT count(*) FROM vec_entries'))).scalar_one() == 1
        finally:
            await engine.dispose()
    asyncio.run(rebuild())


@pytest.mark.parametrize('trigger', [
    'calendar_queue_block_update', 'calendar_queue_task_update', 'calendar_queue_block_delete',
])
@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_restore_rejects_missing_or_changed_capture_trigger(tmp_path, trigger, damage):
    backup = database(tmp_path / 'backup.db')
    target = database(tmp_path / 'current.db', label='current')
    with sqlite3.connect(backup) as conn:
        sql = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (trigger,)).fetchone()[0]
        conn.execute(f'DROP TRIGGER {trigger}')
        if damage == 'changed':
            conn.execute(sql.replace('local_revision + 1', 'local_revision + 2'))
    original_backup, original_target = backup.read_bytes(), target.read_bytes()
    with pytest.raises(RecoveryError, match=f'incompatible schema for trigger {trigger}'):
        asyncio.run(restore_database(backup, target))
    assert target.read_bytes() == original_target
    assert backup.read_bytes() == original_backup
    assert not list(tmp_path.glob('.restore-*'))
