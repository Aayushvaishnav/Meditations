"""SYNC-02 capability-aware inbound reconciliation; no server, vault, or user database."""
import asyncio

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.migrations import migrate
from app.calendar_sync.adapter import (
    AuthenticationError, CalDAVError, NotFoundError, RemoteResource, SyncTokenInvalid, SyncResult, SyncChange,
)
from app.calendar_sync.inbound import InboundService, reconcile_connections
from app.models import CalendarConnection, CalendarInboundEvent, CalendarInboundState

pytestmark = pytest.mark.anyio


def ics(uid='external-1', summary='Dentist', start='20260115T090000Z', end='20260115T100000Z'):
    return (f'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\n'
            f'DTSTAMP:20260101T000000Z\r\nSUMMARY:{summary}\r\n'
            f'DTSTART:{start}\r\nDTEND:{end}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')


class FakeAdapter:
    def __init__(self, resources=None, supports_tokens=True):
        self.resources = dict(resources or {})  # url -> (etag, content)
        self.supports_tokens = supports_tokens
        self.token = 'token-1'
        self.tokens_seen = []
        self.calls = []
        self.fail_sync_collection = None
        self.fail_on_initial = False  # invalid tokens recover within the same pass
        self.known = {}  # server-side view the client last synchronized

    async def list_resources(self, calendar_url):
        self.calls.append('list')
        return [RemoteResource(url, etag) for url, (etag, _) in self.resources.items()]

    async def supports_sync_collection(self, calendar_url):
        self.calls.append('supports')
        return self.supports_tokens

    async def sync_collection(self, calendar_url, token=None):
        self.calls.append('sync')
        self.tokens_seen.append(token)
        if self.fail_sync_collection and (token is not None or self.fail_on_initial):
            raise self.fail_sync_collection
        if token is None:
            self.known = {url: etag for url, (etag, _) in self.resources.items()}
            return SyncResult(self.token, tuple(
                SyncChange(url, etag) for url, (etag, _) in self.resources.items()))
        changes = []
        for url, (etag, _) in self.resources.items():
            if self.known.get(url) != etag:
                changes.append(SyncChange(url, etag))
        for url in self.known:
            if url not in self.resources:
                changes.append(SyncChange(url, None))
        self.known = {url: etag for url, (etag, _) in self.resources.items()}
        return SyncResult(self.token, tuple(changes))

    async def get_resource(self, url):
        self.calls.append(('get', url))
        etag, content = self.resources[url]
        return RemoteResource(url, etag, content)


@pytest.fixture
async def engine():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    try:
        await migrate(engine)
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def seed(sessions, **overrides):
    connection = CalendarConnection(server_url='https://dav.test/', calendar_url='https://dav.test/cal/',
                                    state='connected', enabled=True, credential_state='present', **overrides)
    async with sessions() as session:
        session.add(connection)
        await session.commit()
        await session.refresh(connection)
    return connection


def adapter_for(adapter):
    @asynccontextmanager
    async def adapters(connection):
        yield adapter
    return adapters


async def state_of(sessions, connection_id):
    async with sessions() as session:
        return (await session.exec(select(CalendarInboundState).where(
            CalendarInboundState.connection_id == connection_id))).first()


async def events_of(sessions, connection_id):
    async with sessions() as session:
        return (await session.exec(select(CalendarInboundEvent).where(
            CalendarInboundEvent.connection_id == connection_id))).all()


async def test_initial_sync_token_pass_caches_all_events(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics())})
    connection = await seed(sessions)
    outcome = await InboundService(sessions).reconcile(connection, adapter)
    assert (outcome.capability, outcome.rebuilt, outcome.fetched) == ('sync_token', True, 1)
    rows = await events_of(sessions, connection.id)
    assert [row.uid for row in rows] == ['external-1']
    state = await state_of(sessions, connection.id)
    assert state.capability == 'sync_token' and state.sync_token == 'token-1'


async def test_incremental_pass_fetches_only_changed_events(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics())})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    adapter.resources['https://dav.test/cal/b.ics'] = ('"b1"', ics('external-2', 'Standup'))
    adapter.token = 'token-2'
    adapter.calls.clear()
    outcome = await service.reconcile(connection, adapter)
    assert (outcome.rebuilt, outcome.fetched) == (False, 1)
    assert adapter.calls.count('supports') == 0  # persisted capability skips the probe
    assert ('get', 'https://dav.test/cal/a.ics') not in adapter.calls  # unchanged ETag skips GET
    assert {row.uid for row in await events_of(sessions, connection.id)} == {'external-1', 'external-2'}


async def test_deletion_change_removes_cached_event(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics())})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    adapter.token = 'token-2'

    async def sync_with_delete(calendar_url, token=None):
        return SyncResult('token-2', (SyncChange('https://dav.test/cal/a.ics', None),))

    adapter.sync_collection = sync_with_delete
    outcome = await service.reconcile(connection, adapter)
    assert (outcome.removed, outcome.fetched) == (1, 0)
    assert await events_of(sessions, connection.id) == []


