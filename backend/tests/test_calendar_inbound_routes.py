"""Inbound overlay projection and public routes; read-only with respect to tasks."""
from app import db
from app.models import CalendarConnection


def ics(uid='external-1', summary='Dentist', start='20260115T090000Z', end='20260115T100000Z'):
    return (f'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\n'
            f'DTSTAMP:20260101T000000Z\r\nSUMMARY:{summary}\r\n'
            f'DTSTART:{start}\r\nDTEND:{end}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')


def seed(client):
    from app.calendar_sync.inbound import _parse_resource

    async def create():
        async with db.get_sessionmaker()() as session:
            connection = CalendarConnection(
                server_url='https://dav.test/', calendar_url='https://dav.test/cal/',
                state='connected', enabled=True, credential_state='present')
            session.add(connection)
            await session.flush()
            session.add(_parse_resource(ics(), connection_id=connection.id,
                                        resource_url='https://dav.test/cal/a.ics', etag='"v1"'))
            session.add(_parse_resource('garbage', connection_id=connection.id,
                                        resource_url='https://dav.test/cal/b.ics', etag='"v2"'))
            session.add(_parse_resource(
                ics().replace('DTEND:20260115T100000Z\r\n', 'DTEND:20260115T100000Z\r\nRRULE:FREQ=DAILY\r\n'),
                connection_id=connection.id, resource_url='https://dav.test/cal/c.ics', etag='"v3"'))
            await session.commit()
            await session.refresh(connection)
            return connection.id

    return client.portal.call(create)


def test_overlay_places_timed_events_and_reports_reasons(client):
    connection = seed(client)
    response = client.get(f'/api/calendar/connections/{connection}/inbound/overlay')
    assert response.status_code == 200
    body = response.json()
    assert body['connection_id'] == connection
    assert [item['uid'] for item in body['items']] == ['external-1']
    interval = body['items'][0]['interval']
    assert interval['kind'] == 'timed'
    assert interval['start'] == '2026-01-15T09:00:00Z'
    assert interval['end'] == '2026-01-15T10:00:00Z'
    assert {item['reason'] for item in body['unplaced']} == {'unparsable_resource', 'recurrence'}


def test_overlay_requires_existing_connection(client):
    assert client.get('/api/calendar/connections/missing/inbound/overlay').status_code == 404


def test_overlay_of_empty_cache(client):
    async def create():
        async with db.get_sessionmaker()() as session:
            connection = CalendarConnection(
                server_url='https://dav.test/x/', calendar_url='https://dav.test/x/',
                state='disconnected', enabled=False, credential_state='absent')
            session.add(connection)
            await session.commit()
            await session.refresh(connection)
            return connection.id

    connection_id = client.portal.call(create)
    body = client.get(f'/api/calendar/connections/{connection_id}/inbound/overlay').json()
    assert body == {'connection_id': connection_id, 'items': [], 'unplaced': []}


def test_resume_endpoint_runs_one_pass(client, monkeypatch):
    from app.calendar_sync import queue_worker
    called = []

    async def fake_run_once(self, connection_id=None):
        called.append(connection_id)

    monkeypatch.setattr(queue_worker.QueueWorker, 'run_once', fake_run_once)
    response = client.post('/api/calendar/connections/resume')
    assert response.status_code == 204
    assert called == [None]
