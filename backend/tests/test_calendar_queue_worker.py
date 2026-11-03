"""Periodic outbound recovery and read-only inspection; no network or vault."""
import asyncio
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.calendar_sync.adapter import AuthenticationError, Calendar, CalDAVError, RemoteResource
from app.calendar_sync.queue_worker import QueueWorker, serve
from app.models import CalendarConnection, CalendarDispatch, CalendarLink, Task, TimeBlock
from test_calendar_outbound import change, env, saved  # noqa: F401

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def listing(monkeypatch):
    from test_calendar_outbound import FakeAdapter

    async def list_resources(self, calendar_url):
        self.calls.append(('list', calendar_url))
        return list(self.resources.values())

    async def discover_calendars(self):
        return [Calendar('https://calendar.test/events/', 'Events', True, True)]

    monkeypatch.setattr(FakeAdapter, 'list_resources', list_resources, raising=False)
    monkeypatch.setattr(FakeAdapter, 'discover_calendars', discover_calendars, raising=False)


def writes(env):
    return [call for call in env.adapter.calls if call[0] in ('put', 'delete')]


async def test_pending_is_dispatched_once_and_acknowledged_link_is_inspected(env):
    worker = QueueWorker(env.sessions, env.manager)
    await worker.run_once()
    assert (await saved(env)).state == 'synced'
    assert len(writes(env)) == 1
    await worker.run_once()
    assert len(writes(env)) == 1
    assert any(call[0] == 'list' for call in env.adapter.calls)


@pytest.mark.parametrize('source', ['task', 'block'])
async def test_offline_source_edits_survive_worker_restart(env, source):
    await QueueWorker(env.sessions, env.manager).run_once()
    previous = (await saved(env)).local_revision
    if source == 'task':
        await change(env, Task, env.task.id, title='Offline revised title')
    else:
        from datetime import datetime
        await change(env, TimeBlock, env.block.id, start_at=datetime(2026, 11, 2, 8))
    dirty = await saved(env)
    assert dirty.local_revision > previous
    env.adapter.uncertain, env.adapter.apply = True, False
    await QueueWorker(env.sessions, env.manager).run_once()
    assert (await saved(env)).acknowledged_revision < dirty.local_revision
    assert await saved(env, CalendarDispatch) is not None
    env.adapter.uncertain, env.adapter.apply = False, True
    await QueueWorker(env.sessions, env.manager).run_once()
    result = await saved(env)
    assert result.state == 'synced'
    assert result.acknowledged_revision == result.local_revision
    payload = env.adapter.resources[result.resource_url].payload
    assert (b'Offline revised title' if source == 'task' else b'20261102T080000') in payload


@pytest.mark.parametrize('source', [Task, TimeBlock])
async def test_source_cascade_deletion_removes_remote_event(env, source):
    await QueueWorker(env.sessions, env.manager).run_once()
    async with env.sessions() as session:
        await session.delete(await session.get(source, env.task.id if source is Task else env.block.id))
        await session.commit()
    assert (await saved(env)).desired_action == 'delete'
    await QueueWorker(env.sessions, env.manager).run_once()
    assert env.adapter.resources == {}
    assert (await saved(env)).state == 'detached'
    assert [call[0] for call in writes(env)] == ['put', 'delete']


async def test_uncertain_create_then_local_delete_reconciles_before_deleting(env):
    env.adapter.uncertain = True
    await QueueWorker(env.sessions, env.manager).run_once()
    dispatch = await saved(env, CalendarDispatch)
    assert dispatch.attempted
    async with env.sessions() as session:
        await session.delete(await session.get(TimeBlock, env.block.id))
        await session.commit()
    env.adapter.uncertain = False
    await QueueWorker(env.sessions, env.manager).run_once()
    assert len(writes(env)) == 1
    assert (await saved(env)).desired_action == 'delete'
    await QueueWorker(env.sessions, env.manager).run_once()
    assert [call[0] for call in writes(env)] == ['put', 'delete']
    assert env.adapter.resources == {}
    assert (await saved(env)).state == 'detached'


@pytest.mark.parametrize('changes', [
    {'enabled': False}, {'state': 'authentication_required'}, {'state': 'disconnected'},
])
async def test_connection_gates_preserve_pending_work(env, changes):
    await change(env, CalendarConnection, env.connection.id, **changes)
    await QueueWorker(env.sessions, env.manager).run_once()
    assert env.adapter.calls == []
    assert (await saved(env)).acknowledged_revision == 0


@pytest.mark.parametrize('state', ['detached', 'conflict'])
async def test_link_gates_never_write(env, state):
    await change(env, CalendarLink, env.link.id, state=state)
    await QueueWorker(env.sessions, env.manager).run_once()
    assert env.adapter.calls == []
    assert (await saved(env)).state == state


