"""Frozen status migration preserves unknown history and rolls back DDL."""
import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.recovery import _contract

pytestmark = pytest.mark.anyio


async def test_status_migration_atomic_retry_preserves_legacy_history(monkeypatch):
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    try:
        real = migrations.MIGRATIONS
        async with engine.begin() as conn:
            for migration in real[:11]:
                await migration(conn)
            await conn.exec_driver_sql('PRAGMA user_version=11')
            await conn.exec_driver_sql("INSERT INTO calendar_connections VALUES "
                "('c','https://example.test/','https://example.test/cal/','connected',0,"
                "'2026-01-01','2026-01-01','present')")
            await conn.exec_driver_sql("INSERT INTO calendar_links VALUES "
                "('l','c',NULL,'b','uid','https://example.test/cal/a.ics','etag',"
                "'synced',1,1,'upsert','unprepared',NULL,'none',NULL,"
                "'2026-01-01','2026-01-01','upsert')")
            before = (await conn.exec_driver_sql('SELECT * FROM calendar_links')).all()

        async def fail(conn):
            await real[11](conn)
            raise RuntimeError('injected status failure')

        with monkeypatch.context() as patch:
            patch.setattr(migrations, 'MIGRATIONS', (*real[:11], fail))
            with pytest.raises(migrations.MigrationError, match='database intact at version 11'):
                await migrations.migrate(engine)
        async with engine.connect() as conn:
            assert (await conn.exec_driver_sql('PRAGMA user_version')).scalar_one() == 11
            assert (await conn.exec_driver_sql('SELECT * FROM calendar_links')).all() == before
        await migrations.migrate(engine)
        await migrations.migrate(engine)
        async with engine.connect() as conn:
            after = (await conn.exec_driver_sql('SELECT * FROM calendar_links')).all()
            assert tuple(after[0][:-2]) == tuple(before[0])
            assert after[0][-2] is None
            assert after[0][-1] == 'opted_in'
            expected = await conn.run_sync(lambda sync: _contract(sync.exec_driver_sql)['calendar_links'])
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)
            actual = await conn.run_sync(lambda sync: _contract(sync.exec_driver_sql)['calendar_links'])
            assert actual == expected
            assert 'last_synced_at' in await conn.run_sync(
                lambda sync: {col['name'] for col in inspect(sync).get_columns('calendar_links')})
    finally:
        await engine.dispose()
