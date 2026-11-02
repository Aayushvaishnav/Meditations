from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app import migrations
from app.migrations.baseline import STATEMENTS


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    yield engine
    await engine.dispose()


async def baseline(engine):
    async with engine.begin() as conn:
        for statement in STATEMENTS:
            await conn.exec_driver_sql(statement)
        await conn.exec_driver_sql(
            "INSERT INTO lists VALUES ('list', 'Personal', '#64748b', NULL, 0, '2026-01-01')"
        )
        for task_id, rule, status in [
            ('one', 'FREQ=DAILY', 'todo'),
            ('two', 'FREQ=DAILY', 'completed'),
            ('empty', '', 'todo'),
            ('none', None, 'todo'),
        ]:
            await conn.exec_driver_sql(
                "INSERT INTO tasks (id, list_id, title, priority, status, actual_minutes, "
                "recurrence_rule, tags, order_index, created_at, updated_at) "
                "VALUES (?, 'list', 'Same title', 0, ?, 0, ?, '[]', 0, '2026-01-01', '2026-01-01')",
                (task_id, status, rule),
            )
        await conn.exec_driver_sql(
            "INSERT INTO focus_sessions VALUES ('focus', 'one', 25, 'pomodoro', NULL, '2026-01-01')"
        )


async def schema(engine):
    async with engine.connect() as conn:
        return (await conn.exec_driver_sql(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        )).all()


async def version(engine):
    async with engine.connect() as conn:
        return (await conn.exec_driver_sql('PRAGMA user_version')).scalar_one()


@pytest.mark.anyio
async def test_fresh_and_legacy_equivalent_with_independent_backfill(engine):
    await baseline(engine)
    async with engine.connect() as conn:
        original = (await conn.exec_driver_sql('SELECT * FROM tasks ORDER BY id')).all()
    await migrations.migrate(engine)
    assert await version(engine) == migrations.LATEST_VERSION
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql('SELECT * FROM tasks ORDER BY id')).all()
        assert [tuple(row[:-3]) for row in rows] == [tuple(row) for row in original]
        assert {row[0]: tuple(row[-3:-1]) for row in rows} == {
            'one': ('one', 0), 'two': ('two', 0), 'empty': (None, None), 'none': (None, None),
        }
        assert (await conn.exec_driver_sql('SELECT name FROM lists')).scalar_one() == 'Personal'
        assert (await conn.exec_driver_sql('SELECT task_id, duration_minutes FROM focus_sessions')).one() == ('one', 25)
    fresh = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    try:
        await migrations.migrate(fresh)
        assert await schema(fresh) == await schema(engine)
    finally:
        await fresh.dispose()
    before = await schema(engine)
    await migrations.migrate(engine)
    assert await schema(engine) == before


@pytest.mark.anyio
@pytest.mark.parametrize('starting_version', [0, 1])
async def test_failed_v2_rolls_back_ddl_ledger_and_data_then_retries(engine, monkeypatch, starting_version):
    await baseline(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'PRAGMA user_version = {starting_version}')

    before = await schema(engine)
    real = migrations.MIGRATIONS

    async def fail(conn):
        await real[1](conn)
        raise ValueError('injected failure')

    monkeypatch.setattr(migrations, 'MIGRATIONS', (real[0], fail, *real[2:]))
    with pytest.raises(migrations.MigrationError, match=rf'v2 failed; database intact at version {starting_version}'):
        await migrations.migrate(engine)
    assert await version(engine) == starting_version
    assert await schema(engine) == before
    async with engine.connect() as conn:
        assert (await conn.exec_driver_sql('SELECT count(*) FROM tasks')).scalar_one() == 4
    monkeypatch.setattr(migrations, 'MIGRATIONS', real)
    await migrations.migrate(engine)
    assert await version(engine) == migrations.LATEST_VERSION


