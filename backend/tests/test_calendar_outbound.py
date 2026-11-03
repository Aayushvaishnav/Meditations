"""Durable outbound intent tested without a credential vault or CalDAV server."""
import asyncio

from contextlib import asynccontextmanager
from datetime import date, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.migrations import migrate
from app.calendar_sync.adapter import CalDAVError, ConflictError, NotFoundError, RemoteResource
from app.calendar_sync.connections import ConnectionFailure, ConnectionManager
from app.calendar_sync.credentials import Credentials
from app.calendar_sync.outbound import OutboundFailure, OutboundService
from app.models import CalendarConnection, CalendarDispatch, CalendarLink, Task, TimeBlock

pytestmark = pytest.mark.anyio


class MemoryStore:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def put(self, key, value):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)


class FakeAdapter:
    def __init__(self):
        self.resources = {}
        self.calls = []
        self.uncertain = False
        self.apply = True
        self.before_write = None
        self.reject_write = False

    async def list_resources(self, calendar_url):
        self.calls.append(('list', calendar_url))
        return [RemoteResource(url, resource.etag) for url, resource in self.resources.items()]

    async def supports_sync_collection(self, calendar_url):
        self.calls.append(('supports_sync', calendar_url))
        return False

    async def get_resource(self, url):
        self.calls.append(('get', url))
        if url not in self.resources:
            raise NotFoundError()
        return self.resources[url]

    async def put_resource(self, url, payload, *, etag=None):
        self.calls.append(('put', url, payload, etag))
        if self.before_write:
            await self.before_write()
        existing = self.resources.get(url)
        if self.reject_write or (existing.etag if existing else None) != etag:
            raise ConflictError()
        result = RemoteResource(url, '"written"', payload)
        if self.apply:
            self.resources[url] = result
        if self.uncertain:
            raise CalDAVError('secret remote diagnostics')
        return result

    async def delete_resource(self, url, *, etag):
        self.calls.append(('delete', url, etag))
        if self.reject_write or self.resources[url].etag != etag:
            raise ConflictError()
        if self.apply:
            del self.resources[url]
        if self.uncertain:
            raise CalDAVError('secret remote diagnostics')


@pytest.fixture
async def env():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    try:
        await migrate(engine)
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        adapter, store = FakeAdapter(), MemoryStore()

        @asynccontextmanager
        async def adapters(server_url, credentials):
            assert server_url == 'https://calendar.test/'
            assert credentials == Credentials('user', 'password', 'basic')
            yield adapter

        async with sessions() as session:
            connection = CalendarConnection(server_url='https://calendar.test/',
                calendar_url='https://calendar.test/events/', state='connected',
                enabled=True, credential_state='present')
            task = Task(title='Write, think; reflect\n日記', description='PRIVATE DESCRIPTION',
                        tags=['PRIVATE TAG'], recurrence_rule='FREQ=DAILY')
            session.add(connection)
            session.add(task)
            await session.flush()
            block = TimeBlock(task_id=task.id, start_at=datetime(2026, 11, 2, 9),
                              end_at=datetime(2026, 11, 2, 10), timezone='Asia/Kolkata')
            session.add(block)
            await session.flush()
            uid = f'meditations-time-block-{uuid5(NAMESPACE_URL, "journal:time-block:" + block.id)}@journal.local'
            link = CalendarLink(connection_id=connection.id, block_id=block.id,
                                local_block_id=block.id, uid=uid,
                                resource_url='https://calendar.test/events/stable.ics')
            session.add(link)
            await session.commit()
        store.values[connection.id] = Credentials('user', 'password', 'basic')
        manager = ConnectionManager(store, adapters)
        yield SimpleNamespace(sessions=sessions, adapter=adapter, store=store, manager=manager,
                              service=OutboundService(sessions, manager), link=link,
                              connection=connection, task=task, block=block)
    finally:
        await engine.dispose()


async def saved(env, model=CalendarLink):
    async with env.sessions() as session:
        return await session.get(model, env.link.id)


