from datetime import date

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app import migrations
from app.models import CalendarConnection, CalendarLink, TimeBlock


@pytest.fixture
async def engine():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    yield engine
    await engine.dispose()


async def seed(engine):
    async with AsyncSession(engine) as session:
        await session.execute(text(
            "INSERT INTO tasks (id,title,priority,status,actual_minutes,tags,order_index,created_at,updated_at) "
            "VALUES ('t','Title',0,'todo',0,'[]',0,'2026-01-01','2026-01-01'), "
            "('other','Other',0,'todo',0,'[]',0,'2026-01-01','2026-01-01')"
        ))
        session.add(CalendarConnection(id='c', server_url='https://example.test',
                                       calendar_url='https://example.test/cal/'))
        await session.flush()
        for i in range(3):
            session.add(TimeBlock(id=f'b{i}', task_id='t', kind='all_day', timezone=None,
                                  start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)))
        await session.flush()
        for i in range(2):
            await session.execute(text("INSERT INTO calendar_links "
                "(id,connection_id,block_id,local_block_id,uid,resource_url,state,local_revision,"
                "acknowledged_revision,desired_action,payload_state,payload,error_state,created_at,updated_at) "
                "VALUES (:id,'c',:block,:block,:uid,:url,'synced',1,0,'upsert','prepared',"
                "'cached','none','2026-01-01','2026-01-01')"),
                dict(id=f'l{i}', block=f'b{i}', uid=f'u{i}', url=f'{i}.ics'))
        await session.commit()
    async with engine.begin() as conn:
        await conn.exec_driver_sql("INSERT INTO calendar_dispatches VALUES "
                                   "('l0',1,'upsert','0.ics','u0',NULL,'immutable',1)")


async def rows(conn):
    return (await conn.exec_driver_sql('SELECT * FROM calendar_links ORDER BY id')).mappings().all()


@pytest.mark.anyio
@pytest.mark.parametrize('assignment', [
    "start_date='2025-12-31'", "end_date='2026-01-03'", "task_id='other'",
    "kind='timed',timezone='UTC',start_date=NULL,end_date=NULL,"
    "start_at='2026-01-01 09:00',end_at='2026-01-01 10:00'",
])
async def test_block_capture_and_rollback(engine, assignment):
    await migrations.migrate(engine)
    await seed(engine)
    async with engine.connect() as conn:
        before = await rows(conn)
        await conn.exec_driver_sql(f"UPDATE time_blocks SET {assignment} WHERE id='b0'")
        captured = await rows(conn)
        assert captured[0]['local_revision'] == 2
        assert captured[0]['state'] == 'pending'
        assert captured[0]['payload'] is None
        assert captured[1] == before[1]
        assert (await conn.exec_driver_sql('SELECT payload FROM calendar_dispatches')).scalar_one() == 'immutable'
        await conn.rollback()
        assert await rows(conn) == before


@pytest.mark.anyio
@pytest.mark.parametrize('state', ['synced', 'error', 'conflict', 'syncing', 'detached'])
async def test_task_capture_noops_states_and_delete(engine, state):
    await migrations.migrate(engine)
    await seed(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f"UPDATE calendar_links SET state='{state}',error_state='present',last_error='old'")
        before = await rows(conn)
        for statement in ["UPDATE tasks SET title=title,status='completed' WHERE id='t'",
                          "UPDATE tasks SET priority=2 WHERE id='t'",
                          "UPDATE time_blocks SET start_date=start_date,updated_at='2026-02-01'"]:
            await conn.exec_driver_sql(statement)
            assert await rows(conn) == before
        await conn.exec_driver_sql("UPDATE tasks SET title='Renamed',status='canceled' WHERE id='t'")
        for row in await rows(conn):
            assert row['local_revision'] == (1 if state == 'detached' else 2)
            assert row['state'] == (state if state in ('conflict', 'syncing', 'detached') else 'pending')
            assert row['last_error'] == ('old' if state in ('conflict', 'syncing', 'detached') else None)
        await conn.exec_driver_sql("UPDATE tasks SET status='todo' WHERE id='t'")
        assert all(r['local_revision'] == (1 if state == 'detached' else 3) for r in await rows(conn))
        await conn.exec_driver_sql("UPDATE calendar_links SET desired_action='delete' WHERE id='l1'")
        await conn.exec_driver_sql("DELETE FROM tasks WHERE id='t'")
        result = await rows(conn)
        assert all(r['block_id'] is None for r in result)
        assert result[0]['local_revision'] == (1 if state == 'detached' else 4)
        assert result[0]['desired_action'] == ('upsert' if state == 'detached' else 'delete')
        assert result[1]['local_revision'] == (1 if state == 'detached' else 3)
        assert (await conn.exec_driver_sql('SELECT payload FROM calendar_dispatches')).scalar_one() == 'immutable'
        assert len(result) == 2
        assert not (await conn.exec_driver_sql('PRAGMA foreign_key_check')).all()


