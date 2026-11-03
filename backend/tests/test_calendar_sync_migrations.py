from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.models import CalendarConnection, CalendarLink, Task, TimeBlock
from app.recovery import _contract


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    yield engine
    await engine.dispose()


async def seed_source(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Task(id="task", title="Existing task"))
        await session.flush()
        session.add(TimeBlock(id="block", task_id="task", kind="all_day",
                              timezone=None, start_date=date(2026, 1, 1),
                              end_date=date(2026, 1, 2)))
        await session.commit()


async def snapshot(engine):
    async with engine.connect() as conn:
        return (
            (await conn.exec_driver_sql("PRAGMA user_version")).scalar_one(),
            (await conn.exec_driver_sql("SELECT * FROM tasks")).all(),
            (await conn.exec_driver_sql("SELECT * FROM time_blocks")).all(),
            (await conn.exec_driver_sql(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
            )).all(),
        )


@pytest.mark.anyio
async def test_v8_upgrade_preserves_sources_and_rolls_back_then_retries(engine, monkeypatch):
    real = migrations.MIGRATIONS
    async with engine.begin() as conn:
        for migration in real[:7]:
            await migration(conn)
        await conn.exec_driver_sql("PRAGMA user_version=7")
    await seed_source(engine)
    before = await snapshot(engine)

    async def fail(conn):
        await real[7](conn)
        raise RuntimeError("injected after calendar DDL")

    monkeypatch.setattr(migrations, "MIGRATIONS", (*real[:7], fail, *real[8:]))
    with pytest.raises(migrations.MigrationError, match="injected after calendar DDL"):
        await migrations.migrate(engine)
    assert await snapshot(engine) == before
    monkeypatch.setattr(migrations, "MIGRATIONS", real)
    await migrations.migrate(engine)
    after = await snapshot(engine)
    assert after[0] == migrations.LATEST_VERSION
    assert after[1:3] == before[1:3]
    async with engine.connect() as conn:
        assert (await conn.exec_driver_sql("SELECT count(*) FROM calendar_links")).scalar_one() == 0
        assert (await conn.exec_driver_sql("SELECT count(*) FROM calendar_connections")).scalar_one() == 0


async def schema_contract(conn):
    def read(sync):
        inspector = inspect(sync)
        return (
            {table: contract for table, contract in _contract(sync.exec_driver_sql).items()
             if table in ("calendar_connections", "calendar_links")},
            {table: inspector.get_check_constraints(table)
             for table in ("calendar_connections", "calendar_links")},
        )
    return await conn.run_sync(read)


@pytest.mark.anyio
async def test_metadata_matches_frozen_migration_and_recovery_contract(engine):
    await migrations.migrate(engine)
    async with engine.connect() as conn:
        expected = await schema_contract(conn)
    other = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with other.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            assert await schema_contract(conn) == expected
    finally:
        await other.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("delete_table", ["tasks", "time_blocks"])
async def test_tombstone_survives_deletion_and_connection_is_restricted(engine, metadata, delete_table):
    if metadata:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        await migrations.migrate(engine)
    await seed_source(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        connection = CalendarConnection(id="connection", server_url="https://example.test",
                                        calendar_url="https://example.test/calendar/")
        session.add(connection)
        await session.flush()
        link = CalendarLink(id="link", connection_id=connection.id, block_id="block",
                            local_block_id="block", uid="stable-uid", resource_url="event.ics")
        session.add(link)
        await session.commit()
        assert connection.state == "disconnected" and not connection.enabled
        assert (link.state, link.local_revision, link.acknowledged_revision) == ("pending", 1, 0)
        assert (link.payload_state, link.payload, link.error_state, link.last_error, link.etag) == (
            "unprepared", None, "none", None, None)
    async with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.exec_driver_sql("DELETE FROM calendar_connections")
        await conn.exec_driver_sql(f"DELETE FROM {delete_table}")
        row = (await conn.exec_driver_sql(
            "SELECT block_id,local_block_id,uid,resource_url,desired_action FROM calendar_links"
        )).one()
        assert tuple(row) == (None, "block", "stable-uid", "event.ics",
                              "upsert" if metadata else "delete")
        assert not (await conn.exec_driver_sql("PRAGMA foreign_key_check")).all()
        for assignment in (
            "state='unlinked'", "desired_action='unknown'", "local_revision=0",
            "acknowledged_revision=-1", "acknowledged_revision=3", "payload_state='prepared'",
            "payload='data'", "error_state='present'", "last_error='failure'", "error_state='unknown'",
            "payload_state='unknown'", "connection_id='missing'", "block_id='missing'",
        ):
            with pytest.raises(IntegrityError):
                await conn.exec_driver_sql(f"UPDATE calendar_links SET {assignment}")
        await conn.exec_driver_sql(
            "UPDATE calendar_links SET payload_state='prepared',payload='serialized',"
            "error_state='present',last_error='retry',state='error',desired_action='delete',"
            "etag='known',local_revision=2,acknowledged_revision=1"
        )
        for columns, values in (
            ("id", "'duplicate'"),
            ("id,local_block_id", "'duplicate','other-block'"),
            ("id,resource_url", "'duplicate','other.ics'"),
        ):
            replacements = dict(zip(columns.split(','), values.split(',')))
            names = [c['name'] for c in await conn.run_sync(lambda sync: inspect(sync).get_columns('calendar_links'))]
            projection = ','.join(replacements.get(name, name) for name in names)
            with pytest.raises(IntegrityError):
                await conn.exec_driver_sql(f"INSERT INTO calendar_links SELECT {projection} FROM calendar_links")
        with pytest.raises(IntegrityError):
            await conn.exec_driver_sql("UPDATE calendar_connections SET state='unknown'")


@pytest.mark.anyio
async def test_identity_is_global_but_resource_url_is_destination_scoped(engine):
    await migrations.migrate(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for identity in ("first", "second"):
            session.add(CalendarConnection(id=identity, server_url="https://example.test",
                                           calendar_url=f"https://example.test/{identity}/"))
        await session.flush()
        session.add(CalendarLink(connection_id="first", local_block_id="block",
                                 uid="uid", resource_url="event.ics"))
        await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(CalendarLink(connection_id="second", local_block_id="block",
                                         uid="uid", resource_url="other.ics"))
                await session.flush()
        session.add(CalendarLink(connection_id="second", local_block_id="different-block",
                                 uid="different-uid", resource_url="event.ics"))
        await session.commit()
