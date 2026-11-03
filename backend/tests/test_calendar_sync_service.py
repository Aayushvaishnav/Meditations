import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app import db
from app.calendar_sync.adapter import AuthenticationError
from app.calendar_sync.service import LinkSnapshot, inspect_links
from app.calendar_sync.worker import inspect_once
from app.models import CalendarConnection, CalendarLink


class FakeAdapter:
    def __init__(self, resources=(), error=None, before_listing=None):
        self.resources = resources
        self.error = error
        self.before_listing = before_listing
        self.calls = []

    async def list_resources(self, url):
        self.calls.append(url)
        if self.before_listing:
            await self.before_listing()
        if self.error:
            raise self.error
        return self.resources


@pytest.mark.parametrize("versions,outcomes", [
    ([('a', 'v1'), ('b', 'v3')], ['unchanged', 'changed']),
    ([], ['missing', 'missing']),
])
def test_inspect_only_linked_resources(versions, outcomes):
    adapter = FakeAdapter([SimpleNamespace(url=url, etag=etag) for url, etag in versions])
    links = [LinkSnapshot('1', 'a', 'v1', 1), LinkSnapshot('2', 'b', 'v2', 1)]
    result = asyncio.run(inspect_links(adapter, 'calendar/', links))
    assert [item.outcome for item in result] == outcomes
    assert adapter.calls == ['calendar/']


def test_incomplete_listing_never_reports_deletion():
    async def run():
        with pytest.raises(RuntimeError, match='interrupted'):
            await inspect_links(FakeAdapter(error=RuntimeError('interrupted')), 'calendar/',
                                [LinkSnapshot('1', 'a', 'v1', 1)])
    asyncio.run(run())


@pytest.mark.parametrize('scenario', ['unchanged', 'changed', 'missing', 'auth', 'network',
                                       'paused', 'disconnected', 'edited', 'detached',
                                       'pause_during', 'disconnect_during', 'stale_auth'])
def test_worker_only_inspects_and_preserves_newer_state(scenario):
    async def run():
        db.init_engine('sqlite+aiosqlite:///:memory:')
        try:
            await db.init_db()
            sessions = db.get_sessionmaker()
            async with sessions() as session:
                connection = CalendarConnection(server_url='https://calendar.test/',
                                                calendar_url='https://calendar.test/events/',
                                                state='disconnected' if scenario == 'disconnected' else 'connected',
                                                enabled=scenario != 'paused')
                session.add(connection)
                await session.flush()
                link = CalendarLink(connection_id=connection.id, local_block_id='deleted-local-block',
                                    uid='stable-uid', resource_url='https://calendar.test/events/a.ics',
                                    etag='"v1"', state='synced', acknowledged_revision=1)
                session.add(link)
                await session.commit()

            async def concurrent_change():
                if scenario in {'pause_during', 'disconnect_during', 'stale_auth'}:
                    from app.util import utc_now
                    async with sessions() as session:
                        row = await session.get(CalendarConnection, connection.id)
                        row.enabled = scenario != 'pause_during'
                        row.state = 'connected' if scenario == 'pause_during' else 'disconnected'
                        row.updated_at = utc_now()
                        session.add(row)
                        await session.commit()
                    return
                if scenario not in {'edited', 'detached'}:
                    return
                async with sessions() as session:
                    row = await session.get(CalendarLink, link.id)
                    row.state = 'pending' if scenario == 'edited' else 'detached'
                    row.local_revision += 1
                    session.add(row)
                    await session.commit()

            resources = [] if scenario == 'missing' else [SimpleNamespace(
                url=link.resource_url, etag='"v1"' if scenario == 'unchanged' else '"v2"')]
            error = AuthenticationError('authentication required') if scenario in {'auth', 'stale_auth'} else (
                RuntimeError('network failure') if scenario == 'network' else None)
            adapter = FakeAdapter(resources, error, concurrent_change)

            @asynccontextmanager
            async def adapters(_connection):
                yield adapter

            if scenario == 'network':
                with pytest.raises(RuntimeError, match='network'):
                    await inspect_once(sessions, adapters)
            else:
                await inspect_once(sessions, adapters)
            async with sessions() as session:
                saved = await session.get(CalendarLink, link.id)
                expected = {'changed': 'conflict', 'missing': 'conflict',
                            'edited': 'pending', 'detached': 'detached'}.get(scenario, 'synced')
                assert saved.state == expected
                assert saved.etag == '"v1"'
                assert saved.uid == 'stable-uid'
                connection = await session.get(CalendarConnection, connection.id)
                assert (connection.state == 'authentication_required') == (scenario == 'auth')
                if scenario in {'paused', 'disconnected'}:
                    assert not adapter.calls
                assert len((await session.exec(select(CalendarLink))).all()) == 1
        finally:
            await db.dispose_engine()
    asyncio.run(run())


@pytest.mark.parametrize('inventory', ['empty', 'error', 'duplicate', 'not_collection', 'valid_empty'])
def test_real_adapter_rejects_incomplete_inventory_before_persisting_conflict(inventory):
    import httpx
    from app.calendar_sync.adapter import CalDAVAdapter, ProtocolError

    collection = ('<d:response><d:href>/events/</d:href><d:propstat><d:prop>'
                  '<d:resourcetype><d:collection/></d:resourcetype></d:prop>'
                  '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>')
    contents = {
        'empty': '',
        'error': collection + '<d:error><d:number-of-matches-within-limits/></d:error>',
        'duplicate': collection + collection,
        'not_collection': collection.replace('<d:collection/>', ''),
        'valid_empty': collection,
    }
    xml = f'<d:multistatus xmlns:d="DAV:">{contents[inventory]}</d:multistatus>'

    async def run():
        db.init_engine('sqlite+aiosqlite:///:memory:')
        try:
            await db.init_db()
            sessions = db.get_sessionmaker()
            async with sessions() as session:
                connection = CalendarConnection(server_url='https://calendar.test/',
                                                calendar_url='https://calendar.test/events/',
                                                state='connected', enabled=True)
                session.add(connection)
                await session.flush()
                link = CalendarLink(connection_id=connection.id, local_block_id='block', uid='uid',
                                    resource_url='https://calendar.test/events/a.ics',
                                    etag='"v1"', state='synced', acknowledged_revision=1)
                session.add(link)
                await session.commit()

            @asynccontextmanager
            async def adapters(_connection):
                transport = httpx.MockTransport(lambda request: httpx.Response(207, text=xml))
                async with httpx.AsyncClient(transport=transport) as client:
                    yield CalDAVAdapter('https://calendar.test/', client)

            if inventory == 'valid_empty':
                await inspect_once(sessions, adapters)
            else:
                with pytest.raises(ProtocolError):
                    await inspect_once(sessions, adapters)
            async with sessions() as session:
                saved = await session.get(CalendarLink, link.id)
                assert saved.state == ('conflict' if inventory == 'valid_empty' else 'synced')
                assert saved.etag == '"v1"'
        finally:
            await db.dispose_engine()
    asyncio.run(run())
