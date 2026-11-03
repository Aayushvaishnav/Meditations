import pytest


def test_drafts_are_local_and_disabled(client):
    response = client.post('/api/calendar/connections', json={
        'server_url': 'https://calendar.example/dav/',
        'calendar_url': 'https://calendar.example/dav/events/',
    })
    assert response.status_code == 201
    draft = response.json()
    assert draft['state'] == 'disconnected'
    assert draft['enabled'] is False
    assert client.get(f"/api/calendar/connections/{draft['id']}/links").json() == []
    assert client.get('/api/calendar/connections').json() == [draft]
    assert client.delete(f"/api/calendar/connections/{draft['id']}").status_code == 204
    assert client.get('/api/calendar/connections').json() == []
    assert client.delete(f"/api/calendar/connections/{draft['id']}").status_code == 404


@pytest.mark.parametrize('changes', [
    {'server_url': 'https://user:secret@calendar.example/dav/'},
    {'calendar_url': 'https://other.example/events/'},
    {'calendar_url': 'https://calendar.example/events/?password=secret'},
    {'calendar_url': 'https://calendar.example/events/#fragment'},
    {'calendar_url': 'https://calendar.example/events'},
    {'calendar_url': 'file:///tmp/events/'},
    {'calendar_url': 'https://calendar.example:bad/events/'},
    {'calendar_url': 'https://calendar.example/events/\n'},
    {'enabled': True}, {'state': 'connected'}, {'password': 'secret'},
])
def test_draft_validation_never_enables_network(client, changes):
    payload = {'server_url': 'https://calendar.example/dav/',
               'calendar_url': 'https://calendar.example/events/'} | changes
    assert client.post('/api/calendar/connections', json=payload).status_code == 422
    assert client.get('/api/calendar/connections').json() == []


def test_unknown_connection_has_no_link_listing(client):
    assert client.get('/api/calendar/connections/missing/links').status_code == 404


def test_task_crud_does_not_require_calendar_server(client, monkeypatch):
    from app.calendar_sync.adapter import CalDAVAdapter

    async def unreachable(*args, **kwargs):
        raise AssertionError('Local CRUD must not contact CalDAV')

    monkeypatch.setattr(CalDAVAdapter, '_request', unreachable)
    client.post('/api/calendar/connections', json={
        'server_url': 'http://127.0.0.1:9/',
        'calendar_url': 'http://127.0.0.1:9/events/',
    })
    created = client.post('/api/tasks', json={'title': 'Offline task'})
    assert created.status_code == 201
    task_id = created.json()['id']
    assert client.patch(f'/api/tasks/{task_id}', json={'title': 'Still local'}).status_code == 200
    assert client.get(f'/api/tasks/{task_id}').json()['title'] == 'Still local'
    assert client.delete(f'/api/tasks/{task_id}').status_code == 204


@pytest.mark.parametrize('reason', ['linked', 'connected', 'enabled'])
def test_removal_cannot_discard_links_or_active_connection(client, reason):
    from app import db
    from app.models import CalendarConnection, CalendarLink

    created = client.post('/api/calendar/connections', json={
        'server_url': 'https://calendar.example/',
        'calendar_url': 'https://calendar.example/events/',
    }).json()

    async def prepare():
        async with db.get_sessionmaker()() as session:
            connection = await session.get(CalendarConnection, created['id'])
            if reason == 'linked':
                session.add(CalendarLink(connection_id=connection.id, local_block_id='deleted-block',
                                         uid='stable', resource_url='https://calendar.example/events/a.ics'))
            elif reason == 'connected':
                connection.state = 'connected'
                session.add(connection)
            else:
                connection.enabled = True
                session.add(connection)
            await session.commit()

    client.portal.call(prepare)
    assert client.delete(f"/api/calendar/connections/{created['id']}").status_code == 409
    assert len(client.get('/api/calendar/connections').json()) == 1
    links = client.get(f"/api/calendar/connections/{created['id']}/links").json()
    assert len(links) == (1 if reason == 'linked' else 0)