@pytest.mark.anyio
async def test_v11_backfill_atomic_failure_retry(engine, monkeypatch):
    real = migrations.MIGRATIONS
    async with engine.begin() as conn:
        for migration in real[:10]:
            await migration(conn)
        await conn.exec_driver_sql('PRAGMA user_version=10')
    await seed(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql('DELETE FROM time_blocks')
        before = await rows(conn)

    async def fail(conn):
        await real[10](conn)
        raise RuntimeError('injected queue failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', (*real[:10], fail))
        with pytest.raises(migrations.MigrationError, match='v11 failed; database intact at version 10'):
            await migrations.migrate(engine)
    async with engine.connect() as conn:
        assert await rows(conn) == before
        assert (await conn.exec_driver_sql('PRAGMA user_version')).scalar_one() == 10
        assert not (await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")).all()
    await migrations.migrate(engine)
    await migrations.migrate(engine)
    async with engine.connect() as conn:
        assert all(r['desired_action'] == 'delete' and r['local_revision'] == 2 for r in await rows(conn))
        assert (await conn.exec_driver_sql('SELECT payload FROM calendar_dispatches')).scalar_one() == 'immutable'


@pytest.mark.anyio
@pytest.mark.parametrize('enabled,state', [(0, 'disconnected'), (0, 'connected'), (1, 'connected')])
async def test_timed_fields_capture_independently_and_direct_delete(engine, enabled, state):
    await migrations.migrate(engine)
    await seed(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            f"UPDATE calendar_connections SET enabled={enabled},state='{state}'")
        await conn.exec_driver_sql(
            "UPDATE time_blocks SET kind='timed',timezone='UTC',start_date=NULL,end_date=NULL,"
            "start_at='2026-01-01 09:00',end_at='2026-01-01 10:00' WHERE id='b0'")
        for revision, assignment in enumerate([
            "timezone='Asia/Kolkata'", "start_at='2026-01-01 08:00'",
            "end_at='2026-01-01 11:00'",
        ], start=3):
            await conn.exec_driver_sql(f"UPDATE time_blocks SET {assignment} WHERE id='b0'")
            assert (await rows(conn))[0]['local_revision'] == revision
            await conn.exec_driver_sql(f"UPDATE time_blocks SET {assignment} WHERE id='b0'")
            assert (await rows(conn))[0]['local_revision'] == revision
        before = (await conn.exec_driver_sql('SELECT * FROM calendar_dispatches')).all()
        await conn.exec_driver_sql("DELETE FROM time_blocks WHERE id='b0'")
        link = (await rows(conn))[0]
        assert (link['local_revision'], link['desired_action'], link['block_id']) == (6, 'delete', None)
        assert (link['local_block_id'], link['uid'], link['resource_url']) == ('b0', 'u0', '0.ics')
        assert (await conn.exec_driver_sql('SELECT * FROM calendar_dispatches')).all() == before
