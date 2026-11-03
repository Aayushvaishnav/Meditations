"""Calendar worker lifetime and startup verification without a server or vault."""

import asyncio

from fastapi.testclient import TestClient

from app import db, main
from app.calendar_sync import queue_worker
from app.models import CalendarConnection


def test_calendar_worker_uses_application_manager_and_drains_before_disposal(monkeypatch):
    events = []
    original_dispose = db.dispose_engine

    async def worker(sessions, manager, *, worker):
        assert sessions is db.get_sessionmaker()
        assert manager is main.app.state.calendar_connection_manager
        events.append('started')
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            assert db.engine_initialized()
            events.append('drained')

    async def dispose():
        assert events == ['started', 'drained']
        events.append('dispose')
        await original_dispose()

    monkeypatch.setattr(queue_worker, 'serve', worker)
    monkeypatch.setattr(db, 'dispose_engine', dispose)
    db.init_engine('sqlite+aiosqlite:///:memory:')
    with TestClient(main.app) as client:
        assert client.get('/api/health').status_code == 200
        assert events == ['started']
    assert events == ['started', 'drained', 'dispose']
    assert not db.engine_initialized()


def test_startup_requires_verification_before_worker_sees_connections(monkeypatch):
    from app.calendar_sync.connections import require_verification_on_startup

    events = []
    checked = asyncio.Event()
    original = require_verification_on_startup

    async def seed_and_verify(session):
        session.add(CalendarConnection(id='restored', server_url='https://calendar.test/',
                    calendar_url='https://calendar.test/events/', state='connected',
                    enabled=True, credential_state='present'))
        await session.commit()
        await original(session)
        events.append('verification-required')

    async def worker(sessions, manager, *, worker):
        try:
            async with sessions() as session:
                connection = await session.get(CalendarConnection, 'restored')
                assert not connection.enabled
                assert connection.state == 'authentication_required'
            events.append('worker-checked')
        finally:
            checked.set()
        await asyncio.Event().wait()

    monkeypatch.setattr('app.calendar_sync.connections.require_verification_on_startup', seed_and_verify)
    monkeypatch.setattr(queue_worker, 'serve', worker)
    db.init_engine('sqlite+aiosqlite:///:memory:')
    with TestClient(main.app) as client:
        assert client.get('/api/health').status_code == 200
        client.portal.call(checked.wait)
        assert events == ['verification-required', 'worker-checked']
