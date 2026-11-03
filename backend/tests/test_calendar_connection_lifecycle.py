"""Credential lifecycle contracts; all remote and OS boundaries are fakes."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app import db
from app.calendar_sync.adapter import AuthenticationError, CalDAVError, Calendar
from app.calendar_sync.connections import ConnectionManager, require_verification_on_startup
from app.calendar_sync.credentials import Credentials, CredentialStoreError
from app.calendar_sync.dependencies import get_connection_manager
from app.main import app
from app.models import CalendarConnection, CalendarLink

BASE = "/api/calendar/connections"
SERVER = "https://calendar.example.test"
SELECTED = SERVER + "/events/"
AUTH = {"username": "username-canary-83c0", "password": "password-canary-87f1", "auth_type": "digest"}


class FakeCredentialStore:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.fail_get = False
        self.fail_put = False
        self.fail_delete = False

    async def get(self, identity):
        self.calls.append(("get", identity))
        if self.fail_get:
            raise CredentialStoreError(AUTH["password"])
        return self.values.get(identity)

    async def put(self, identity, credentials):
        self.calls.append(("put", identity))
        self.values[identity] = credentials
        if self.fail_put:
            raise CredentialStoreError(AUTH["password"])

    async def delete(self, identity):
        self.calls.append(("delete", identity))
        if self.fail_delete:
            raise CredentialStoreError(AUTH["password"])
        self.values.pop(identity, None)


class FakeAdapters:
    def __init__(self):
        self.calls = []
        self.error = None
        self.entered = None
        self.release = None
        self.remote = {"event.ics": b"unchanged remote event"}
        self.calendars = [Calendar(SELECTED, "Events", True, True),
                          Calendar(SERVER + "/readonly/", "Read only", False, True),
                          Calendar(SERVER + "/tasks/", "Tasks", True, False)]

    @asynccontextmanager
    async def __call__(self, server, credentials):
        self.calls.append((server, credentials))
        yield self

    async def discover_calendars(self):
        if self.entered is not None:
            self.entered.set()
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.calendars


@pytest.fixture
def lifecycle(client):
    store, adapters = FakeCredentialStore(), FakeAdapters()
    manager = ConnectionManager(store, adapters)
    app.dependency_overrides[get_connection_manager] = lambda: manager
    try:
        yield client, store, adapters, manager
    finally:
        app.dependency_overrides.pop(get_connection_manager, None)


def draft(client):
    response = client.post(BASE, json={"server_url": SERVER, "calendar_url": SELECTED})
    assert response.status_code == 201
    return response.json()["id"]


def post(client, identity, action, **changes):
    return client.post(f"{BASE}/{identity}/{action}", json={**AUTH, **changes})


def row(client, identity):
    return next(item for item in client.get(BASE).json() if item["id"] == identity)


def connect(client, identity):
    response = post(client, identity, "connect", calendar_url=SELECTED)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "connected"
    return response


def test_discovery_and_connect(lifecycle):
    client, store, adapters, _ = lifecycle
    identity = draft(client)
    assert post(client, identity, "discover").status_code == 200
    assert not store.calls
    assert row(client, identity)["state"] == "disconnected"
    connect(client, identity)
    expected = Credentials(**AUTH)
    assert adapters.calls == [(SERVER, expected), (SERVER, expected)]
    assert store.values == {identity: expected}
    assert client.delete(f"{BASE}/{identity}").status_code == 409


@pytest.mark.parametrize("selection", ["missing", "readonly", "tasks"])
def test_invalid_selection(lifecycle, selection):
    client, store, _, _ = lifecycle
    identity = draft(client)
    assert post(client, identity, "connect", calendar_url=SERVER + f"/{selection}/").status_code == 422
    assert not store.calls


@pytest.mark.parametrize("error,status", [(AuthenticationError, 401), (CalDAVError, 502)])
def test_discovery_errors(lifecycle, error, status):
    client, store, adapters, _ = lifecycle
    identity = draft(client)
    adapters.error = error(AUTH["password"])
    for action in ("discover", "connect"):
        response = post(client, identity, action, **({"calendar_url": SELECTED} if action == "connect" else {}))
        assert response.status_code == status
        assert AUTH["password"] not in response.text
    assert not store.calls
    assert row(client, identity)["state"] == "authentication_required"
    assert not row(client, identity)["enabled"]


def test_replacement(lifecycle):
    client, store, adapters, _ = lifecycle
    identity = draft(client)
    connect(client, identity)
    adapters.error = AuthenticationError("denied")
    assert post(client, identity, "connect", password="rejected", calendar_url=SELECTED).status_code == 401
    assert store.values[identity].password == AUTH["password"]
    adapters.error = None
    assert post(client, identity, "connect", password="replacement", calendar_url=SELECTED).status_code == 200
    assert store.values[identity].password == "replacement"


def test_startup_verification(lifecycle):
    client, store, adapters, _ = lifecycle
    identity = draft(client)
    connect(client, identity)

    async def reset():
        async with db.get_sessionmaker()() as session:
            connection = await session.get(CalendarConnection, identity)
            connection.enabled = True
            session.add(connection)
            await session.commit()
            await require_verification_on_startup(session)

    client.portal.call(reset)
    assert row(client, identity)["state"] == "authentication_required"
    assert not row(client, identity)["enabled"]
    assert client.post(f"{BASE}/{identity}/verify").status_code == 200
    assert adapters.calls[-1][1] == store.values[identity]


@pytest.mark.parametrize("locked,status,state", [(False, 401, "absent"), (True, 503, "present")])
def test_missing_or_locked_store(lifecycle, locked, status, state):
    client, store, _, _ = lifecycle
    identity = draft(client)
    connect(client, identity)
    if locked:
        store.fail_get = True
    else:
        store.values.clear()
    response = client.post(f"{BASE}/{identity}/verify")
    assert response.status_code == status
    assert AUTH["password"] not in response.text
    assert row(client, identity)["credential_state"] == state
    assert row(client, identity)["state"] == "authentication_required"


def test_disconnect_preserves_remote_and_links(lifecycle):
    client, store, adapters, _ = lifecycle
    identity = draft(client)
    connect(client, identity)

    async def seed():
        async with db.get_sessionmaker()() as session:
            session.add(CalendarLink(connection_id=identity, local_block_id="historic", uid="stable", resource_url="event.ics", state="syncing"))
            await session.commit()

    client.portal.call(seed)
    calls = list(adapters.calls)
    store.values.clear()
    for _ in range(2):
        assert client.post(f"{BASE}/{identity}/disconnect").status_code == 200
    links = client.get(f"{BASE}/{identity}/links").json()
    assert len(links) == 1
    assert (links[0]["uid"], links[0]["state"], links[0]["error_state"]) == ("stable", "detached", "present")
    assert adapters.calls == calls
    assert adapters.remote == {"event.ics": b"unchanged remote event"}
    assert client.delete(f"{BASE}/{identity}").status_code == 409


@pytest.mark.parametrize("partial_put", [False, True])
def test_cleanup_recovery(lifecycle, partial_put):
    client, store, _, _ = lifecycle
    identity = draft(client)
    if partial_put:
        store.fail_put = True
        assert post(client, identity, "connect", calendar_url=SELECTED).status_code == 503
        assert identity in store.values
    else:
        connect(client, identity)
        store.fail_delete = True
        assert client.post(f"{BASE}/{identity}/disconnect").status_code == 503
        assert row(client, identity)["state"] == "disconnected"
    assert row(client, identity)["credential_state"] == "removal_pending"
    assert not row(client, identity)["enabled"]
    assert client.delete(f"{BASE}/{identity}").status_code == 409
    assert client.post(f"{BASE}/{identity}/verify").status_code == 409
    assert post(client, identity, "connect", calendar_url=SELECTED).status_code == 409
    store.fail_put = store.fail_delete = False
    assert client.post(f"{BASE}/{identity}/disconnect").status_code == 200
    assert not store.values
    assert row(client, identity)["credential_state"] == "absent"
    assert client.delete(f"{BASE}/{identity}").status_code == 204


@pytest.mark.parametrize("action", ["discover", "connect"])
@pytest.mark.parametrize("field", ["username", "password", "auth_type", "extra"])
@pytest.mark.parametrize("kind", ["missing", "null"])
def test_input_validation(lifecycle, action, field, kind):
    client, store, adapters, _ = lifecycle
    identity = draft(client)
    payload = dict(AUTH)
    if action == "connect":
        payload["calendar_url"] = SELECTED
    if field == "extra":
        payload[field] = None if kind == "null" else "unexpected"
    elif kind == "missing":
        del payload[field]
    else:
        payload[field] = None
    assert client.post(f"{BASE}/{identity}/{action}", json=payload).status_code == 422
    assert not store.calls and not adapters.calls


def test_canaries_absent_from_sqlite_and_responses(lifecycle):
    client, _, _, _ = lifecycle
    identity = draft(client)
    responses = [connect(client, identity), client.get(BASE), client.post(f"{BASE}/{identity}/verify")]

    async def dump():
        async with db.get_engine().connect() as connection:
            names = (await connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")).scalars().all()
            result = []
            for name in names:
                quoted = name.replace('"', '""')
                result.append((name, (await connection.exec_driver_sql(f'SELECT * FROM "{quoted}"')).all()))
            return repr(result)

    persisted = client.portal.call(dump)
    for canary in (AUTH["username"], AUTH["password"]):
        assert canary not in persisted
        assert all(canary not in response.text for response in responses)


def test_deferred_connect_serializes_disconnect():
    asyncio.run(_deferred_connect_serializes_disconnect())


async def _deferred_connect_serializes_disconnect():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    store, adapters = FakeCredentialStore(), FakeAdapters()
    adapters.entered, adapters.release = asyncio.Event(), asyncio.Event()
    manager = ConnectionManager(store, adapters)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(CalendarConnection(id="race", server_url=SERVER, calendar_url=SELECTED))
            await session.commit()
        async with AsyncSession(engine, expire_on_commit=False) as first, AsyncSession(engine, expire_on_commit=False) as second:
            connecting = asyncio.create_task(manager.connect(first, "race", Credentials(**AUTH), SELECTED))
            await adapters.entered.wait()
            disconnecting = asyncio.create_task(manager.disconnect(second, "race"))
            await asyncio.sleep(0)
            assert not disconnecting.done()
            assert not store.calls
            adapters.release.set()
            await connecting
            result = await disconnecting
            assert result.state == "disconnected"
            assert result.credential_state == "absent"
            assert not store.values
            assert store.calls == [("put", "race"), ("delete", "race")]
    finally:
        await engine.dispose()


@pytest.mark.parametrize("payload", [{}, {"calendar_url": None}, {"calendar_url": ""}])
def test_connect_requires_calendar_url(lifecycle, payload):
    client, store, adapters, _ = lifecycle
    identity = draft(client)
    assert post(client, identity, "connect", **payload).status_code == 422
    assert not store.calls and not adapters.calls


def test_portable_export_excludes_credentials(lifecycle):
    from io import BytesIO
    from zipfile import ZipFile

    client, _, _, _ = lifecycle
    identity = draft(client)
    connect(client, identity)
    response = client.post("/api/export")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        for name in archive.namelist():
            content = archive.read(name)
            for canary in (AUTH["username"], AUTH["password"]):
                assert canary.encode() not in content, name
