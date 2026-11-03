from __future__ import annotations

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.models import CalendarConnection
from app.recovery import _contract


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    yield engine
    await engine.dispose()


async def snapshot(engine):
    async with engine.connect() as conn:
        return (
            (await conn.exec_driver_sql("PRAGMA user_version")).scalar_one(),
            (await conn.exec_driver_sql(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
            )).all(),
            (await conn.exec_driver_sql("SELECT * FROM calendar_connections")).all(),
            (await conn.exec_driver_sql("SELECT * FROM calendar_links")).all(),
        )


@pytest.mark.anyio
async def test_v9_preserves_v8_rows_and_links_with_atomic_rollback_and_retry(engine, monkeypatch):
    real = migrations.MIGRATIONS
    async with engine.begin() as conn:
        for migration in real[:8]:
            await migration(conn)
        await conn.exec_driver_sql("PRAGMA user_version=8")
        await conn.exec_driver_sql(
            "INSERT INTO calendar_connections VALUES "
            "('connection','https://example.test','https://example.test/calendar/',"
            "'connected',1,'2026-01-01','2026-01-02')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO calendar_links VALUES "
            "('link','connection',NULL,'deleted-block','stable-uid','event.ics','etag',"
            "'error',3,2,'delete','prepared','BEGIN:VCALENDAR\r\nEND:VCALENDAR',"
            "'present','retry','2026-01-01','2026-01-02')"
        )
    before = await snapshot(engine)

    async def fail(conn):
        await real[8](conn)
        raise RuntimeError("injected after credential DDL")

    with monkeypatch.context() as patch:
        patch.setattr(migrations, "MIGRATIONS", (*real[:8], fail, *real[9:]))
        with pytest.raises(migrations.MigrationError, match="v9 failed; database intact at version 8"):
            await migrations.migrate(engine)
    assert await snapshot(engine) == before
    await migrations.migrate(engine)
    after = await snapshot(engine)
    assert after[0] == migrations.LATEST_VERSION
    assert tuple(after[2][0][:-1]) == tuple(before[2][0])
    assert after[2][0][-1] == "absent"
    assert [tuple(row[:len(before[3][0])]) for row in after[3]] == [tuple(row) for row in before[3]]
    assert after[3][0][-3] == "upsert"
    assert after[3][0][-2] is None
    async with engine.begin() as conn:
        assert not (await conn.exec_driver_sql("PRAGMA foreign_key_check")).all()
        with pytest.raises(IntegrityError):
            await conn.exec_driver_sql("DELETE FROM calendar_connections")
    await migrations.migrate(engine)
    assert await snapshot(engine) == after


async def contract(conn):
    def read(sync):
        inspector = inspect(sync)
        return (
            {table: value for table, value in _contract(sync.exec_driver_sql).items()
             if table in ("calendar_connections", "calendar_links")},
            {table: inspector.get_check_constraints(table)
             for table in ("calendar_connections", "calendar_links")},
        )
    return await conn.run_sync(read)


@pytest.mark.anyio
async def test_v9_metadata_equivalence_includes_defaults_and_named_constraints(engine):
    await migrations.migrate(engine)
    async with engine.connect() as conn:
        expected = await contract(conn)
        columns = await conn.run_sync(lambda sync: inspect(sync).get_columns("calendar_connections"))
        column = next(column for column in columns if column["name"] == "credential_state")
        assert column["default"] == "'absent'"
        assert not column["nullable"]
    other = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with other.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            assert await contract(conn) == expected
    finally:
        await other.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("metadata", [False, True])
async def test_explicit_credential_states_and_database_default(engine, metadata):
    if metadata:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        await migrations.migrate(engine)
    assert CalendarConnection(server_url="server", calendar_url="calendar").credential_state == "absent"
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO calendar_connections "
            "(id,server_url,calendar_url,state,enabled,created_at,updated_at) VALUES "
            "('connection','server','calendar','disconnected',0,'2026-01-01','2026-01-01')"
        )
        assert (await conn.exec_driver_sql(
            "SELECT credential_state FROM calendar_connections"
        )).scalar_one() == "absent"
        for state in ("removal_pending", "present", "removal_pending", "absent"):
            await conn.exec_driver_sql(
                "UPDATE calendar_connections SET credential_state=?", (state,)
            )
            assert (await conn.exec_driver_sql(
                "SELECT credential_state FROM calendar_connections"
            )).scalar_one() == state
        for state in (None, "", "unknown", "PRESENT"):
            with pytest.raises(IntegrityError):
                await conn.exec_driver_sql(
                    "UPDATE calendar_connections SET credential_state=?", (state,)
                )
