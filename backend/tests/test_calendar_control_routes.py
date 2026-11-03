"""HTTP controls are strict, local-only until an explicit eligible sync."""
from app.models import CalendarConnection, CalendarLink, Task, TimeBlock
from app import db


def test_public_controls_roundtrip_and_strict_enablement(client):
    from datetime import datetime

    async def seed():
        async with db.get_sessionmaker()() as session:
            connection = CalendarConnection(server_url='https://example.test/',
                calendar_url='https://example.test/calendar/', state='connected',
                credential_state='present')
            task = Task(title='Selected block')
            session.add(connection)
            session.add(task)
            await session.flush()
            block = TimeBlock(task_id=task.id, start_at=datetime(2026, 1, 1, 9),
                              end_at=datetime(2026, 1, 1, 10), timezone='UTC')
            session.add(block)
            await session.commit()
            return connection.id, block.id

    connection, block = client.portal.call(seed)
    root = f'/api/calendar/connections/{connection}'
    assert client.get(root + '/status').json()['last_success_state'] == 'never'
    assert client.patch(root + '/sync', json={'enabled': 'true'}).status_code == 422
    assert client.patch(root + '/sync', json={'enabled': True, 'state': 'connected'}).status_code == 422
    opted = client.post(root + f'/blocks/{block}/opt-in')
    assert opted.status_code == 200
    link = opted.json()
    assert client.get(root + '/status').json()['queued_count'] == 1
    assert client.post(root + '/sync-now').status_code == 409
    assert client.post(root + f'/blocks/{block}/opt-out').json()['desired_action'] == 'delete'
    assert client.post(root + f'/links/{link["id"]}/detach').json()['state'] == 'detached'
    assert client.get(root + '/status').json()['detached_count'] == 1
    assert client.post(root + f'/blocks/{block}/opt-in').status_code == 409
    assert client.patch(root + '/sync', json={'enabled': True}).json()['enabled'] is True
    assert client.patch(root + '/sync', json={'enabled': False}).json()['enabled'] is False


def test_missing_public_resources_return_404(client):
    root = '/api/calendar/connections/missing'
    for path in ['/status']:
        assert client.get(root + path).status_code == 404
    assert client.patch(root + '/sync', json={'enabled': False}).status_code == 404
    for path in ['/sync-now', '/blocks/block/opt-in', '/blocks/block/opt-out', '/links/link/detach']:
        assert client.post(root + path).status_code == 404