@pytest.mark.parametrize('remote', ['changed', 'missing'])
async def test_synced_remote_divergence_is_inspected_without_writes(env, remote):
    worker = QueueWorker(env.sessions, env.manager)
    await worker.run_once()
    old = env.adapter.resources[env.link.resource_url]
    if remote == 'missing':
        env.adapter.resources.clear()
    else:
        env.adapter.resources[old.url] = RemoteResource(old.url, '"external"', old.payload)
    env.adapter.calls.clear()
    await worker.run_once()
    assert (await saved(env)).state == 'conflict'
    assert any(call[0] == 'list' for call in env.adapter.calls)
    assert writes(env) == []


async def test_auth_failure_requires_verification_and_explicit_enable(env, monkeypatch):
    original = env.adapter.put_resource

    async def denied(*args, **kwargs):
        raise AuthenticationError()

    monkeypatch.setattr(env.adapter, 'put_resource', denied)
    worker = QueueWorker(env.sessions, env.manager)
    await worker.run_once()
    assert (await saved(env, CalendarDispatch)).attempted
    async with env.sessions() as session:
        connection = await session.get(CalendarConnection, env.connection.id)
        assert connection.state == 'authentication_required'
    monkeypatch.setattr(env.adapter, 'put_resource', original)
    await worker.run_once()
    assert writes(env) == []
    async with env.sessions() as session:
        connection = await env.manager.verify(session, env.connection.id)
        assert not connection.enabled
    await worker.run_once()
    assert writes(env) == []
    await change(env, CalendarConnection, env.connection.id, enabled=True)
    await worker.run_once()
    assert (await saved(env)).state == 'synced'


async def test_cancelled_inflight_write_retains_immutable_dispatch(env):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked():
        entered.set()
        await release.wait()

    env.adapter.before_write = blocked
    task = asyncio.create_task(QueueWorker(env.sessions, env.manager).run_once())
    await entered.wait()
    original = await saved(env, CalendarDispatch)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    durable = await saved(env, CalendarDispatch)
    assert durable.attempted
    assert (durable.payload, durable.revision) == (original.payload, original.revision)
    env.adapter.before_write = None
    await QueueWorker(env.sessions, env.manager).run_once()
    assert (await saved(env)).state == 'synced'


