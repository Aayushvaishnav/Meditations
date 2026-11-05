from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app import migrations
from app.models import Task
from app.schemas import TaskResponse


def test_deadline_transitions(client):
    task = client.post('/api/tasks', json={'title': 'date', 'deadline': {'kind': 'date', 'date': '2026-11-02'}}).json()
    assert task['deadline'] == {'kind': 'date', 'date': '2026-11-02'}
    assert task['due_date'] is None
    path = '/api/tasks/' + task['id']
    task = client.patch(path, json={'deadline': {'kind': 'timed', 'at': '2026-11-02T09:00:00+05:30'}}).json()
    assert task['deadline'] == {'kind': 'timed', 'at': '2026-11-02T03:30:00'}
    assert task['deadline_date'] is None
    task = client.patch(path, json={'deadline': {'kind': 'none'}}).json()
    assert task['due_date'] is None and task['deadline_date'] is None
    task = client.patch(path, json={'due_date': '2026-01-01T09:00:00Z'}).json()
    assert task['deadline']['kind'] == 'timed'
    assert client.patch(path, json={'due_date': None}).json()['deadline'] == {'kind': 'none'}
    assert client.post('/api/tasks', json={'title': 'none'}).json()['deadline'] == {'kind': 'none'}


@pytest.mark.parametrize('payload', [
    {'deadline': None}, {'deadline_date': '2026-01-01'},
    {'deadline': {'kind': 'none', 'date': '2026-01-01'}},
    {'deadline': {'kind': 'date', 'date': '2026-02-30'}},
    {'deadline': {'kind': 'date', 'date': '2026-01-01T00:00:00'}},
    {'deadline': {'kind': 'timed', 'at': '2026-01-01'}},
    {'deadline': {'kind': 'none'}, 'due_date': None},
    {'deadline': {'kind': 'date', 'date': 0}},
])
def test_invalid_deadlines(client, payload):
    assert client.post('/api/tasks', json={'title': 'invalid', **payload}).status_code == 422
    task = client.post('/api/tasks', json={'title': 'existing'}).json()
    assert client.patch('/api/tasks/' + task['id'], json=payload).status_code == 422


def test_date_overdue_and_timed_filters(client):
    for label in ['2026-11-01', '2026-11-02', '2026-11-03']:
        client.post('/api/tasks', json={'title': label, 'deadline': {'kind': 'date', 'date': label}})
    assert [t['title'] for t in client.get('/api/tasks?overdue=true&as_of_date=2026-11-02').json()] == ['2026-11-01']
    assert client.get('/api/tasks?due_before=2030-01-01T00:00:00').json() == []


def test_date_recurrence_and_persistence(client):
    task = client.post('/api/tasks', json={'title': 'repeat', 'recurrence_rule': 'FREQ=DAILY', 'deadline': {'kind': 'date', 'date': '2026-11-02'}}).json()
    assert client.patch('/api/tasks/' + task['id'], json={'status': 'completed'}).status_code == 200
    successor = next(t for t in client.get('/api/tasks').json() if t['id'] != task['id'])
    assert successor['deadline'] == {'kind': 'date', 'date': '2026-11-03'}
    assert successor['recurrence_series_id'] == task['recurrence_series_id']
    assert successor['recurrence_occurrence'] == 1
    legacy = Task(title='legacy', due_date=datetime(2026, 1, 1, 9))
    assert TaskResponse.model_validate(legacy).deadline.kind == 'timed'
    assert 'deadline' not in legacy.model_dump()


@pytest.mark.anyio
async def test_v5_exact_preservation_rollback_retry(monkeypatch):
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    real = migrations.MIGRATIONS
    try:
        monkeypatch.setattr(migrations, 'MIGRATIONS', real[:4])
        monkeypatch.setattr(migrations, 'LATEST_VERSION', 4)
        await migrations.migrate(engine)
        async with engine.begin() as conn:
            await conn.exec_driver_sql("INSERT INTO tasks (id,title,priority,status,due_date,actual_minutes,tags,order_index,created_at,updated_at) VALUES ('a','legacy',0,'todo','2026-01-01 09:00:00',0,'[]',0,'2026-01-01','2026-01-01')")
            before = (await conn.exec_driver_sql('SELECT * FROM tasks')).all()
        async def fail(conn):
            await real[4](conn)
            raise ValueError('injected')
        monkeypatch.setattr(migrations, 'MIGRATIONS', (*real[:4], fail))
        monkeypatch.setattr(migrations, 'LATEST_VERSION', 5)
        with pytest.raises(migrations.MigrationError):
            await migrations.migrate(engine)
        async with engine.connect() as conn:
            assert (await conn.exec_driver_sql('PRAGMA user_version')).scalar_one() == 4
            assert (await conn.exec_driver_sql('SELECT * FROM tasks')).all() == before
        monkeypatch.setattr(migrations, 'MIGRATIONS', real)
        await migrations.migrate(engine)
        async with engine.connect() as conn:
            after = (await conn.exec_driver_sql('SELECT * FROM tasks')).one()
            assert tuple(after[:-1]) == tuple(before[0])
            assert after[-1] is None
        await migrations.migrate(engine)
    finally:
        await engine.dispose()


