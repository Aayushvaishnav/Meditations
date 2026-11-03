import asyncio
from contextlib import asynccontextmanager

import pytest

from app import db
from app.calendar_sync.adapter import Calendar
from app.calendar_sync.connections import ConnectionManager
from app.calendar_sync.credentials import Credentials
from app.calendar_sync.dependencies import create_manager
from app.models import CalendarConnection


class BlockingStore:
    def __init__(self):
        self.values = {}
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def put(self, key, value):
        self.values[key] = value
        self.started.set()
        await self.finish.wait()

    async def delete(self, key):
        self.values.pop(key, None)

    async def get(self, key):
        return self.values.get(key)


@asynccontextmanager
async def available_adapter(server_url, credentials):
    class Adapter:
        async def discover_calendars(self):
            return [Calendar('https://calendar.test/events/', 'Events', True, True)]
    yield Adapter()


def test_disconnect_serializes_after_inflight_credential_write():
    async def run():
        db.init_engine('sqlite+aiosqlite:///:memory:')
        try:
            await db.init_db()
            sessions = db.get_sessionmaker()
            async with sessions() as session:
                row = CalendarConnection(server_url='https://calendar.test/',
                                         calendar_url='https://calendar.test/events/')
                session.add(row)
                await session.commit()
            store = BlockingStore()
            manager = ConnectionManager(store, available_adapter)

            async def connect():
                async with sessions() as session:
                    await manager.connect(session, row.id, Credentials('user', 'password', 'basic'), row.calendar_url)

            async def disconnect():
                async with sessions() as session:
                    await manager.disconnect(session, row.id)

            connecting = asyncio.create_task(connect())
            await store.started.wait()
            disconnecting = asyncio.create_task(disconnect())
            store.finish.set()
            await asyncio.gather(connecting, disconnecting)
            assert store.values == {}
            async with sessions() as session:
                row = await session.get(CalendarConnection, row.id)
                assert (row.state, row.credential_state, row.enabled) == ('disconnected', 'absent', False)
        finally:
            await db.dispose_engine()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['cancel', 'commit'])
def test_interrupted_credential_write_remains_recoverable(failure, monkeypatch):
    async def run():
        db.init_engine('sqlite+aiosqlite:///:memory:')
        try:
            await db.init_db()
            sessions = db.get_sessionmaker()
            async with sessions() as session:
                row = CalendarConnection(server_url='https://calendar.test/',
                                         calendar_url='https://calendar.test/events/')
                session.add(row)
                await session.commit()
            store = BlockingStore()
            manager = ConnectionManager(store, available_adapter)
            real_save = manager._save

            async def failing_save(session, connection):
                if failure == 'commit' and connection.credential_state == 'present':
                    raise RuntimeError('injected database commit failure')
                await real_save(session, connection)

            monkeypatch.setattr(manager, '_save', failing_save)

            async def connect():
                async with sessions() as session:
                    await manager.connect(session, row.id, Credentials('user', 'password', 'basic'), row.calendar_url)

            task = asyncio.create_task(connect())
            await store.started.wait()
            if failure == 'cancel':
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                store.finish.set()
                with pytest.raises(RuntimeError, match='commit failure'):
                    await task
            async with sessions() as session:
                saved = await session.get(CalendarConnection, row.id)
                assert saved.credential_state == 'removal_pending'
                assert saved.state == 'authentication_required'
                assert not saved.enabled
            assert row.id in store.values
            async with sessions() as session:
                await manager.disconnect(session, row.id)
            assert store.values == {}
            async with sessions() as session:
                saved = await session.get(CalendarConnection, row.id)
                assert saved.credential_state == 'absent'
        finally:
            await db.dispose_engine()
    asyncio.run(run())


def test_namespace_is_database_scoped_and_memory_is_unique(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.calendar_sync import dependencies

    namespaces = []
    monkeypatch.setattr(dependencies, 'OSCredentialStore', lambda namespace: namespaces.append(namespace))
    first = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/database.db')
    alias = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/./database.db')
    other = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/other.db')
    memory = create_async_engine('sqlite+aiosqlite:///:memory:')
    for engine in (first, alias, other, memory, memory):
        create_manager(engine)
    assert namespaces[0] == namespaces[1]
    assert len(set(namespaces)) == 4