async def test_serve_logs_error_and_runs_next_iteration(env, monkeypatch, caplog):
    calls = []

    async def run_once(self):
        calls.append('run')
        if len(calls) == 1:
            raise RuntimeError('worker iteration failed')

    async def sleep(interval):
        assert interval == 7
        if len(calls) == 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(QueueWorker, 'run_once', run_once)
    monkeypatch.setattr('app.calendar_sync.queue_worker.asyncio.sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await serve(env.sessions, env.manager, interval_seconds=7)
    assert calls == ['run', 'run']
    assert 'worker iteration failed' in caplog.text


@pytest.mark.parametrize('other_connection', [False, True])
async def test_failed_link_does_not_prevent_other_link_dispatch(env, monkeypatch, other_connection):
    async with env.sessions() as session:
        connection_id = env.connection.id
        if other_connection:
            connection = CalendarConnection(
                server_url=env.connection.server_url, calendar_url=env.connection.calendar_url,
                state='connected', enabled=True, credential_state='present',
            )
            session.add(connection)
            await session.flush()
            connection_id = connection.id
            env.store.values[connection_id] = env.store.values[env.connection.id]
        block = TimeBlock(task_id=env.task.id, start_at=env.block.start_at,
                          end_at=env.block.end_at, timezone=env.block.timezone)
        session.add(block)
        await session.flush()
        link = CalendarLink(connection_id=connection_id, block_id=block.id,
                            local_block_id=block.id,
                            uid=f'meditations-time-block-{uuid5(NAMESPACE_URL, "journal:time-block:" + block.id)}@journal.local',
                            resource_url='https://calendar.test/events/second.ics')
        session.add(link)
        await session.commit()
    original = env.adapter.put_resource

    async def selectively_fail(url, *args, **kwargs):
        if url == env.link.resource_url:
            raise CalDAVError('offline first resource')
        return await original(url, *args, **kwargs)

    monkeypatch.setattr(env.adapter, 'put_resource', selectively_fail)
    await QueueWorker(env.sessions, env.manager).run_once()
    assert (await saved(env)).state == 'error'
    async with env.sessions() as session:
        assert (await session.get(CalendarLink, link.id)).state == 'synced'
    assert link.resource_url in env.adapter.resources


@pytest.mark.parametrize('prepared', [False, True])
async def test_never_attempted_create_deleted_offline_requires_no_remote_cleanup(env, prepared):
    if prepared:
        await env.service.prepare(env.link.id)
        assert not (await saved(env, CalendarDispatch)).attempted
    async with env.sessions() as session:
        await session.delete(await session.get(TimeBlock, env.block.id))
        await session.commit()
    await QueueWorker(env.sessions, env.manager).run_once()
    result = await saved(env)
    assert result.state == 'detached'
    assert result.acknowledged_revision == result.local_revision
    assert await saved(env, CalendarDispatch) is None
    assert env.adapter.calls == []


async def test_source_edit_between_acknowledgment_reads_remains_pending(env, monkeypatch):
    from sqlmodel.ext.asyncio.session import AsyncSession

    original = AsyncSession.get
    edited = False

    async def get(session, model, key, *args, **kwargs):
        nonlocal edited
        result = await original(session, model, key, *args, **kwargs)
        if model is CalendarDispatch and writes(env) and not edited:
            edited = True
            await change(env, Task, env.task.id, title='Changed during acknowledgment')
        return result

    monkeypatch.setattr(AsyncSession, 'get', get)
    await QueueWorker(env.sessions, env.manager).run_once()
    pending = await saved(env)
    assert edited
    assert pending.state == 'pending'
    assert pending.acknowledged_revision < pending.local_revision
    await QueueWorker(env.sessions, env.manager).run_once()
    assert (await saved(env)).state == 'synced'
    assert b'Changed during acknowledgment' in env.adapter.resources[pending.resource_url].payload


@pytest.mark.parametrize('boundary', ['link', 'block', 'task', 'delete', 'reassign'])
async def test_source_change_during_preparation_converges_without_losing_revision(env, monkeypatch, boundary):
    from sqlmodel.ext.asyncio.session import AsyncSession

    replacement_id = None
    if boundary == 'reassign':
        async with env.sessions() as session:
            replacement = Task(title='New block owner')
            session.add(replacement)
            await session.commit()
            replacement_id = replacement.id
    original = AsyncSession.get
    link_reads, edited = 0, False

    async def get(session, model, key, *args, **kwargs):
        nonlocal edited, link_reads
        result = await original(session, model, key, *args, **kwargs)
        if model is CalendarLink:
            link_reads += 1
        matches = ((boundary in {'link', 'delete'} and model is CalendarLink and link_reads == 2)
                   or (boundary in {'block', 'reassign'} and model is TimeBlock)
                   or (boundary == 'task' and model is Task))
        if not edited and matches:
            edited = True
            if boundary == 'delete':
                async with env.sessions() as writer:
                    await writer.delete(await original(writer, TimeBlock, env.block.id))
                    await writer.commit()
            elif boundary == 'reassign':
                await change(env, TimeBlock, env.block.id, task_id=replacement_id)
            else:
                await change(env, Task, env.task.id, title='New preparation title')
        return result

    monkeypatch.setattr(AsyncSession, 'get', get)
    for _ in range(3):
        await QueueWorker(env.sessions, env.manager).run_once()
    result = await saved(env)
    assert edited
    assert result.acknowledged_revision == result.local_revision
    if boundary == 'delete':
        assert result.state == 'detached'
        assert not env.adapter.resources
    else:
        assert result.state == 'synced'
        expected = b'New block owner' if boundary == 'reassign' else b'New preparation title'
        assert expected in env.adapter.resources[result.resource_url].payload


async def test_list_removal_unassigns_tasks_without_deleting_calendar_events(env):
    from app.models import TaskList

    async with env.sessions() as session:
        task_list = TaskList(name='Planning')
        session.add(task_list)
        await session.flush()
        task = await session.get(Task, env.task.id)
        task.list_id = task_list.id
        session.add(task)
        await session.commit()
    await QueueWorker(env.sessions, env.manager).run_once()
    before = await saved(env)
    async with env.sessions() as session:
        await session.delete(await session.get(TaskList, task_list.id))
        await session.commit()
        assert (await session.get(Task, env.task.id)).list_id is None
        assert await session.get(TimeBlock, env.block.id) is not None
    await QueueWorker(env.sessions, env.manager).run_once()
    assert (await saved(env)).local_revision == before.local_revision
    assert [call[0] for call in writes(env)] == ['put']


async def test_parent_task_deletion_captures_subtask_block_delete(env):
    async with env.sessions() as session:
        parent = Task(title='Parent')
        session.add(parent)
        await session.flush()
        child = await session.get(Task, env.task.id)
        child.parent_id = parent.id
        session.add(child)
        await session.commit()
    await QueueWorker(env.sessions, env.manager).run_once()
    async with env.sessions() as session:
        await session.delete(await session.get(Task, parent.id))
        await session.commit()
    assert (await saved(env)).desired_action == 'delete'
    await QueueWorker(env.sessions, env.manager).run_once()
    assert (await saved(env)).state == 'detached'
    assert not env.adapter.resources