async def change(env, model, key, **changes):
    async with env.sessions() as session:
        row = await session.get(model, key)
        for name, value in changes.items():
            setattr(row, name, value)
        session.add(row)
        await session.commit()


async def prepare_remote(env, *, action='upsert'):
    await env.service.prepare(env.link.id)
    payload = (await saved(env, CalendarDispatch)).payload.encode()
    env.adapter.resources[env.link.resource_url] = RemoteResource(env.link.resource_url, '"old"', payload)
    async with env.sessions() as session:
        await session.delete(await session.get(CalendarDispatch, env.link.id))
        await session.commit()
    await change(env, CalendarLink, env.link.id, etag='"old"', desired_action=action,
                 local_revision=2, acknowledged_revision=1)


async def test_create_and_repeat_dispatch_are_idempotent(env):
    result = await env.service.dispatch(env.link.id)
    assert (result.state, result.acknowledged_revision, result.etag) == ('synced', 1, '"written"')
    calls = list(env.adapter.calls)
    await env.service.dispatch(env.link.id)
    assert env.adapter.calls == calls
    assert await saved(env, CalendarDispatch) is None
    assert calls[-1][3] is None


@pytest.mark.parametrize('action', ['upsert', 'delete'])
async def test_update_delete_use_etag_preconditions(env, action):
    await prepare_remote(env, action=action)
    result = await env.service.dispatch(env.link.id)
    assert result.acknowledged_revision == 2
    assert result.state == ('synced' if action == 'upsert' else 'detached')
    assert env.adapter.calls[-1][-1] == '"old"'
    assert (env.link.resource_url in env.adapter.resources) == (action == 'upsert')


async def test_preexisting_identical_uid_and_payload_is_not_owned(env):
    await env.service.prepare(env.link.id)
    row = await saved(env, CalendarDispatch)
    env.adapter.resources[row.resource_url] = RemoteResource(row.resource_url, '"other"', row.payload.encode())
    result = await env.service.dispatch(env.link.id)
    assert result.state == 'conflict'
    assert not any(call[0] == 'put' for call in env.adapter.calls)
    assert (await saved(env)).acknowledged_revision == 0


@pytest.mark.parametrize('action,applied', [('create', True), ('create', False), ('upsert', True),
                                           ('upsert', False), ('delete', True), ('delete', False)])
async def test_uncertain_writes_reconcile_after_service_restart(env, action, applied):
    if action != 'create':
        await prepare_remote(env, action=action)
    env.adapter.uncertain, env.adapter.apply = True, applied
    with pytest.raises(OutboundFailure) as error:
        await env.service.dispatch(env.link.id)
    assert isinstance(error.value, ConnectionFailure)
    assert error.value.status == 502
    assert 'secret' not in error.value.message
    durable = await saved(env, CalendarDispatch)
    assert durable.attempted
    assert (await saved(env)).state == 'error'
    original_writes = [call for call in env.adapter.calls if call[0] != 'get']
    env.adapter.uncertain, env.adapter.apply = False, True
    restarted = OutboundService(env.sessions, ConnectionManager(env.store, env.manager.adapters))
    result = await restarted.dispatch(env.link.id)
    writes = [call for call in env.adapter.calls if call[0] != 'get']
    assert result.state == ('detached' if action == 'delete' else 'synced')
    if applied:
        assert writes == original_writes
    else:
        assert writes == original_writes * 2
    assert await saved(env, CalendarDispatch) is None


@pytest.mark.parametrize('remote', ['changed', 'missing', 'precondition'])
async def test_remote_divergence_persists_conflict(env, remote):
    await prepare_remote(env)
    if remote == 'missing':
        env.adapter.resources.clear()
    elif remote == 'changed':
        old = env.adapter.resources[env.link.resource_url]
        env.adapter.resources[old.url] = RemoteResource(old.url, '"external"', old.payload)
    else:
        env.adapter.reject_write = True
    assert (await env.service.dispatch(env.link.id)).state == 'conflict'
    assert (await saved(env)).error_state == 'present'
    assert await saved(env, CalendarDispatch) is not None


