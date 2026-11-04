"""Explicit task classifications across API, storage, recurrence and portability."""

import asyncio
import io
import json
import sqlite3
import zipfile

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from app import migrations
from app.models import Task
from app.recovery import restore_database
from app.schemas import TaskResponse


@pytest.mark.parametrize('field,valid', [('importance', 'important'), ('urgency', 'urgent')])
@pytest.mark.parametrize('invalid', [None, '', 'high', True, 1, [], {}])
def test_invalid_classification(client, field, valid, invalid):
    assert client.post('/api/tasks', json={'title': 'invalid', field: invalid}).status_code == 422
    task = client.post('/api/tasks', json={'title': 'valid', field: valid}).json()
    assert client.patch('/api/tasks/' + task['id'], json={field: invalid}).status_code == 422
    assert client.get('/api/tasks/' + task['id']).json()[field] == valid
    with pytest.raises(ValidationError):
        TaskResponse.model_validate({**task, field: invalid})


def test_independent_partial_edits_and_defaults(client):
    task = client.post('/api/tasks', json={
        'title': 'not inferred', 'priority': 3, 'due_date': '2000-01-01T00:00:00',
    }).json()
    assert task['importance'] == task['urgency'] == 'unassigned'
    path = '/api/tasks/' + task['id']
    for payload, expected in [
        ({'importance': 'important'}, ('important', 'unassigned')),
        ({'urgency': 'not_urgent'}, ('important', 'not_urgent')),
        ({'importance': 'not_important'}, ('not_important', 'not_urgent')),
        ({'title': 'renamed', 'priority': 0}, ('not_important', 'not_urgent')),
        ({'urgency': 'urgent'}, ('not_important', 'urgent')),
        ({'importance': 'unassigned'}, ('unassigned', 'urgent')),
        ({'urgency': 'unassigned'}, ('unassigned', 'unassigned')),
    ]:
        response = client.patch(path, json=payload)
        assert response.status_code == 200
        assert (response.json()['importance'], response.json()['urgency']) == expected


def test_subtask_independence_and_recurrence(client):
    parent = client.post('/api/tasks', json={
        'title': 'parent', 'importance': 'important', 'urgency': 'urgent',
    }).json()
    child = client.post('/api/tasks', json={
        'title': 'child', 'parent_id': parent['id'], 'recurrence_rule': 'FREQ=DAILY',
    }).json()
    assert child['importance'] == child['urgency'] == 'unassigned'
    child_path = '/api/tasks/' + child['id']
    client.patch(child_path, json={'importance': 'not_important', 'urgency': 'not_urgent'})
    assert client.patch(child_path, json={'status': 'completed'}).status_code == 200
    successor = next(t for t in client.get('/api/tasks').json() if t['recurrence_occurrence'] == 1)
    assert successor['parent_id'] == parent['id']
    assert (successor['importance'], successor['urgency']) == ('not_important', 'not_urgent')
    client.patch('/api/tasks/' + successor['id'], json={'importance': 'important'})
    assert client.get(child_path).json()['importance'] == 'not_important'
    assert client.get('/api/tasks/' + parent['id']).json()['urgency'] == 'urgent'


@pytest.mark.anyio
@pytest.mark.parametrize('schema', ['migration', 'model'])
async def test_classification_storage_constraints(schema):
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        if schema == 'migration':
            await migrations.migrate(engine)
        else:
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO tasks (id,title,priority,status,actual_minutes,tags,order_index,created_at,updated_at) "
                "VALUES ('a','legacy',3,'todo',0,'[]',0,'2026-01-01','2026-01-01')"
            )
            assert (await conn.exec_driver_sql('SELECT importance,urgency FROM tasks')).one() == ('unassigned', 'unassigned')
            for field, values in [('importance', ['unassigned', 'important', 'not_important']), ('urgency', ['unassigned', 'urgent', 'not_urgent'])]:
                for value in values:
                    await conn.exec_driver_sql(f'UPDATE tasks SET {field}=?', (value,))
                for value in [None, '', 'invalid']:
                    with pytest.raises(IntegrityError):
                        await conn.exec_driver_sql(f'UPDATE tasks SET {field}=?', (value,))
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_legacy_upgrade_and_backup_restore(tmp_path):
    source, target = tmp_path / 'legacy.db', tmp_path / 'restored.db'
    engine = create_async_engine('sqlite+aiosqlite:///' + str(source))
    try:
        async with engine.begin() as conn:
            for migration in migrations.MIGRATIONS[:15]:
                await migration(conn)
            await conn.exec_driver_sql('PRAGMA user_version=15')
            await conn.exec_driver_sql(
                "INSERT INTO tasks (id,title,priority,status,due_date,actual_minutes,tags,order_index,created_at,updated_at) "
                "VALUES ('a','legacy',3,'todo','2000-01-01',0,'[]',0,'2026-01-01','2026-01-01')"
            )
            original = (await conn.exec_driver_sql('SELECT * FROM tasks')).mappings().one()
        await restore_database(source, target)
        await migrations.migrate(engine, checkpoint=False)
        await migrations.migrate(engine, checkpoint=False)
        async with engine.connect() as conn:
            row = (await conn.exec_driver_sql('SELECT * FROM tasks')).mappings().one()
            assert {key: row[key] for key in original} == dict(original)
            assert (row['importance'], row['urgency']) == ('unassigned', 'unassigned')
        with sqlite3.connect(target) as conn:
            assert conn.execute('SELECT importance,urgency FROM tasks').fetchone() == ('unassigned', 'unassigned')
        with sqlite3.connect(source) as conn:
            assert conn.execute('PRAGMA user_version').fetchone()[0] == migrations.LATEST_VERSION
    finally:
        await engine.dispose()