def test_calendar_telemetry(client):
    from app import db
    from app.telemetry import collect_daily_metrics

    async def metrics():
        async with db.get_sessionmaker()() as session:
            session.add_all([
                Task(title=label, deadline_date=date.fromisoformat(label), created_at=datetime(2026, 11, 1))
                for label in ['2026-11-01', '2026-11-02', '2026-11-03']
            ])
            session.add(Task(title='undated', created_at=datetime(2026, 11, 1)))
            await session.commit()
            return await collect_daily_metrics(session, date(2026, 11, 2))

    assert client.portal.call(metrics).tasks_planned == 2


def test_capture_deadline_kinds(client, monkeypatch):
    from app import agents

    async def fake(*args, **kwargs):
        return agents.CaptureOutput(tasks=[
            agents.CapturedTask(title='calendar', due_date='2026-11-02'),
            agents.CapturedTask(title='clock', due_date='2026-11-02', due_time='09:00'),
            agents.CapturedTask(title='undated'),
        ], journal_snippet='')

    monkeypatch.setattr(agents, 'run_capture', fake)
    response = client.post('/api/agents/capture', json={'text': 'capture these'})
    assert response.status_code == 200
    tasks = response.json()['tasks']
    assert [t['deadline']['kind'] for t in tasks] == ['date', 'timed', 'none']
    assert tasks[0]['deadline'] == {'kind': 'date', 'date': '2026-11-02'}
    assert tasks[0]['due_date'] is None


@pytest.mark.parametrize('alias', ['2027-01-01T12:00:00Z', None])
def test_legacy_alias_clears_calendar_deadline(client, alias):
    task = client.post('/api/tasks', json={'title': 'calendar', 'deadline': {'kind': 'date', 'date': '2026-12-31'}}).json()
    updated = client.patch('/api/tasks/' + task['id'], json={'due_date': alias}).json()
    assert updated['deadline_date'] is None
    assert updated['deadline']['kind'] == ('timed' if alias else 'none')


@pytest.mark.parametrize('deadline', [
    {'kind': 'date', 'date': '2026-12-31'},
    {'kind': 'timed', 'at': '2026-12-31T23:00:00'},
])
def test_unrelated_patch_preserves_deadline(client, deadline):
    task = client.post('/api/tasks', json={'title': 'before', 'deadline': deadline}).json()
    updated = client.patch('/api/tasks/' + task['id'], json={'title': 'after', 'priority': 3}).json()
    for key in ['deadline', 'due_date', 'deadline_date']:
        assert updated[key] == task[key]