async def test_newer_revision_during_http_acknowledges_only_snapshot(env):
    async def edit():
        await change(env, Task, env.task.id, title='New title')
        await change(env, CalendarLink, env.link.id, local_revision=2)
    env.adapter.before_write = edit
    result = await env.service.dispatch(env.link.id)
    assert (result.state, result.local_revision, result.acknowledged_revision) == ('pending', 2, 1)
    assert b'New title' not in env.adapter.calls[-1][2]
    env.adapter.before_write = None
    assert (await env.service.dispatch(env.link.id)).acknowledged_revision == 2
    assert b'New title' in env.adapter.calls[-1][2]


async def test_newer_delete_waits_for_uncertain_create_ack(env):
    env.adapter.uncertain = True
    with pytest.raises(OutboundFailure):
        await env.service.dispatch(env.link.id)
    await change(env, CalendarLink, env.link.id, local_revision=2, desired_action='delete', block_id=None)
    async with env.sessions() as session:
        await session.delete(await session.get(TimeBlock, env.block.id))
        await session.commit()
    env.adapter.uncertain = False
    assert (await env.service.dispatch(env.link.id)).state == 'pending'
    assert (await env.service.dispatch(env.link.id)).state == 'detached'
    assert [call[0] for call in env.adapter.calls if call[0] != 'get'] == ['put', 'delete']


@pytest.mark.parametrize('state', ['paused', 'disconnected', 'credential', 'detached', 'conflict'])
async def test_inactive_links_never_contact_server(env, state):
    if state in {'detached', 'conflict'}:
        await change(env, CalendarLink, env.link.id, state=state)
    else:
        changes = {'enabled': False} if state == 'paused' else (
            {'state': 'disconnected'} if state == 'disconnected' else {'credential_state': 'absent'})
        await change(env, CalendarConnection, env.connection.id, **changes)
    for operation in [env.service.prepare, env.service.dispatch]:
        with pytest.raises(OutboundFailure) as error:
            await operation(env.link.id)
        assert error.value.status == 409
    assert env.adapter.calls == []


async def test_detach_is_local_and_preserves_source(env):
    await env.service.prepare(env.link.id)
    assert (await env.service.detach(env.link.id)).state == 'detached'
    assert env.adapter.calls == []
    async with env.sessions() as session:
        assert await session.get(Task, env.task.id) is not None
        assert await session.get(TimeBlock, env.block.id) is not None


@pytest.mark.parametrize('all_day', [False, True])
async def test_prepare_immutable_private_ics_snapshot(env, all_day):
    if all_day:
        await change(env, TimeBlock, env.block.id, kind='all_day', timezone=None,
                     start_at=None, end_at=None, start_date=date(2026, 11, 2), end_date=date(2026, 11, 4))
    await env.service.prepare(env.link.id)
    first = await saved(env, CalendarDispatch)
    text = first.payload.replace('\r\n ', '')
    marker = next(line.split(':', 1)[1] for line in text.split('\r\n') if line.startswith('X-JOURNAL-DISPATCH:'))
    UUID(marker)
    assert f'UID:{env.link.uid}\r\n' in text
    assert 'SUMMARY:Write\\, think\\; reflect\\n日記' in text
    assert 'PRIVATE' not in text and 'RRULE' not in text and 'DESCRIPTION' not in text
    if all_day:
        assert 'DTSTART;VALUE=DATE:20261102\r\n' in text
        assert 'DTEND;VALUE=DATE:20261104\r\n' in text
    else:
        assert 'DTSTART:20261102T090000Z\r\n' in text
        assert 'X-JOURNAL-TIMEZONE:Asia/Kolkata\r\n' in text
    await change(env, Task, env.task.id, title='Changed after preparation')
    await env.service.prepare(env.link.id)
    second = await saved(env, CalendarDispatch)
    assert (second.payload, second.revision, second.attempted) == (first.payload, first.revision, False)
    assert (await saved(env)).local_revision > second.revision
    async with env.sessions() as session:
        task = await session.get(Task, env.task.id)
        assert task.description == 'PRIVATE DESCRIPTION'
        assert task.recurrence_rule == 'FREQ=DAILY'


