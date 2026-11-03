"""v15 rollback, static schema parity, and inbound cache preservation."""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.recovery import _contract

TABLES = ("calendar_inbound_state", "calendar_inbound_events")


@pytest.mark.anyio
async def test_v15_atomic_rollback_retry_and_schema(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    real = migrations.MIGRATIONS
    try:
        async with engine.begin() as conn:
            for migration in real[:14]:
                await migration(conn)
            await conn.exec_driver_sql("PRAGMA user_version=14")

        async def fail(conn):
            await real[14](conn)
            raise RuntimeError("injected inbound failure")

        with monkeypatch.context() as patch:
            patch.setattr(migrations, "MIGRATIONS", (*real[:14], fail))
            with pytest.raises(migrations.MigrationError, match="database intact at version 14"):
                await migrations.migrate(engine)
        async with engine.connect() as conn:
            assert (await conn.exec_driver_sql("PRAGMA user_version")).scalar_one() == 14
            assert (await conn.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE name LIKE 'calendar_inbound%'"
            )).scalar_one() == 0
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


@pytest.mark.anyio
async def test_inbound_state_constraints():
    import sqlalchemy

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        await migrations.migrate(engine)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO calendar_connections (id, server_url, calendar_url, state, enabled, "
                "created_at, updated_at, credential_state) VALUES "
                "('c1', 'https://dav.test/', 'https://dav.test/cal/', 'connected', 1, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00', 'present')")
            with pytest.raises(sqlalchemy.exc.IntegrityError):
                # token capability requires a persisted token
                await conn.exec_driver_sql(
                    "INSERT INTO calendar_inbound_state (id, connection_id, capability, sync_token, "
                    "error_state) VALUES ('s1', 'c1', 'sync_token', NULL, 'none')")
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO calendar_inbound_state (id, connection_id, capability, sync_token, "
                "error_state) VALUES ('s1', 'c1', 'sync_token', 't1', 'none')")
            await conn.exec_driver_sql(
                "INSERT INTO calendar_inbound_events (id, connection_id, resource_url, etag, content, "
                "component_state, fetched_at) VALUES ('e1', 'c1', 'https://dav.test/cal/a.ics', '\"v1\"', "
                "'raw', 'unparsable', '2026-01-01 00:00:00')")
            with pytest.raises(sqlalchemy.exc.IntegrityError):
                # stored components require parsed fields
                await conn.exec_driver_sql(
                    "INSERT INTO calendar_inbound_events (id, connection_id, resource_url, etag, content, "
                    "component_state, fetched_at) VALUES ('e2', 'c1', 'https://dav.test/cal/b.ics', '\"v2\"', "
                    "'raw', 'stored', '2026-01-01 00:00:00')")
    finally:
        await engine.dispose()
