"""Batch reset, version and cache identity regressions for inbound reconciliation."""
from contextlib import asynccontextmanager

import pytest
from sqlmodel import select

from app.calendar_sync.adapter import CalDAVError, RemoteResource, SyncChange, SyncResult, SyncTokenInvalid
from app.calendar_sync.inbound import InboundFailure, InboundService
from app.models import CalendarInboundEvent, CalendarInboundState
from test_calendar_inbound import FakeAdapter, engine, sessions, seed, state_of, events_of, ics  # noqa: F401

pytestmark = pytest.mark.anyio
A = 'https://dav.test/cal/a.ics'
B = 'https://dav.test/cal/b.ics'


async def test_expired_token_initial_report_removes_missing_events(sessions):
    adapter = FakeAdapter({A: ('"a1"', ics()), B: ('"b1"', ics('other'))})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    del adapter.resources[B]
    adapter.fail_sync_collection = SyncTokenInvalid('expired')
    adapter.token = 'rebuilt'
    await service.reconcile(connection, adapter)
    assert [row.resource_url for row in await events_of(sessions, connection.id)] == [A]
    assert (await state_of(sessions, connection.id)).sync_token == 'rebuilt'


@pytest.mark.parametrize('tokens', [False, True])
async def test_get_version_must_match_report_before_cursor_advance(sessions, tokens):
    adapter = FakeAdapter({A: ('"a1"', ics())}, supports_tokens=tokens)
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    before = await state_of(sessions, connection.id)
    adapter.resources[A] = ('"a2"', ics(summary='Reported'))
    adapter.token = 'token-2'

    async def raced_get(url):
        return RemoteResource(url, '"a3"', ics(summary='Changed after report').encode())

    adapter.get_resource = raced_get
    with pytest.raises((InboundFailure, CalDAVError)):
        await service.reconcile(connection, adapter)
    rows = await events_of(sessions, connection.id)
    assert rows[0].summary == 'Dentist' and rows[0].etag == '"a1"'
    after = await state_of(sessions, connection.id)
    assert after.sync_token == before.sync_token and after.last_synced_at == before.last_synced_at


@pytest.mark.parametrize('tokens', [False, True])
async def test_cache_row_identity_survives_unchanged_and_changed_passes(sessions, tokens):
    adapter = FakeAdapter({A: ('"a1"', ics())}, supports_tokens=tokens)
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    original = (await events_of(sessions, connection.id))[0]
    await service.reconcile(connection, adapter)
    assert (await events_of(sessions, connection.id))[0].id == original.id
    adapter.resources[A] = ('"a2"', ics(summary='Edited'))
    adapter.token = 'token-2'
    await service.reconcile(connection, adapter)
    edited = (await events_of(sessions, connection.id))[0]
    assert edited.id == original.id and edited.summary == 'Edited'


async def test_two_completed_initial_reports_cannot_overwrite_newer_cursor(sessions):
    connection = await seed(sessions)
    service = InboundService(sessions)
    winner = FakeAdapter({B: ('"b1"', ics('newer'))})
    stale = FakeAdapter({A: ('"a1"', ics())})
    original_get = stale.get_resource

    async def another_pass_commits(url):
        await service.reconcile(connection, winner)
        return await original_get(url)

    stale.get_resource = another_pass_commits
    with pytest.raises(InboundFailure):
        await service.reconcile(connection, stale)
    assert [row.resource_url for row in await events_of(sessions, connection.id)] == [B]


async def test_failed_batch_does_not_expose_adapter_diagnostics(sessions):
    adapter = FakeAdapter()
    connection = await seed(sessions)
    adapter.fail_sync_collection = CalDAVError('password=SECRET')
    adapter.fail_on_initial = True
    with pytest.raises(CalDAVError):
        await InboundService(sessions).reconcile(connection, adapter)
    assert 'SECRET' not in (await state_of(sessions, connection.id)).last_error


@pytest.mark.parametrize('change_destination', [False, True])
async def test_reconnect_scopes_cache_to_selected_destination(sessions, change_destination):
    from app.calendar_sync.adapter import Calendar
    from app.calendar_sync.connections import ConnectionManager
    from app.calendar_sync.credentials import Credentials
    from test_calendar_outbound import MemoryStore

    adapter = FakeAdapter({A: ('"a1"', ics())})
    connection = await seed(sessions)
    await InboundService(sessions).reconcile(connection, adapter)
    destination = 'https://dav.test/new/' if change_destination else connection.calendar_url

    class Discovery:
        async def discover_calendars(self):
            return [Calendar(destination, 'Selected', True, True)]

    @asynccontextmanager
    async def adapters(server_url, credentials):
        yield Discovery()

    manager = ConnectionManager(MemoryStore(), adapters)
    async with sessions() as session:
        await manager.connect(session, connection.id, Credentials('u', 'p', 'basic'), destination)
    if change_destination:
        assert await events_of(sessions, connection.id) == []
        assert await state_of(sessions, connection.id) is None
    else:
        assert len(await events_of(sessions, connection.id)) == 1
        assert (await state_of(sessions, connection.id)).sync_token == 'token-1'


async def test_expired_token_empty_inventory_removes_all_cached_events(sessions):
    adapter = FakeAdapter({A: ('"a1"', ics())})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    adapter.resources.clear()
    adapter.fail_sync_collection = SyncTokenInvalid('expired')
    adapter.token = 'empty'
    await service.reconcile(connection, adapter)
    assert await events_of(sessions, connection.id) == []
    assert (await state_of(sessions, connection.id)).sync_token == 'empty'


