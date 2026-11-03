from __future__ import annotations

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.recovery import _contract


@pytest.fixture
async def engine():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    yield engine
    await engine.dispose()


@pytest.mark.anyio
async def test_dispatch_migration_atomic_retry_and_legacy_preservation(engine, monkeypatch):
    real = migrations.MIGRATIONS
    async with engine.begin() as conn:
        for migration in real[:9]:
            await migration(conn)
        await conn.exec_driver_sql('PRAGMA user_version=9')
        await conn.exec_driver_sql(
            "INSERT INTO calendar_connections VALUES "
            "('c','https://example.test','https://example.test/events/','connected',1,"
            "'2026-01-01','2026-01-01','present')")
        await conn.exec_driver_sql(
            "INSERT INTO calendar_links VALUES "
            "('l','c',NULL,'b','uid','https://example.test/events/a.ics',NULL,"
            "'error',2,0,'delete','unprepared',NULL,'present','uncertain',"
            "'2026-01-01','2026-01-01')")
        before = (await conn.exec_driver_sql('SELECT * FROM calendar_links')).all()

    async def fail(conn):
        await real[9](conn)
        raise RuntimeError('injected dispatch DDL failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', (*real[:9], fail, *real[10:]))
        with pytest.raises(migrations.MigrationError, match='injected dispatch DDL failure'):
            await migrations.migrate(engine)
    async with engine.connect() as conn:
        assert (await conn.exec_driver_sql('PRAGMA user_version')).scalar_one() == 9
        assert not (await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name='calendar_dispatches'")).all()
        assert (await conn.exec_driver_sql('SELECT * FROM calendar_links')).all() == before
    await migrations.migrate(engine)
    await migrations.migrate(engine)
    async with engine.begin() as conn:
        after = (await conn.exec_driver_sql('SELECT * FROM calendar_links')).all()
        assert [tuple(row[:len(before[0])]) for row in after] == [tuple(row) for row in before]
        assert after[0][-3] == 'unknown'
        assert after[0][-2] is None
        with pytest.raises(IntegrityError):
            await conn.exec_driver_sql("UPDATE calendar_links SET acknowledged_action='invalid'")
        await conn.exec_driver_sql(
            "INSERT INTO calendar_dispatches VALUES "
            "('l',2,'delete','https://example.test/events/a.ics','uid',NULL,NULL,1)")
        for statement in [
            'UPDATE calendar_dispatches SET revision=0',
            "UPDATE calendar_dispatches SET action='unknown'",
            "UPDATE calendar_dispatches SET action='upsert'",
            "UPDATE calendar_dispatches SET payload='unexpected'",
            'UPDATE calendar_dispatches SET attempted=2',
            "UPDATE calendar_dispatches SET link_id='missing'",
        ]:
            with pytest.raises(IntegrityError):
                await conn.exec_driver_sql(statement)
        await conn.exec_driver_sql("DELETE FROM calendar_links WHERE id='l'")
        assert not (await conn.exec_driver_sql('SELECT * FROM calendar_dispatches')).all()
        assert not (await conn.exec_driver_sql('PRAGMA foreign_key_check')).all()


async def contract(conn):
    def read(sync):
        tables = ('calendar_dispatches', 'calendar_links')
        return ({name: _contract(sync.exec_driver_sql)[name] for name in tables},
                {name: inspect(sync).get_check_constraints(name) for name in tables})
    return await conn.run_sync(read)


@pytest.mark.anyio
async def test_dispatch_metadata_matches_frozen_ddl_and_restore_contract(engine):
    await migrations.migrate(engine)
    async with engine.connect() as conn:
        expected = await contract(conn)
    other = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    try:
        async with other.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            assert await contract(conn) == expected
    finally:
        await other.dispose()