@pytest.mark.parametrize('mutation', ['changed', 'missing'])
async def test_uncertain_update_does_not_ack_nonidentical_remote(env, mutation):
    await prepare_remote(env)
    env.adapter.uncertain = True
    with pytest.raises(OutboundFailure):
        await env.service.dispatch(env.link.id)
    if mutation == 'missing':
        env.adapter.resources.clear()
    else:
        old = env.adapter.resources[env.link.resource_url]
        env.adapter.resources[old.url] = RemoteResource(old.url, old.etag,
            old.payload.replace(b'SUMMARY:', b'SUMMARY:Externally changed '))
    env.adapter.uncertain = False
    writes = len([call for call in env.adapter.calls if call[0] == 'put'])
    assert (await env.service.dispatch(env.link.id)).state == 'conflict'
    assert (await saved(env)).acknowledged_revision == 1
    assert len([call for call in env.adapter.calls if call[0] == 'put']) == writes


async def test_missing_vault_credential_persists_authentication_error(env):
    env.store.values.clear()
    with pytest.raises(OutboundFailure) as error:
        await env.service.dispatch(env.link.id)
    assert error.value.status == 401
    assert (await saved(env)).state == 'error'
    async with env.sessions() as session:
        connection = await session.get(CalendarConnection, env.connection.id)
        assert connection.state == 'authentication_required'
        assert not connection.enabled
    assert env.adapter.calls == []


@pytest.mark.parametrize('operation', ['dispatch', 'disconnect'])
async def test_manager_serializes_inflight_dispatch(env, monkeypatch, operation):
    writing, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def hold():
        writing.set()
        await release.wait()

    env.adapter.before_write = hold
    first = asyncio.create_task(env.service.dispatch(env.link.id))
    await writing.wait()
    original_lock = env.manager.lock

    @asynccontextmanager
    async def observed_lock(key):
        waiting.set()
        async with original_lock(key):
            yield

    monkeypatch.setattr(env.manager, 'lock', observed_lock)

    async def followup():
        if operation == 'dispatch':
            return await OutboundService(env.sessions, env.manager).dispatch(env.link.id)
        async with env.sessions() as session:
            return await env.manager.disconnect(session, env.connection.id)

    second = asyncio.create_task(followup())
    try:
        await waiting.wait()
        assert not second.done()
        assert env.connection.id in env.store.values
        release.set()
        await first
        result = await second
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
    assert [c[0] for c in env.adapter.calls if c[0] != 'get'] == ['put']
    assert await saved(env, CalendarDispatch) is None
    if operation == 'disconnect':
        assert result.state == 'disconnected'
        assert (await saved(env)).state == 'detached'
        assert env.connection.id not in env.store.values
    else:
        assert result.state == 'synced'


async def test_cancelled_remote_write_recovers_snapshot(env, monkeypatch):
    written, release = asyncio.Event(), asyncio.Event()
    original_put = env.adapter.put_resource

    async def interrupted_put(*args, **kwargs):
        result = await original_put(*args, **kwargs)
        written.set()
        await release.wait()
        return result

    monkeypatch.setattr(env.adapter, 'put_resource', interrupted_put)
    dispatch = asyncio.create_task(env.service.dispatch(env.link.id))
    try:
        await written.wait()
        snapshot = await saved(env, CalendarDispatch)
        assert snapshot.attempted
        dispatch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await dispatch
    finally:
        release.set()
        if not dispatch.done():
            dispatch.cancel()
        await asyncio.gather(dispatch, return_exceptions=True)
    await change(env, Task, env.task.id, title='Edited after cancellation')
    await change(env, CalendarLink, env.link.id, local_revision=2)
    restarted = OutboundService(env.sessions, ConnectionManager(env.store, env.manager.adapters))
    result = await restarted.dispatch(env.link.id)
    assert (result.state, result.acknowledged_revision) == ('pending', snapshot.revision)
    assert env.adapter.resources[snapshot.resource_url].payload == snapshot.payload.encode()
    assert len([c for c in env.adapter.calls if c[0] == 'put']) == 1
    assert await saved(env, CalendarDispatch) is None


