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
    assert body == {'connection_id': connection_id, 'items': [], 'unplaced': [],
                    'reconciliation': {'state': 'never', 'capability': 'unknown',
                                       'last_synced_at': None, 'last_error': None}}


def test_resume_endpoint_runs_one_pass(client, monkeypatch):
    from app.calendar_sync import queue_worker
    called = []

    async def fake_run_once(self, connection_id=None):
        called.append(connection_id)

    monkeypatch.setattr(queue_worker.QueueWorker, 'run_once', fake_run_once)
    response = client.post('/api/calendar/connections/resume')
    assert response.status_code == 204
    assert called == [None]


def test_resume_local_only_does_not_access_the_credential_store(client, monkeypatch):
    async def forbidden(_id):
        raise AssertionError('local-only resume must not contact the vault')

    monkeypatch.setattr(client.app.state.calendar_connection_manager.store, 'get', forbidden)
    assert client.post('/api/calendar/connections/resume').status_code == 204


def test_inbound_failure_status_preserves_last_successful_check(client):
    from datetime import datetime
    from app.models import CalendarInboundState
    connection = seed(client)

    async def mark_failure():
        async with db.get_sessionmaker()() as session:
            session.add(CalendarInboundState(connection_id=connection, capability='listing',
                last_synced_at=datetime(2026, 1, 1), error_state='present',
                last_error='Calendar refresh failed; the last successful cache is retained'))
            await session.commit()

    client.portal.call(mark_failure)
    body = client.get(f'/api/calendar/connections/{connection}/inbound/overlay').json()
    assert len(body['items']) == 1
    assert body['reconciliation']['state'] == 'error'
    assert body['reconciliation']['last_synced_at'] == '2026-01-01T00:00:00'