@pytest.mark.anyio
@pytest.mark.parametrize('schema', ['migration', 'model'])
async def test_storage_deadline_constraint(schema):
    from sqlalchemy import CheckConstraint
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import SQLModel

    constraint = next(c for c in Task.__table__.constraints if isinstance(c, CheckConstraint) and c.name == 'ck_task_deadline_exclusive')
    assert constraint.name == 'ck_task_deadline_exclusive'
    assert str(constraint.sqltext) == 'due_date IS NULL OR deadline_date IS NULL'
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        if schema == 'migration':
            await migrations.migrate(engine)
        else:
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
        async with engine.begin() as conn:
            ddl = (await conn.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='tasks'")).scalar_one()
            assert 'ck_task_deadline_exclusive' in ddl
            for i, (due, calendar) in enumerate([(None, None), ('2026-01-01 09:00:00', None), (None, '2026-01-01')]):
                await conn.exec_driver_sql("INSERT INTO tasks (id,title,priority,status,due_date,deadline_date,actual_minutes,tags,order_index,created_at,updated_at) VALUES (?, 'valid', 0, 'todo', ?, ?, 0, '[]', 0, '2026-01-01', '2026-01-01')", (str(i), due, calendar))
            with pytest.raises(IntegrityError, match='ck_task_deadline_exclusive'):
                await conn.exec_driver_sql("UPDATE tasks SET due_date='2026-01-01 09:00:00', deadline_date='2026-01-01'")
    finally:
        await engine.dispose()


def test_capture_time_without_date_rejected(client, monkeypatch):
    from app import agents

    async def fake(*args, **kwargs):
        return agents.CaptureOutput(tasks=[agents.CapturedTask(title='invalid', due_time='09:00')], journal_snippet='')

    monkeypatch.setattr(agents, 'run_capture', fake)
    assert client.post('/api/agents/capture', json={'text': 'capture'}).status_code == 502
    assert client.get('/api/tasks').json() == []


def test_date_weekly_recurrence_crosses_year(client):
    task = client.post('/api/tasks', json={'title': 'weekly', 'recurrence_rule': 'FREQ=WEEKLY;BYDAY=TH', 'deadline': {'kind': 'date', 'date': '2026-12-31'}}).json()
    assert client.patch('/api/tasks/' + task['id'], json={'status': 'completed'}).status_code == 200
    successor = next(t for t in client.get('/api/tasks').json() if t['id'] != task['id'])
    assert successor['deadline'] == {'kind': 'date', 'date': '2027-01-07'}
    assert successor['due_date'] is None


def test_date_export_and_offline_backup_restore(client, tmp_path):
    import asyncio
    import io
    import json
    import sqlite3
    import zipfile
    from app.recovery import restore_database

    task = client.post('/api/tasks', json={'title': 'calendar', 'deadline': {'kind': 'date', 'date': '2026-12-31'}}).json()
    exported = client.post('/api/export')
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        row = next(t for t in json.loads(archive.read('data.json'))['tasks'] if t['id'] == task['id'])
    assert row['deadline_date'] == '2026-12-31' and row['due_date'] is None
    response = client.post('/api/backup')
    assert response.status_code == 200
    backup, target = tmp_path / 'backup.db', tmp_path / 'restored.db'
    backup.write_bytes(response.content)
    asyncio.run(restore_database(backup, target))
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT due_date,deadline_date FROM tasks WHERE id=?', (task['id'],)).fetchone() == (None, '2026-12-31')


def test_briefing_calendar_dates_and_statuses(client, monkeypatch):
    from app import agents
    from app.routers import agents as router

    monkeypatch.setattr(router, 'utc_now', lambda: datetime(2026, 11, 2, 12))
    for title, label, status in [
        ('overdue', '2026-11-01', 'todo'), ('today', '2026-11-02', 'in_progress'),
        ('future', '2026-11-03', 'todo'), ('completed', '2026-11-01', 'completed'),
        ('canceled', '2026-11-02', 'canceled'),
    ]:
        client.post('/api/tasks', json={'title': title, 'status': status, 'deadline': {'kind': 'date', 'date': label}})

    async def fake(deps, **kwargs):
        assert deps['overdue_tasks'] == ['overdue (due 2026-11-01)']
        assert deps['due_today'] == ['today']
        assert deps['open_tasks_total'] == 3
        return agents.BriefingOutput(top_focus=['today'], reasoning='calendar')

    monkeypatch.setattr(agents, 'run_briefing', fake)
    assert client.post('/api/agents/briefing').status_code == 200


def test_calendar_completed_canceled_telemetry(client):
    from app import db
    from app.telemetry import collect_daily_metrics

    async def seed_and_measure():
        async with db.get_sessionmaker()() as session:
            session.add_all([
                Task(title='completed today', created_at=datetime(2026, 11, 1), deadline_date=date(2026, 11, 1), status='completed', completed_at=datetime(2026, 11, 2, 9)),
                Task(title='completed yesterday', created_at=datetime(2026, 11, 1), deadline_date=date(2026, 11, 1), status='completed', completed_at=datetime(2026, 11, 1, 9)),
                Task(title='canceled', created_at=datetime(2026, 11, 1), deadline_date=date(2026, 11, 1), status='canceled'),
                Task(title='open', created_at=datetime(2026, 11, 1), deadline_date=date(2026, 11, 2)),
            ])
            await session.commit()
            return await collect_daily_metrics(session, date(2026, 11, 2))

    metrics = client.portal.call(seed_and_measure)
    assert metrics.tasks_planned == 2
    assert metrics.tasks_completed == 1
