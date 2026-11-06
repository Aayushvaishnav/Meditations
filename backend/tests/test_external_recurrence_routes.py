"""Windowed HTTP projections; no network or user database access."""
import pytest

from app import db
from app.models import CalendarConnection, CalendarInboundEvent
from app.calendar_sync.inbound import _parse_resource
from test_calendar_import import BASE, calendar, upload

WINDOW = '?start=2026-03-07&end=2026-03-11'
MASTER = 'UID:series\r\nDTSTART:20260307T090000Z\r\nRRULE:FREQ=DAILY;COUNT=4'


def test_import_refresh_isolation_and_no_mutation(client):
    content = calendar(MASTER)
    source = upload(client, content).json()['source_id']
    other = upload(client, content).json()['source_id']
    url = f'{BASE}/{source}/overlay'
    original = client.get(url + WINDOW).json()
    assert len(original['items']) == 4
    assert client.get(url).json()['unplaced'][0]['reason'] == 'recurrence'
    upload(client, calendar(MASTER + '\r\nSUMMARY:Updated'), source)
    refreshed = client.get(url + WINDOW).json()
    assert [i['id'] for i in refreshed['items']] == [i['id'] for i in original['items']]
    assert all(i['summary'] == 'Updated' for i in refreshed['items'])
    assert all(i['summary'] == '' for i in client.get(f'{BASE}/{other}/overlay' + WINDOW).json()['items'])
    assert client.get('/api/tasks').json() == []
    assert client.get('/api/time-blocks').json() == []


@pytest.mark.parametrize('query', ['?start=2026-03-01', '?end=2026-03-01', '?start=no&end=2026-03-01', '?start=2026-03-01&end=2026-03-01', '?start=2026-03-01&end=2028-03-01'])
def test_api_window_validation(client, query):
    source = upload(client, calendar(MASTER)).json()['source_id']
    assert client.get(f'{BASE}/{source}/overlay' + query).status_code == 422


def test_live_retained_multi_component_resource_and_removal(client):
    content = calendar(MASTER,
        'UID:series\r\nRECURRENCE-ID:20260308T090000Z\r\nDTSTART:20260309T120000Z',
        'UID:series\r\nRECURRENCE-ID:20260309T090000Z\r\nSTATUS:CANCELLED')

    async def create():
        async with db.get_sessionmaker()() as session:
            connection = CalendarConnection(server_url='https://dav.test/', calendar_url='https://dav.test/cal/',
                                            state='connected', enabled=True, credential_state='present')
            session.add(connection)
            await session.flush()
            event = _parse_resource(content, connection_id=connection.id,
                                    resource_url='https://dav.test/cal/a.ics', etag='v1')
            session.add(event)
            await session.commit()
            return connection.id, event.id

    connection, event_id = client.portal.call(create)
    url = f'/api/calendar/connections/{connection}/inbound/overlay'
    body = client.get(url + WINDOW).json()
    assert body['unplaced'] == []
    assert [i['interval']['start'] for i in body['items']] == ['2026-03-07T09:00:00Z', '2026-03-09T12:00:00Z', '2026-03-10T09:00:00Z']
    assert client.get(url).json()['unplaced'][0]['reason'] == 'unparsable_resource'
    assert client.get(url + '?start=2026-03-01').status_code == 422

    async def remove():
        async with db.get_sessionmaker()() as session:
            event = await session.get(CalendarInboundEvent, event_id)
            await session.delete(event)
            await session.commit()

    client.portal.call(remove)
    assert client.get(url + WINDOW).json()['items'] == []


def test_custom_snapshot_timezone_isolation(client):
    from test_calendar_overlay import custom_zone
    event = 'UID:a\r\nDTSTART;TZID=Overlay/Window:20260307T120000\r\nRRULE:FREQ=DAILY;COUNT=2'
    sources = [upload(client, calendar(event, extra=custom_zone('Overlay/Window', offset))).json()['source_id']
               for offset in ['+0530', '+0200']]
    for source, clock in zip(sources, ['06:30:00Z', '10:00:00Z']):
        body = client.get(f'{BASE}/{source}/overlay' + WINDOW).json()
        assert not body['unplaced']
        assert all(i['interval']['start'].endswith(clock) for i in body['items'])


def test_live_component_diagnostic_and_standalone_ids_are_unique(client):
    content = calendar('UID:a\r\nDTSTART:20260308T090000Z', 'UID:b\r\nDTSTART:20260308T120000Z',
                       'UID:c\r\nDTSTART:20260308T090000Z\r\nRRULE:FREQ=HOURLY',
                       'UID:c\r\nRECURRENCE-ID:20260309T090000Z\r\nSTATUS:CANCELLED')

    async def create():
        async with db.get_sessionmaker()() as session:
            connection = CalendarConnection(server_url='https://dav.test/', calendar_url='https://dav.test/multi/',
                                            state='connected', enabled=True, credential_state='present')
            session.add(connection)
            await session.flush()
            session.add(_parse_resource(content, connection_id=connection.id,
                                       resource_url='https://dav.test/multi/a.ics', etag='v1'))
            await session.commit()
            return connection.id

    connection = client.portal.call(create)
    body = client.get(f'/api/calendar/connections/{connection}/inbound/overlay' + WINDOW).json()
    assert len(body['items']) == 2
    assert len(body['unplaced']) == 2
    ids = [i['id'] for i in body['items'] + body['unplaced']]
    assert len(set(ids)) == 4