async def test_advertised_report_support_can_explicitly_fall_back_to_listing(sessions):
    from app.calendar_sync.adapter import UnsupportedSyncCollection
    adapter = FakeAdapter({A: ('"a1"', ics())})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    adapter.fail_sync_collection = UnsupportedSyncCollection()
    await service.reconcile(connection, adapter)
    state = await state_of(sessions, connection.id)
    assert state.capability == 'listing' and state.sync_token is None
    assert len(await events_of(sessions, connection.id)) == 1
    adapter.calls.clear()
    await service.reconcile(connection, adapter)
    assert 'sync' not in adapter.calls


async def test_initial_report_without_continuation_token_is_not_committed(sessions):
    adapter = FakeAdapter({A: ('"a1"', ics())})
    connection = await seed(sessions)
    adapter.token = None
    with pytest.raises(CalDAVError):
        await InboundService(sessions).reconcile(connection, adapter)
    state = await state_of(sessions, connection.id)
    assert state.capability == 'unknown' and state.sync_token is None
    assert state.error_state == 'present'
    assert await events_of(sessions, connection.id) == []


async def test_failed_initial_reset_leaves_old_inventory_and_token(sessions):
    adapter = FakeAdapter({A: ('"a1"', ics())})
    connection = await seed(sessions)
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    before = await state_of(sessions, connection.id)
    adapter.resources = {B: ('"b1"', ics('new'))}
    adapter.fail_sync_collection = SyncTokenInvalid('expired')
    adapter.token = 'new'

    async def fail_get(url):
        raise CalDAVError()

    adapter.get_resource = fail_get
    with pytest.raises(CalDAVError):
        await service.reconcile(connection, adapter)
    assert [row.resource_url for row in await events_of(sessions, connection.id)] == [A]
    assert (await state_of(sessions, connection.id)).sync_token == before.sync_token


async def test_pause_during_fetch_does_not_commit_late_cache(sessions):
    from app.models import CalendarConnection
    adapter = FakeAdapter({A: ('"a1"', ics())})
    connection = await seed(sessions)
    original_get = adapter.get_resource

    async def pause(url):
        async with sessions() as session:
            row = await session.get(CalendarConnection, connection.id)
            row.enabled = False
            session.add(row)
            await session.commit()
        return await original_get(url)

    adapter.get_resource = pause
    with pytest.raises(InboundFailure):
        await InboundService(sessions).reconcile(connection, adapter)
    assert await events_of(sessions, connection.id) == []
    assert await state_of(sessions, connection.id) is None


@pytest.mark.parametrize('tokens', [False, True])
async def test_canceled_pass_leaves_no_partial_cache(sessions, tokens):
    import asyncio
    adapter = FakeAdapter({A: ('"a1"', ics()), B: ('"b1"', ics('other'))}, supports_tokens=tokens)
    connection = await seed(sessions)
    original_get = adapter.get_resource

    async def cancel_second(url):
        if url == B:
            raise asyncio.CancelledError()
        return await original_get(url)

    adapter.get_resource = cancel_second
    with pytest.raises(asyncio.CancelledError):
        await InboundService(sessions).reconcile(connection, adapter)
    assert await events_of(sessions, connection.id) == []
    assert await state_of(sessions, connection.id) is None


async def test_equal_clock_ticks_do_not_let_old_listing_replace_newer_cache(sessions, monkeypatch):
    from datetime import datetime
    import app.calendar_sync.inbound as inbound

    monkeypatch.setattr(inbound, 'utc_now', lambda: datetime(2026, 1, 1))
    connection = await seed(sessions)
    service = InboundService(sessions)
    adapter = FakeAdapter({A: ('"a1"', ics())}, supports_tokens=False)
    await service.reconcile(connection, adapter)
    winner = FakeAdapter({B: ('"b1"', ics('winner'))}, supports_tokens=False)
    loser = FakeAdapter({A: ('"a2"', ics(summary='loser'))}, supports_tokens=False)
    original_get = loser.get_resource

    async def winner_commits(url):
        await service.reconcile(connection, winner)
        return await original_get(url)

    loser.get_resource = winner_commits
    with pytest.raises(InboundFailure):
        await service.reconcile(connection, loser)
    assert [row.resource_url for row in await events_of(sessions, connection.id)] == [B]


async def test_flush_then_commit_failure_preserves_cache_and_cursor(sessions, monkeypatch):
    from sqlmodel.ext.asyncio.session import AsyncSession

    connection = await seed(sessions)
    adapter = FakeAdapter({A: ('"a1"', ics())})
    service = InboundService(sessions)
    await service.reconcile(connection, adapter)
    before = await state_of(sessions, connection.id)
    adapter.resources = {B: ('"b1"', ics('new'))}
    adapter.token = 'after'
    original_commit = AsyncSession.commit
    failed = False

    async def fail_after_flush(session):
        nonlocal failed
        await session.flush()
        if not failed:
            failed = True
            raise RuntimeError('injected commit failure')
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, 'commit', fail_after_flush)
    with pytest.raises(RuntimeError, match='injected commit failure'):
        await service.reconcile(connection, adapter)
    assert [row.resource_url for row in await events_of(sessions, connection.id)] == [A]
    after = await state_of(sessions, connection.id)
    assert after.sync_token == before.sync_token and after.last_synced_at == before.last_synced_at
