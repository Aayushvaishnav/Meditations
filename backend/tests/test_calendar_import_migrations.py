"""v13 rollback/retry, metadata equivalence and SQLite recovery preservation."""
import asyncio
from contextlib import closing
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.recovery import _contract, checkpoint_database, restore_database

TABLES = ('calendar_import_sources', 'calendar_import_snapshots', 'calendar_import_events')


@pytest.mark.anyio
async def test_v13_atomic_rollback_retry_and_metadata_equivalence(monkeypatch):
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    try:
        real = migrations.MIGRATIONS
        assert len(real) >= 13
        async with engine.begin() as conn:
            for migration in real[:12]:
                await migration(conn)
            await conn.exec_driver_sql('PRAGMA user_version=12')
            await conn.exec_driver_sql("INSERT INTO app_settings VALUES ('sentinel','keep','2026-01-01')")

        async def fail(conn):
            await real[12](conn)
            raise RuntimeError('injected import failure')

        with monkeypatch.context() as patch:
            patch.setattr(migrations, 'MIGRATIONS', (*real[:12], fail))
            with pytest.raises(migrations.MigrationError, match='database intact at version 12'):
                await migrations.migrate(engine)
        async with engine.connect() as conn:
            assert (await conn.exec_driver_sql('PRAGMA user_version')).scalar_one() == 12
            assert (await conn.exec_driver_sql("SELECT value FROM app_settings WHERE key='sentinel'")).scalar_one() == 'keep'
            assert (await conn.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE name LIKE 'calendar_import_%'")).scalar_one() == 0
        await migrations.migrate(engine)
        await migrations.migrate(engine)
        async with engine.begin() as conn:
            expected = await conn.run_sync(lambda sync: _contract(sync.exec_driver_sql))
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)
            actual = await conn.run_sync(lambda sync: _contract(sync.exec_driver_sql))
            for table in TABLES:
                assert actual[table] == expected[table]
    finally:
        await engine.dispose()


def test_sqlite_checkpoint_restore_preserves_opaque_imports(tmp_path):
    backup = tmp_path / 'imported.db'

    async def create():
        engine = create_async_engine('sqlite+aiosqlite:///' + str(backup))
        try:
            await migrations.migrate(engine)
            async with engine.begin() as conn:
                await conn.exec_driver_sql("INSERT INTO calendar_import_sources VALUES ('source','Original','2026-01-01','2026-01-01')")
                await conn.exec_driver_sql("INSERT INTO calendar_import_snapshots VALUES ('snapshot','source',?,?,'2026-01-01')",
                                           ('exact original\r\nunknown properties\r\n', 'timezone context'))
                await conn.exec_driver_sql("INSERT INTO calendar_import_events VALUES "
                    "('event','source','snapshot','identity','uid','summary','floating','20260101T120000',"
                    "NULL,NULL,'unspecified','CANCELLED',1,'20260101T130000',NULL,'original component',2)")
        finally:
            await engine.dispose()

    asyncio.run(create())
    checkpoint = checkpoint_database(backup, 'calendar-import-test')
    destination = tmp_path / 'restored.db'
    asyncio.run(restore_database(checkpoint, destination))
    with closing(sqlite3.connect(backup)) as before, closing(sqlite3.connect(destination)) as after:
        for table in TABLES:
            assert before.execute(f'SELECT * FROM {table}').fetchall() == after.execute(f'SELECT * FROM {table}').fetchall()
        assert after.execute('PRAGMA foreign_key_check').fetchall() == []
        assert after.execute('PRAGMA user_version').fetchone() == (migrations.LATEST_VERSION,)
