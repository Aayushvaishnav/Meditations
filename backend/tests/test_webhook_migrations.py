"""v14 rollback, static schema parity and offline recovery preservation."""

import asyncio
import sqlite3
from contextlib import closing

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.recovery import _contract, checkpoint_database, restore_database

TABLES = ("webhook_endpoints", "webhook_versions", "webhook_deliveries")


@pytest.mark.anyio
async def test_v14_atomic_rollback_retry_and_schema(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    real = migrations.MIGRATIONS
    try:
        async with engine.begin() as conn:
            for migration in real[:13]:
                await migration(conn)
            await conn.exec_driver_sql("PRAGMA user_version=13")

        async def fail(conn):
            await real[13](conn)
            raise RuntimeError("injected webhook failure")

        with monkeypatch.context() as patch:
            patch.setattr(migrations, "MIGRATIONS", (*real[:13], fail))
            with pytest.raises(
                migrations.MigrationError, match="database intact at version 13"
            ):
                await migrations.migrate(engine)
        async with engine.connect() as conn:
            assert (
                await conn.exec_driver_sql("PRAGMA user_version")
            ).scalar_one() == 13
            assert (
                await conn.exec_driver_sql(
                    "SELECT count(*) FROM sqlite_master WHERE name LIKE 'webhook_%'"
                )
            ).scalar_one() == 0
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


def test_webhook_recovery_preserves_outbox_without_credentials(tmp_path):
    source = tmp_path / "source.db"

    async def seed():
        engine = create_async_engine("sqlite+aiosqlite:///" + str(source))
        try:
            await migrations.migrate(engine)
            async with engine.begin() as conn:
                await conn.exec_driver_sql(
                    "INSERT INTO webhook_endpoints VALUES ('endpoint','Workflow','http://localhost/hook',1,'[]','{}',0)"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO webhook_versions VALUES ('time_block:gone',3)"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO webhook_deliveries VALUES ('delivery','endpoint','event','time_block.deleted','gone',3,'{}','pending',2,'Unavailable','2026-11-01','2026-11-01')"
                )
        finally:
            await engine.dispose()

    asyncio.run(seed())
    snapshot = checkpoint_database(source, "webhook-test")
    destination = tmp_path / "restored.db"
    asyncio.run(restore_database(snapshot, destination))
    with (
        closing(sqlite3.connect(source)) as before,
        closing(sqlite3.connect(destination)) as after,
    ):
        for table in TABLES:
            assert (
                before.execute(f"SELECT * FROM {table}").fetchall()
                == after.execute(f"SELECT * FROM {table}").fetchall()
            )
        assert after.execute("PRAGMA foreign_key_check").fetchall() == []
        assert after.execute("PRAGMA user_version").fetchone() == (
            migrations.LATEST_VERSION,
        )