def test_export_and_current_backup_restore(client, tmp_path):
    task = client.post('/api/tasks', json={
        'title': 'portable', 'importance': 'not_important', 'urgency': 'urgent',
    }).json()
    response = client.post('/api/export')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        row = next(t for t in json.loads(archive.read('data.json'))['tasks'] if t['id'] == task['id'])
    assert (row['importance'], row['urgency']) == ('not_important', 'urgent')
    response = client.post('/api/backup')
    assert response.status_code == 200
    source, target = tmp_path / 'backup.db', tmp_path / 'restored.db'
    source.write_bytes(response.content)
    asyncio.run(restore_database(source, target))
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT importance,urgency FROM tasks WHERE id=?', (task['id'],)).fetchone() == ('not_important', 'urgent')


def test_classification_edits_preserve_task_semantics(client):
    task = client.post('/api/tasks', json={
        'title': 'independent', 'priority': 3, 'status': 'in_progress',
        'recurrence_rule': 'FREQ=DAILY',
        'deadline': {'kind': 'date', 'date': '2026-11-01'},
    }).json()
    result = client.patch('/api/tasks/' + task['id'], json={
        'importance': 'important', 'urgency': 'urgent',
    }).json()
    for field in ('priority', 'status', 'deadline', 'due_date', 'deadline_date',
                  'completed_at', 'recurrence_rule', 'recurrence_series_id',
                  'recurrence_occurrence', 'actual_minutes', 'estimated_minutes'):
        assert result[field] == task[field]
    assert len(client.get('/api/tasks').json()) == 1


@pytest.mark.parametrize('importance', ['unassigned', 'important', 'not_important'])
@pytest.mark.parametrize('urgency', ['unassigned', 'urgent', 'not_urgent'])
@pytest.mark.parametrize('deadline', [
    {'kind': 'date', 'date': '2026-11-01'},
    {'kind': 'timed', 'at': '2026-11-01T12:00:00'},
])
def test_recurrence_all_classifications(client, importance, urgency, deadline):
    task = client.post('/api/tasks', json={
        'title': 'repeat', 'importance': importance, 'urgency': urgency,
        'recurrence_rule': 'FREQ=DAILY', 'deadline': deadline,
    }).json()
    assert client.patch('/api/tasks/' + task['id'], json={'status': 'completed'}).status_code == 200
    successor = next(t for t in client.get('/api/tasks').json() if t['id'] != task['id'])
    assert (successor['importance'], successor['urgency']) == (importance, urgency)
    assert successor['deadline']['kind'] == deadline['kind']


def test_ai_creation_defaults_are_not_inferred(client, monkeypatch):
    from app import agents

    async def capture(*args, **kwargs):
        return agents.CaptureOutput(tasks=[
            agents.CapturedTask(title='captured', priority=3, due_date='2000-01-01'),
        ], journal_snippet='')

    async def decompose(*args, **kwargs):
        return agents.DecompositionOutput(subtasks=[
            agents.SubtaskItem(title='decomposed', priority=3, estimated_minutes=30),
        ], advice='')

    monkeypatch.setattr(agents, 'run_capture', capture)
    monkeypatch.setattr(agents, 'run_task_decomposition', decompose)
    response = client.post('/api/agents/capture', json={'text': 'capture'})
    assert response.status_code == 200
    captured = response.json()['tasks'][0]
    parent = client.post('/api/tasks', json={
        'title': 'parent', 'importance': 'important', 'urgency': 'urgent',
    }).json()
    response = client.post('/api/agents/decompose', json={'task_id': parent['id']})
    assert response.status_code == 200
    child = response.json()['subtasks'][0]
    for task in [captured, child]:
        assert task['importance'] == task['urgency'] == 'unassigned'


def test_classification_is_not_exported_in_ics(client):
    task = client.post('/api/tasks', json={
        'title': 'calendar', 'importance': 'not_important', 'urgency': 'not_urgent',
    }).json()
    block = client.post('/api/time-blocks', json={
        'task_id': task['id'], 'start_at': '2026-11-01T09:00:00',
        'end_at': '2026-11-01T10:00:00',
    }).json()
    response = client.post('/api/calendar/export', json={'block_ids': [block['id']]})
    assert response.status_code == 200
    for value in ('IMPORTANCE', 'URGENCY', 'PRIORITY', 'not_important', 'not_urgent'):
        assert value not in response.text
    assert client.get('/api/tasks/' + task['id']).json() == task
