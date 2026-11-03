from __future__ import annotations

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app import migrations
from app.models import TimeBlock  # noqa: F401


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    yield engine
    await engine.dispose()


async def seed_v6(engine):
    async with engine.begin() as conn:
        for migration in migrations.MIGRATIONS[:6]:
            await migration(conn)
        await conn.exec_driver_sql("PRAGMA user_version=6")
        await conn.exec_driver_sql(
            "INSERT INTO tasks (id,title,priority,status,actual_minutes,tags,order_index,created_at,updated_at) "
            "VALUES ('task','Task',0,'todo',0,'[]',0,'2026-01-01','2026-01-01')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO time_blocks VALUES "
            "('block','task','2026-01-01 01:02:03.000004','2026-01-01 02:03:04.000005',"
            "'2025-12-31 23:00:00.123456','2026-01-01 00:00:00.654321')"
        )


async def snapshot(engine):
    async with engine.connect() as conn:
        return (
            (await conn.exec_driver_sql("PRAGMA user_version")).scalar_one(),
            (await conn.exec_driver_sql("SELECT * FROM time_blocks")).all(),
            (await conn.exec_driver_sql(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
            )).all(),
        )


@pytest.mark.anyio
async def test_v7_preserves_bytes_and_rolls_back_then_retries(engine, monkeypatch):
    await seed_v6(engine)
    before = await snapshot(engine)
    real = migrations.MIGRATIONS

    async def fail(conn):
        await real[6](conn)
        raise RuntimeError("injected after rebuild")

    monkeypatch.setattr(migrations, "MIGRATIONS", (*real[:6], fail))
    with pytest.raises(migrations.MigrationError, match="injected after rebuild"):
        await migrations.migrate(engine)
    assert await snapshot(engine) == before
    monkeypatch.setattr(migrations, "MIGRATIONS", real)
    await migrations.migrate(engine)
    version, rows, _ = await snapshot(engine)
    assert version == migrations.LATEST_VERSION
    row = rows[0]
    assert (row[0], row[1], row[4], row[5], row[8], row[9]) == tuple(before[1][0])
    assert (row[2], row[3], row[6], row[7]) == ("timed", "UTC", None, None)


async def shape_schema(conn):
    def read(sync):
        inspector = inspect(sync)
        return (
            [(c['name'], str(c['type']), c['nullable'], c['default'])
             for c in inspector.get_columns('time_blocks')],
            inspector.get_check_constraints('time_blocks'),
            sorted((i['name'], tuple(i['column_names'])) for i in inspector.get_indexes('time_blocks')),
            inspector.get_foreign_keys('time_blocks'),
        )
    return await conn.run_sync(read)


@pytest.mark.anyio
async def test_fresh_model_schema_matches_migration(engine):
    await migrations.migrate(engine)
    async with engine.connect() as conn:
        migrated = await shape_schema(conn)
    other = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with other.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            assert await shape_schema(conn) == migrated
    finally:
        await other.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize('model_schema', [False, True])
async def test_shapes_and_cascade(engine, model_schema):
    if model_schema:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        await migrations.migrate(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO tasks (id,title,priority,status,actual_minutes,tags,order_index,created_at,updated_at) "
            "VALUES ('task','Task',0,'todo',0,'[]',0,'2026-01-01','2026-01-01')"
        )
        timed = ('timed', 'UTC', '2026-01-01 01:00:00', '2026-01-01 02:00:00', None, None)
        all_day = ('all_day', None, None, None, '2026-01-01', '2026-01-02')
        insert = (
            "INSERT INTO time_blocks "
            "(id,task_id,kind,timezone,start_at,end_at,start_date,end_date,created_at,updated_at) "
            "VALUES (?,'task',?,?,?,?,?,?,'2026-01-01','2026-01-01')"
        )
        invalid = []
        for valid in (timed, all_day):
            for index, value in enumerate(valid):
                if value is not None:
                    variant = list(valid)
                    variant[index] = None
                    invalid.append(variant)
        invalid.extend([
            ('other', *timed[1:]),
            ('timed', 'UTC', timed[2], timed[2], None, None),
            ('timed', 'UTC', timed[3], timed[2], None, None),
            ('all_day', None, None, None, all_day[4], all_day[4]),
            ('all_day', None, None, None, all_day[5], all_day[4]),
            ('timed', 'UTC', timed[2], timed[3], all_day[4], all_day[5]),
            ('all_day', 'UTC', None, None, all_day[4], all_day[5]),
            ('all_day', None, timed[2], None, all_day[4], all_day[5]),
        ])
        for values in invalid:
            with pytest.raises(IntegrityError):
                await conn.exec_driver_sql(insert, ('invalid', *values))
        for index, values in enumerate((timed, all_day)):
            await conn.exec_driver_sql(insert, (str(index), *values))
        assert (await conn.exec_driver_sql("SELECT count(*) FROM time_blocks")).scalar_one() == 2
        await conn.exec_driver_sql("DELETE FROM tasks WHERE id='task'")
        assert (await conn.exec_driver_sql("SELECT count(*) FROM time_blocks")).scalar_one() == 0