@pytest.mark.parametrize('action', ['upsert', 'delete'])
async def test_ack_commit_failure_keeps_durable_dispatch(env, monkeypatch, action):
    await prepare_remote(env, action=action)
    original_commit = AsyncSession.commit
    failed = False

    async def fail_commit(session):
        nonlocal failed
        mutated = (env.link.resource_url not in env.adapter.resources if action == 'delete'
                   else env.adapter.resources[env.link.resource_url].etag == '"written"')
        if mutated and not failed:
            failed = True
            raise RuntimeError('injected SQL commit failure')
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, 'commit', fail_commit)
    with pytest.raises(RuntimeError, match='injected SQL commit failure'):
        await env.service.dispatch(env.link.id)
    snapshot = await saved(env, CalendarDispatch)
    assert snapshot.attempted
    assert (await saved(env)).acknowledged_revision == 1
    writes = [c for c in env.adapter.calls if c[0] != 'get']
    restarted = OutboundService(env.sessions, ConnectionManager(env.store, env.manager.adapters))
    result = await restarted.dispatch(env.link.id)
    assert failed
    assert result.acknowledged_revision == snapshot.revision
    assert result.state == ('synced' if action == 'upsert' else 'detached')
    assert [c for c in env.adapter.calls if c[0] != 'get'] == writes
    assert await saved(env, CalendarDispatch) is None


@pytest.mark.parametrize('action', ['upsert', 'delete'])
@pytest.mark.parametrize('content', ['malformed', 'recurrence'])
async def test_unsupported_remote_content_blocks_writes(env, action, content):
    await prepare_remote(env, action=action)
    remote = env.adapter.resources[env.link.resource_url]
    payload = (b'not a calendar' if content == 'malformed' else
               remote.payload.replace(b'END:VEVENT\r\n', b'RRULE:FREQ=DAILY\r\nEND:VEVENT\r\n'))
    env.adapter.resources[remote.url] = RemoteResource(remote.url, remote.etag, payload)
    assert (await env.service.dispatch(env.link.id)).state == 'conflict'
    assert (await saved(env)).acknowledged_revision == 1
    assert all(c[0] == 'get' for c in env.adapter.calls)
    assert env.adapter.resources[remote.url].payload == payload


async def test_corrected_source_retries_preparation_failure(env):
    await change(env, Task, env.task.id, title='Unrepresentable\x00title')
    with pytest.raises(OutboundFailure):
        await env.service.prepare(env.link.id)
    assert await saved(env, CalendarDispatch) is None
    assert env.adapter.calls == []
    await change(env, Task, env.task.id, title='Corrected title')
    result = await env.service.dispatch(env.link.id)
    assert result.state == 'synced'
    assert result.acknowledged_revision == result.local_revision
    assert len([c for c in env.adapter.calls if c[0] == 'put']) == 1


@pytest.mark.parametrize('tampering', [
    {'revision': 2}, {'uid': 'unrelated@calendar.test'},
    {'expected_etag': '"unrelated"'},
])
async def test_tampered_dispatch_rejected_without_remote_calls(env, tampering):
    await env.service.prepare(env.link.id)
    await change(env, CalendarDispatch, env.link.id, **tampering)
    result = await env.service.dispatch(env.link.id)
    assert result.state == 'conflict'
    assert result.acknowledged_revision == 0
    assert env.adapter.calls == []
    assert await saved(env, CalendarDispatch) is not None


