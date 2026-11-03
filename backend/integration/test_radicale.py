"""Run explicitly: uv run --group calendar-test pytest integration/test_radicale.py."""
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_sync.adapter import AuthenticationError, CalDAVError, ConflictError
from app.calendar_sync.connections import ConnectionManager, require_verification_on_startup
from app.calendar_sync.controls import CalendarControls
from app.calendar_sync.credentials import Credentials
from app.calendar_sync.outbound import OutboundFailure, OutboundService
from app.calendar_sync.queue_worker import QueueWorker
from app.calendar_sync.transport import open_adapter
from app.migrations import migrate
from app.models import CalendarConnection, CalendarLink, Task, TimeBlock
from integration.conftest import PASSWORD, USERNAME

pytestmark = pytest.mark.anyio
CREDENTIALS = Credentials(USERNAME, PASSWORD, 'basic')


class MemoryStore:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def put(self, key, value):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)


def database_engine(url):
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, 'connect')
    def pragmas(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')

    return engine


@pytest.fixture
async def connected(radicale_server, tmp_path):
    engine = database_engine(f'sqlite+aiosqlite:///{tmp_path / "journal.db"}')
    env = SimpleNamespace(engine=engine)
    try:
        await migrate(engine)
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        store = MemoryStore()
        manager = ConnectionManager(store)
        async with sessions() as session:
            connection = CalendarConnection(server_url=radicale_server.url,
                                            calendar_url=radicale_server.calendar_url)
            task = Task(title='Plan, reflect; 日記', description='PRIVATE DESCRIPTION',
                        recurrence_rule='FREQ=DAILY')
            session.add(connection)
            session.add(task)
            await session.commit()
            await manager.connect(session, connection.id, CREDENTIALS, radicale_server.calendar_url)
        control = CalendarControls(QueueWorker(sessions, manager))
        await control.enable(connection.id, True)
        env.sessions, env.manager, env.store, env.control = sessions, manager, store, control
        env.connection, env.task, env.server = connection, task, radicale_server
        yield env
    finally:
        await env.engine.dispose()


async def reopen_database(env):
    url = env.engine.url
    await env.engine.dispose()
    env.engine = database_engine(url)
    env.sessions = async_sessionmaker(env.engine, class_=AsyncSession, expire_on_commit=False)
    # Keep only the explicit fake vault; all SQLite connections are replaced
    async with env.sessions() as session:
        await require_verification_on_startup(session)


async def add_block(env, **values):
    async with env.sessions() as session:
        block = TimeBlock(task_id=env.task.id, **values)
        session.add(block)
        await session.commit()
        link = await env.control.opt_in(env.connection.id, block.id)
    return block, link


async def load(env, model, key):
    async with env.sessions() as session:
        return await session.get(model, key)


async def update(env, model, key, **values):
    async with env.sessions() as session:
        row = await session.get(model, key)
        for field, value in values.items():
            setattr(row, field, value)
        session.add(row)
        await session.commit()


async def test_discovery_authentication_and_conditional_writes(radicale_server):
    async with open_adapter(radicale_server.url, CREDENTIALS) as adapter:
        calendars = await adapter.discover_calendars()
        assert [(c.url, c.writable, c.supports_vevent) for c in calendars] == [
            (radicale_server.calendar_url, True, True)]
        url = radicale_server.calendar_url + 'independent.ics'
        payload = (b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n'
                   b'BEGIN:VEVENT\r\nUID:independent\r\nDTSTAMP:20261101T000000Z\r\n'
                   b'DTSTART;VALUE=DATE:20261101\r\nDTEND;VALUE=DATE:20261103\r\n'
                   b'SUMMARY:Unrelated event\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
        created = await adapter.put_resource(url, payload)
        remote = await adapter.get_resource(url)
        assert remote.etag == created.etag
        assert b'DTSTART;VALUE=DATE:20261101' in remote.payload
        with pytest.raises(ConflictError):
            await adapter.put_resource(url, payload)
        changed = await adapter.put_resource(url, payload.replace(b'Unrelated', b'Changed'), etag=remote.etag)
        assert changed.etag != created.etag
        for operation in (adapter.put_resource(url, payload, etag=created.etag),
                          adapter.delete_resource(url, etag=created.etag)):
            with pytest.raises(ConflictError):
                await operation
        assert len(await adapter.list_resources(radicale_server.calendar_url)) == 1
        await adapter.delete_resource(url, etag=changed.etag)
        assert await adapter.list_resources(radicale_server.calendar_url) == []
    async with open_adapter(radicale_server.url, Credentials(USERNAME, 'wrong', 'basic')) as adapter:
        with pytest.raises(AuthenticationError):
            await adapter.discover_calendars()


@pytest.mark.parametrize('interval,expected', [
    ({'kind': 'all_day', 'timezone': None, 'start_date': date(2026, 3, 7),
      'end_date': date(2026, 3, 10)}, [b'DTSTART;VALUE=DATE:20260307', b'DTEND;VALUE=DATE:20260310']),
    ({'kind': 'timed', 'timezone': 'America/New_York', 'start_at': datetime(2026, 3, 8, 6, 30),
      'end_at': datetime(2026, 3, 8, 7, 30)}, [b'DTSTART:20260308T063000Z', b'DTEND:20260308T073000Z']),
    ({'kind': 'timed', 'timezone': 'America/New_York', 'start_at': datetime(2026, 11, 1, 5, 30),
      'end_at': datetime(2026, 11, 1, 6, 30)}, [b'DTSTART:20261101T053000Z', b'DTEND:20261101T063000Z']),
])
async def test_publication_completion_cancellation_and_deletion(connected, interval, expected):
    env = connected
    block, link = await add_block(env, **interval)
    async with open_adapter(env.server.url, CREDENTIALS) as adapter:
        assert await adapter.list_resources(env.server.calendar_url) == []
        await env.control.sync_now(env.connection.id)
        remote = await adapter.get_resource(link.resource_url)
        for value in expected:
            assert value in remote.payload
        if interval['kind'] == 'timed':
            assert b'X-JOURNAL-TIMEZONE:America/New_York' in remote.payload
        assert b'RRULE' not in remote.payload
        assert b'PRIVATE' not in remote.payload
        assert (await load(env, CalendarLink, link.id)).state == 'synced'
        await env.control.sync_now(env.connection.id)
        assert (await adapter.get_resource(link.resource_url)).etag == remote.etag
        await update(env, Task, env.task.id, status='completed')
        await env.control.sync_now(env.connection.id)
        assert b'STATUS:CONFIRMED' in (await adapter.get_resource(link.resource_url)).payload
        await update(env, Task, env.task.id, status='canceled')
        await env.control.sync_now(env.connection.id)
        assert b'STATUS:CANCELLED' in (await adapter.get_resource(link.resource_url)).payload
        async with env.sessions() as session:
            await session.delete(await session.get(TimeBlock, block.id))
            await session.commit()
        await env.control.sync_now(env.connection.id)
        assert await adapter.list_resources(env.server.calendar_url) == []
        assert (await load(env, CalendarLink, link.id)).state == 'detached'


async def test_unselected_blocks_and_unrelated_remote_events_stay_independent(connected):
    env = connected
    _, link = await add_block(env, start_at=datetime(2026, 11, 2, 9),
                              end_at=datetime(2026, 11, 2, 10), timezone='UTC')
    async with env.sessions() as session:
        session.add(TimeBlock(task_id=env.task.id, start_at=datetime(2026, 11, 3, 9),
                              end_at=datetime(2026, 11, 3, 10), timezone='UTC'))
        await session.commit()
    async with open_adapter(env.server.url, CREDENTIALS) as adapter:
        other_url = env.server.calendar_url + 'unrelated.ics'
        other = (b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Other//EN\r\n'
                 b'BEGIN:VEVENT\r\nUID:other-client\r\nDTSTAMP:20261101T000000Z\r\n'
                 b'DTSTART;VALUE=DATE:20261101\r\nDTEND;VALUE=DATE:20261102\r\n'
                 b'END:VEVENT\r\nEND:VCALENDAR\r\n')
        await adapter.put_resource(other_url, other)
        before = await adapter.get_resource(other_url)
        await env.control.sync_now(env.connection.id)
        assert len(await adapter.list_resources(env.server.calendar_url)) == 2
        await env.control.opt_out(env.connection.id, link.local_block_id)
        await env.control.sync_now(env.connection.id)
        resources = await adapter.list_resources(env.server.calendar_url)
        assert [resource.url for resource in resources] == [other_url]
        after = await adapter.get_resource(other_url)
        assert (after.etag, after.payload) == (before.etag, before.payload)


async def test_remote_edit_conflicts_and_disconnect_preserves_copy(connected):
    env = connected
    _, link = await add_block(env, start_at=datetime(2026, 11, 2, 9),
                              end_at=datetime(2026, 11, 2, 10), timezone='UTC')
    await env.control.sync_now(env.connection.id)
    async with open_adapter(env.server.url, CREDENTIALS) as adapter:
        remote = await adapter.get_resource(link.resource_url)
        changed = remote.payload.replace(b'STATUS:CONFIRMED', b'STATUS:TENTATIVE')
        await adapter.put_resource(link.resource_url, changed, etag=remote.etag)
        await update(env, Task, env.task.id, title='Local edit')
        await env.control.sync_now(env.connection.id)
        assert (await load(env, CalendarLink, link.id)).state == 'conflict'
        assert (await adapter.get_resource(link.resource_url)).payload == changed
        async with env.sessions() as session:
            await env.manager.disconnect(session, env.connection.id)
        assert len(await adapter.list_resources(env.server.calendar_url)) == 1
        assert env.store.values == {}


@pytest.mark.parametrize("action", ["create", "update", "delete"])
async def test_interrupted_write_retries_after_worker_restart(connected, action):
    env = connected
    _, link = await add_block(env, start_at=datetime(2026, 11, 2, 9),
                              end_at=datetime(2026, 11, 2, 10), timezone='UTC')

    if action != 'create':
        await env.control.sync_now(env.connection.id)
        if action == 'update':
            await update(env, Task, env.task.id, title='Updated before response loss')
        else:
            await env.control.opt_out(env.connection.id, link.local_block_id)

    class LostResponse:
        def __init__(self, adapter):
            self.adapter = adapter

        def __getattr__(self, name):
            return getattr(self.adapter, name)

        async def put_resource(self, *args, **kwargs):
            await self.adapter.put_resource(*args, **kwargs)
            raise CalDAVError('Injected response loss after server commit')

        async def delete_resource(self, *args, **kwargs):
            await self.adapter.delete_resource(*args, **kwargs)
            raise CalDAVError('Injected response loss after server deletion')

    @asynccontextmanager
    async def interrupted(url, credentials):
        async with open_adapter(url, credentials) as adapter:
            yield LostResponse(adapter)

    failed = ConnectionManager(env.store, interrupted)
    with pytest.raises(OutboundFailure):
        await OutboundService(env.sessions, failed).dispatch(link.id)
    assert (await load(env, CalendarLink, link.id)).state == 'error'
    await reopen_database(env)
    restarted = ConnectionManager(env.store)
    async with env.sessions() as session:
        await restarted.verify(session, env.connection.id)
    control = CalendarControls(QueueWorker(env.sessions, restarted))
    await control.enable(env.connection.id, True)
    await control.sync_now(env.connection.id)
    assert (await load(env, CalendarLink, link.id)).state == ('detached' if action == 'delete' else 'synced')
    async with open_adapter(env.server.url, CREDENTIALS) as adapter:
        assert len(await adapter.list_resources(env.server.calendar_url)) == (0 if action == 'delete' else 1)


@pytest.mark.parametrize('action', ['create', 'update', 'delete'])
async def test_offline_work_survives_recreated_manager(connected, action):
    env = connected
    block, link = await add_block(env, start_at=datetime(2026, 11, 2, 9),
                                  end_at=datetime(2026, 11, 2, 10), timezone='UTC')
    if action != 'create':
        await env.control.sync_now(env.connection.id)
    env.server.process.stop()
    try:
        if action == 'update':
            await update(env, Task, env.task.id, title='Edited offline')
        elif action == 'delete':
            async with env.sessions() as session:
                await session.delete(await session.get(TimeBlock, block.id))
                await session.commit()
        await env.control.sync_now(env.connection.id)
        assert (await load(env, CalendarLink, link.id)).state == 'error'
    finally:
        env.server.process.restart()
    await reopen_database(env)
    manager = ConnectionManager(env.store)
    async with env.sessions() as session:
        await manager.verify(session, env.connection.id)
    control = CalendarControls(QueueWorker(env.sessions, manager))
    await control.enable(env.connection.id, True)
    await control.sync_now(env.connection.id)
    state = await load(env, CalendarLink, link.id)
    assert state.state == ('detached' if action == 'delete' else 'synced')
    assert state.acknowledged_revision == state.local_revision
    async with open_adapter(env.server.url, CREDENTIALS) as adapter:
        resources = await adapter.list_resources(env.server.calendar_url)
        assert len(resources) == (0 if action == 'delete' else 1)
        if action == 'update':
            assert b'SUMMARY:Edited offline' in (await adapter.get_resource(link.resource_url)).payload


def test_packaged_backend_discovery(radicale_server):
    binary = os.environ.get('JOURNAL_TEST_SIDECAR')
    if binary is None:
        pytest.skip('Set JOURNAL_TEST_SIDECAR to test the frozen executable')
    from scripts.smoke_sidecar import smoke

    smoke(Path(binary), calendar_server_url=radicale_server.url)