@pytest.mark.anyio
async def test_newer_version_is_refused_without_changes(engine):
    await baseline(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql('PRAGMA user_version = 99')
    before = await schema(engine)
    with pytest.raises(migrations.MigrationError, match='99.*newer.*upgrade Journal'):
        await migrations.migrate(engine)
    assert await version(engine) == 99
    assert await schema(engine) == before


@pytest.mark.anyio
async def test_unique_occurrence_allows_unassigned_tasks(engine):
    await baseline(engine)
    await migrations.migrate(engine)
    async with engine.connect() as conn:
        with pytest.raises(IntegrityError, match='UNIQUE constraint failed'):
            await conn.exec_driver_sql(
                "UPDATE tasks SET recurrence_series_id='one', recurrence_occurrence=0 WHERE id='two'"
            )
        await conn.rollback()


@pytest.mark.anyio
async def test_init_db_migrates_before_search_and_repeats(engine, monkeypatch):
    from app import db, search

    calls = []

    async def init_search(conn):
        assert (await conn.exec_driver_sql('PRAGMA user_version')).scalar_one() == migrations.LATEST_VERSION
        await conn.exec_driver_sql('SELECT recurrence_series_id FROM tasks')
        calls.append(True)

    monkeypatch.setattr(db, '_engine', engine)
    monkeypatch.setattr(search, 'init_search', init_search)
    await db.init_db()
    await db.init_db()
    assert len(calls) == 2


@pytest.mark.anyio
async def test_migrated_schema_matches_current_model_contract(engine):
    from sqlalchemy import inspect
    from sqlmodel import SQLModel

    from app import models  # noqa: F401; register all model tables

    def contract(conn):
        inspector = inspect(conn)
        return {
            table: {
                "columns": {
                    column["name"]: (str(column["type"]), column["nullable"], column["primary_key"])
                    for column in inspector.get_columns(table)
                },
                "indexes": sorted(
                    (index["name"], tuple(index["column_names"]), index["unique"])
                    for index in inspector.get_indexes(table)
                ),
                "foreign_keys": sorted(
                    (tuple(fk["constrained_columns"]), fk["referred_table"],
                     tuple(fk["referred_columns"]), fk["options"].get("ondelete"))
                    for fk in inspector.get_foreign_keys(table)
                ),
                "unique_constraints": sorted(
                    tuple(constraint["column_names"])
                    for constraint in inspector.get_unique_constraints(table)
                ),
            }
            for table in inspector.get_table_names()
        }

    await migrations.migrate(engine)
    reference = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with reference.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            expected = await conn.run_sync(contract)
        async with engine.connect() as conn:
            assert await conn.run_sync(contract) == expected
    finally:
        await reference.dispose()


@pytest.mark.anyio
async def test_failed_vector_state_upgrade_preserves_v2_then_retries(engine, monkeypatch):
    async with engine.begin() as conn:
        for migration in migrations.MIGRATIONS[:2]:
            await migration(conn)
        await conn.exec_driver_sql('PRAGMA user_version = 2')
        await conn.exec_driver_sql(
            "INSERT INTO journal_entries (date, raw_markdown, hours_deep_work, tasks_planned, tasks_done, created_at, updated_at) "
            "VALUES ('2026-09-07', 'preserved', 0, 0, 0, '2026-09-07', '2026-09-07')"
        )
    before = await schema(engine)
    real = migrations.MIGRATIONS

    async def fail(conn):
        await real[2](conn)
        raise ValueError('injected vector state failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', (*real[:2], fail))
        with pytest.raises(migrations.MigrationError, match='v3 failed; database intact at version 2'):
            await migrations.migrate(engine)
    assert await version(engine) == 2
    assert await schema(engine) == before
    await migrations.migrate(engine)
    assert await version(engine) == migrations.LATEST_VERSION
    async with engine.connect() as conn:
        assert (await conn.exec_driver_sql('SELECT raw_markdown FROM journal_entries')).scalar_one() == 'preserved'
        assert (await conn.exec_driver_sql('SELECT count(*) FROM search_vector_state')).scalar_one() == 0


@pytest.mark.anyio
async def test_failed_review_jobs_upgrade_preserves_v3_then_retries(engine, monkeypatch):
    async with engine.begin() as conn:
        for migration in migrations.MIGRATIONS[:3]:
            await migration(conn)
        await conn.exec_driver_sql('PRAGMA user_version = 3')
    before = await schema(engine)
    real = migrations.MIGRATIONS

    async def fail(conn):
        await real[3](conn)
        raise ValueError('injected review jobs failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', (*real[:3], fail))
        with pytest.raises(migrations.MigrationError, match='v4 failed; database intact at version 3'):
            await migrations.migrate(engine)
    assert await version(engine) == 3
    assert await schema(engine) == before
    await migrations.migrate(engine)
    assert await version(engine) == migrations.LATEST_VERSION
    async with engine.connect() as conn:
        assert (await conn.exec_driver_sql('SELECT count(*) FROM review_jobs')).scalar_one() == 0


@pytest.mark.anyio
async def test_failed_time_blocks_upgrade_preserves_v5_then_retries(engine, monkeypatch):
    await baseline(engine)
    async with engine.begin() as conn:
        for migration in migrations.MIGRATIONS[1:5]:
            await migration(conn)
        await conn.exec_driver_sql('PRAGMA user_version = 5')
        await conn.exec_driver_sql("UPDATE tasks SET deadline_date='2026-11-02' WHERE id='one'")
        tasks = (await conn.exec_driver_sql('SELECT * FROM tasks ORDER BY id')).all()
        focus = (await conn.exec_driver_sql('SELECT * FROM focus_sessions')).all()
    before = await schema(engine)
    real = migrations.MIGRATIONS

    async def fail(conn):
        await real[5](conn)
        raise ValueError('injected time blocks failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', (*real[:5], fail))
        with pytest.raises(migrations.MigrationError, match='v6 failed; database intact at version 5'):
            await migrations.migrate(engine)
    assert await version(engine) == 5
    assert await schema(engine) == before
    for retry in (False, True):
        if retry:
            await migrations.migrate(engine)
            assert await version(engine) == migrations.LATEST_VERSION
        async with engine.connect() as conn:
            assert (await conn.exec_driver_sql('SELECT * FROM tasks ORDER BY id')).all() == tasks
            assert (await conn.exec_driver_sql('SELECT * FROM focus_sessions')).all() == focus
    async with engine.connect() as conn:
        assert (await conn.exec_driver_sql('SELECT count(*) FROM time_blocks')).scalar_one() == 0


@pytest.mark.anyio
async def test_time_blocks_database_constraints_and_task_cascade(engine):
    await baseline(engine)
    await migrations.migrate(engine)
    async with engine.connect() as conn:
        await conn.exec_driver_sql('PRAGMA foreign_keys=ON')
        assert (await conn.exec_driver_sql('PRAGMA foreign_keys')).scalar_one() == 1
        await conn.commit()
    insert = (
        'INSERT INTO time_blocks (id, task_id, start_at, end_at, kind, timezone, created_at, updated_at) '
        "VALUES (?, ?, ?, ?, 'timed', 'UTC', '2026-11-02', '2026-11-02')"
    )
    for block_id, task_id, start, end, error in [
        ('equal', 'one', '2026-11-02 10:00', '2026-11-02 10:00', 'CHECK'),
        ('reverse', 'one', '2026-11-02 11:00', '2026-11-02 10:00', 'CHECK'),
        ('orphan', 'missing', '2026-11-02 10:00', '2026-11-02 11:00', 'FOREIGN KEY'),
        ('unassigned', None, '2026-11-02 10:00', '2026-11-02 11:00', 'NOT NULL'),
    ]:
        with pytest.raises(IntegrityError, match=error):
            async with engine.begin() as conn:
                await conn.exec_driver_sql(insert, (block_id, task_id, start, end))
    async with engine.begin() as conn:
        for block_id, task_id in [('first', 'one'), ('overlap', 'one'), ('other', 'two')]:
            await conn.exec_driver_sql(
                insert, (block_id, task_id, '2026-11-02 10:00', '2026-11-02 11:00')
            )
        await conn.exec_driver_sql("DELETE FROM tasks WHERE id='one'")
        assert (await conn.exec_driver_sql('SELECT id, task_id FROM time_blocks')).all() == [('other', 'two')]
        assert (await conn.exec_driver_sql('PRAGMA foreign_key_check')).all() == []