@pytest.mark.parametrize('changes', [
    {'state': 'syncing'}, {'acknowledged_revision': 1, 'local_revision': 2, 'etag': None},
])
async def test_missing_dispatch_with_uncertain_prior_outcome_conflicts(env, changes):
    await change(env, CalendarLink, env.link.id, **changes)
    assert (await env.service.dispatch(env.link.id)).state == 'conflict'
    assert env.adapter.calls == []
    assert await saved(env, CalendarDispatch) is None


@pytest.mark.parametrize('etag', [None, 'W/"weak"'])
async def test_real_adapter_requires_strong_get_etag_before_any_mutation(env, etag):
    import httpx
    from app.calendar_sync.adapter import CalDAVAdapter

    await prepare_remote(env)
    body = env.adapter.resources[env.link.resource_url].payload
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=body, headers={} if etag is None else {'ETag': etag})

    @asynccontextmanager
    async def adapters(_server, _credentials):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            yield CalDAVAdapter(env.connection.server_url, client)

    env.manager.adapters = adapters
    with pytest.raises(OutboundFailure) as error:
        await env.service.dispatch(env.link.id)
    assert error.value.status == 502
    assert [request.method for request in requests] == ['GET']
    assert not (await saved(env, CalendarDispatch)).attempted
    assert (await saved(env)).acknowledged_revision == 1


async def test_real_adapter_missing_put_etag_recovers_exact_payload_without_duplicate(env):
    import httpx
    from app.calendar_sync.adapter import CalDAVAdapter

    body = None
    requests = []

    def respond(request):
        nonlocal body
        requests.append(request)
        if request.method == 'GET':
            return (httpx.Response(404) if body is None else
                    httpx.Response(200, content=body, headers={'ETag': '"server-v1"'}))
        assert request.method == 'PUT'
        assert request.headers['If-None-Match'] == '*'
        body = request.content
        return httpx.Response(201)

    @asynccontextmanager
    async def adapters(_server, _credentials):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            yield CalDAVAdapter(env.connection.server_url, client)

    env.manager.adapters = adapters
    with pytest.raises(OutboundFailure):
        await env.service.dispatch(env.link.id)
    assert (await saved(env, CalendarDispatch)).attempted
    assert (await saved(env)).acknowledged_revision == 0
    recovered = await OutboundService(env.sessions, env.manager).dispatch(env.link.id)
    assert (recovered.state, recovered.etag, recovered.acknowledged_revision) == ('synced', '"server-v1"', 1)
    assert [request.method for request in requests] == ['GET', 'PUT', 'GET']
    assert await saved(env, CalendarDispatch) is None


async def test_newer_upsert_waits_for_uncertain_delete_then_reuses_same_identity(env):
    await prepare_remote(env, action='delete')
    env.adapter.uncertain = True
    with pytest.raises(OutboundFailure):
        await env.service.dispatch(env.link.id)
    await change(env, Task, env.task.id, title='Opted back in')
    await change(env, CalendarLink, env.link.id, local_revision=3, desired_action='upsert')
    env.adapter.uncertain = False
    deleted = await env.service.dispatch(env.link.id)
    assert (deleted.state, deleted.acknowledged_revision, deleted.acknowledged_action) == ('pending', 2, 'delete')
    assert deleted.etag is None
    recreated = await env.service.dispatch(env.link.id)
    assert (recreated.state, recreated.acknowledged_revision, recreated.acknowledged_action) == ('synced', 3, 'upsert')
    writes = [call for call in env.adapter.calls if call[0] != 'get']
    assert [call[0] for call in writes] == ['delete', 'put']
    assert all(call[1] == env.link.resource_url for call in writes)
    assert writes[-1][3] is None
    assert b'Opted back in' in writes[-1][2]
    assert f'UID:{env.link.uid}'.encode() in writes[-1][2].replace(b'\r\n ', b'')