async def test_invalid_token_rebuilds_cache_from_complete_listing(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics())})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    adapter.resources['https://dav.test/cal/b.ics'] = ('"b1"', ics('external-2'))
    adapter.fail_sync_collection = SyncTokenInvalid('expired')
    adapter.fail_on_initial = False
    adapter.token = 'token-reborn'
    outcome = await service.reconcile(connection, adapter)
    assert outcome.rebuilt is True
    assert {row.uid for row in await events_of(sessions, connection.id)} == {'external-1', 'external-2'}
    state = await state_of(sessions, connection.id)
    assert state.sync_token == 'token-reborn'


async def test_server_without_token_support_uses_listing_mode(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics())}, supports_tokens=False)
    connection = await seed(sessions)
    outcome = await InboundService(sessions).reconcile(connection, adapter)
    assert outcome.capability == 'listing'
    state = await state_of(sessions, connection.id)
    assert state.capability == 'listing' and state.sync_token is None


async def test_listing_mode_removal_requires_complete_new_listing(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics()),
                           'https://dav.test/cal/b.ics': ('"b1"', ics('external-2'))},
                          supports_tokens=False)
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    del adapter.resources['https://dav.test/cal/b.ics']
    outcome = await service.reconcile(connection, adapter)
    assert outcome.removed == 1
    assert [row.uid for row in await events_of(sessions, connection.id)] == ['external-1']


async def test_incomplete_batch_leaves_previous_cache_intact(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics())})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    state_before = await state_of(sessions, connection.id)
    adapter.token = 'token-2'
    adapter.resources['https://dav.test/cal/b.ics'] = ('"b1"', ics('external-2'))

    async def broken_get(url):
        raise CalDAVError('transport failure')

    adapter.get_resource = broken_get
    with pytest.raises(CalDAVError):
        await service.reconcile(connection, adapter)
    assert [row.uid for row in await events_of(sessions, connection.id)] == ['external-1']
    state_after = await state_of(sessions, connection.id)
    assert state_after.sync_token == state_before.sync_token
    assert state_after.error_state == 'present'


async def test_unparsable_resource_is_cached_with_reason(sessions):
    garbage = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nEND:VTODO\r\nEND:VCALENDAR\r\n'
    adapter = FakeAdapter({'https://dav.test/cal/x.ics': ('"v1"', garbage)})
    connection = await seed(sessions)
    await InboundService(sessions).reconcile(connection, adapter)
    rows = await events_of(sessions, connection.id)
    assert rows[0].component_state == 'unparsable' and rows[0].content == garbage


async def test_authentication_failure_demotes_connection(sessions):
    adapter = FakeAdapter()
    adapter.fail_sync_collection = AuthenticationError()
    adapter.fail_on_initial = True
    connection = await seed(sessions)
    await reconcile_connections(sessions, adapter_for(adapter))
    async with sessions() as session:
        fresh = await session.get(CalendarConnection, connection.id)
    assert fresh.state == 'authentication_required' and fresh.enabled is False


async def test_protocol_failure_records_error_without_touching_cache(sessions):
    adapter = FakeAdapter({'https://dav.test/cal/a.ics': ('"v1"', ics())})
    connection = await seed(sessions)
    await reconcile_connections(sessions, adapter_for(adapter))
    adapter.fail_sync_collection = CalDAVError('server exploded')
    await reconcile_connections(sessions, adapter_for(adapter))
    state = await state_of(sessions, connection.id)
    assert state.error_state == 'present' and 'exploded' in state.last_error
    async with sessions() as session:
        fresh = await session.get(CalendarConnection, connection.id)
    assert fresh.state == 'connected'  # operational errors do not demote


async def test_disabled_or_unverified_connections_are_skipped(sessions):
    adapter = FakeAdapter()
    async with sessions() as session:
        session.add(CalendarConnection(server_url='https://dav.test/1', calendar_url='https://dav.test/cal/',
                                       state='connected', enabled=False, credential_state='present'))
        session.add(CalendarConnection(server_url='https://dav.test/2', calendar_url='https://dav.test/cal/',
                                       state='authentication_required', enabled=True, credential_state='present'))
        await session.commit()
    await reconcile_connections(sessions, adapter_for(adapter))
    assert adapter.calls == []


async def test_multi_event_resources_are_unparsable_not_projected(sessions):
    two = ics() .replace('END:VEVENT', 'END:VEVENT\r\nBEGIN:VEVENT\r\nUID:second\r\nDTSTAMP:20260101T000000Z\r\nDTSTART:20260116T090000Z\r\nDTEND:20260116T100000Z\r\nEND:VEVENT')
    adapter = FakeAdapter({'https://dav.test/cal/two.ics': ('"v1"', two)})
    connection = await seed(sessions)
    await InboundService(sessions).reconcile(connection, adapter)
    rows = await events_of(sessions, connection.id)
    assert rows[0].component_state == 'unparsable'
