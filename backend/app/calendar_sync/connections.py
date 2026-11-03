"""Credential-backed connection lifecycle; no outbound event writes."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from weakref import WeakValueDictionary

from sqlmodel import select
from sqlalchemy import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_sync.adapter import AuthenticationError, CalDAVAdapter, CalDAVError, Calendar
from app.calendar_sync.credentials import Credentials, CredentialStore, CredentialStoreError
from app.calendar_sync.transport import open_adapter
from app.models import CalendarConnection, CalendarLink, CalendarInboundEvent, CalendarInboundState
from app.util import utc_now


class ConnectionFailure(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


AdapterFactory = Callable[[str, Credentials], AbstractAsyncContextManager[CalDAVAdapter]]


class ConnectionManager:
    def __init__(self, store: CredentialStore, adapters: AdapterFactory = open_adapter):
        self.store = store
        self.adapters = adapters
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def lock(self, connection_id: str) -> asyncio.Lock:
        return self._locks.setdefault(connection_id, asyncio.Lock())

    async def _load(self, session: AsyncSession, connection_id: str) -> CalendarConnection:
        connection = await session.get(CalendarConnection, connection_id)
        if connection is None:
            raise ConnectionFailure(404, "Calendar connection not found")
        await session.refresh(connection)
        return connection

    async def _save(self, session: AsyncSession, connection: CalendarConnection) -> None:
        connection.updated_at = utc_now()
        session.add(connection)
        await session.commit()
        await session.refresh(connection)

    async def _discover(self, connection: CalendarConnection, credentials: Credentials) -> list[Calendar]:
        try:
            async with self.adapters(connection.server_url, credentials) as adapter:
                return await adapter.discover_calendars()
        except AuthenticationError:
            raise ConnectionFailure(401, "CalDAV authentication or calendar permission was refused") from None
        except CalDAVError:
            raise ConnectionFailure(502, "CalDAV discovery failed; check the server and try again") from None
        except ValueError:
            raise ConnectionFailure(422, "Use HTTPS or loopback HTTP for password authentication") from None

    async def discover(self, session: AsyncSession, connection_id: str,
                       credentials: Credentials) -> list[Calendar]:
        async with self.lock(connection_id):
            connection = await self._load(session, connection_id)
            return await self._discover(connection, credentials)

    @staticmethod
    def _require_calendar(calendars: list[Calendar], selected: str) -> Calendar:
        matches = [calendar for calendar in calendars if calendar.url == selected]
        if len(matches) != 1 or not matches[0].writable or not matches[0].supports_vevent:
            raise ConnectionFailure(422, "Select a discovered writable event calendar")
        return matches[0]

    async def connect(self, session: AsyncSession, connection_id: str,
                      credentials: Credentials, calendar_url: str) -> CalendarConnection:
        async with self.lock(connection_id):
            connection = await self._load(session, connection_id)
            if connection.credential_state == "removal_pending":
                raise ConnectionFailure(409, "Disconnect to finish pending credential cleanup first")
            links = (await session.exec(select(CalendarLink.id).where(
                CalendarLink.connection_id == connection_id,
            ).limit(1))).first()
            if calendar_url != connection.calendar_url and links is not None:
                raise ConnectionFailure(409, "Linked resources prevent changing this calendar destination")
            connection.state = "authentication_required"
            connection.enabled = False
            await self._save(session, connection)
            calendar = self._require_calendar(await self._discover(connection, credentials), calendar_url)
            connection.credential_state = "removal_pending"
            await self._save(session, connection)
            try:
                await self.store.put(connection_id, credentials)
            except CredentialStoreError:
                raise ConnectionFailure(503, "OS credential storage failed; disconnect to finish cleanup before retrying") from None
            connection.credential_state = "present"
            if connection.calendar_url != calendar.url:
                await session.exec(delete(CalendarInboundEvent).where(
                    CalendarInboundEvent.connection_id == connection_id))
                await session.exec(delete(CalendarInboundState).where(
                    CalendarInboundState.connection_id == connection_id))
            connection.calendar_url = calendar.url
            connection.state = "connected"
            await self._save(session, connection)
            return connection

    async def verify(self, session: AsyncSession, connection_id: str) -> CalendarConnection:
        async with self.lock(connection_id):
            connection = await self._load(session, connection_id)
            if connection.credential_state == "removal_pending":
                raise ConnectionFailure(409, "Disconnect to finish pending credential cleanup first")
            connection.state = "authentication_required"
            connection.enabled = False
            await self._save(session, connection)
            if connection.credential_state == "absent":
                raise ConnectionFailure(401, "Supply credentials to connect this calendar")
            try:
                credentials = await self.store.get(connection_id)
            except CredentialStoreError:
                raise ConnectionFailure(503, "OS credential storage is unavailable; unlock it and retry") from None
            if credentials is None:
                connection.credential_state = "absent"
                await self._save(session, connection)
                raise ConnectionFailure(401, "Stored credentials are missing; supply credentials again")
            self._require_calendar(await self._discover(connection, credentials), connection.calendar_url)
            connection.state = "connected"
            await self._save(session, connection)
            return connection

    async def disconnect(self, session: AsyncSession, connection_id: str) -> CalendarConnection:
        async with self.lock(connection_id):
            connection = await self._load(session, connection_id)
            connection.state = "disconnected"
            connection.enabled = False
            needs_cleanup = connection.credential_state != "absent"
            if needs_cleanup:
                connection.credential_state = "removal_pending"
            links = (await session.exec(select(CalendarLink).where(
                CalendarLink.connection_id == connection_id,
            ))).all()
            for link in links:
                if link.state == "syncing":
                    link.error_state = "present"
                    link.last_error = "Remote outcome requires reconciliation after disconnect"
                link.state = "detached"
                link.selection_state = "detached"
                link.updated_at = utc_now()
                session.add(link)
            await self._save(session, connection)
            if needs_cleanup:
                try:
                    await self.store.delete(connection_id)
                except CredentialStoreError:
                    raise ConnectionFailure(503, "Disconnected; OS credentials still require removal. Unlock the store and retry disconnect") from None
                connection.credential_state = "absent"
                await self._save(session, connection)
            return connection

    async def delete_draft(self, session: AsyncSession, connection_id: str) -> None:
        async with self.lock(connection_id):
            connection = await self._load(session, connection_id)
            links = (await session.exec(select(CalendarLink.id).where(
                CalendarLink.connection_id == connection_id,
            ).limit(1))).first()
            if (links is not None or connection.state != "disconnected" or connection.enabled
                    or connection.credential_state != "absent"):
                raise ConnectionFailure(409, "Only an unlinked, disconnected draft without credentials can be removed")
            await session.delete(connection)
            await session.commit()


async def require_verification_on_startup(session: AsyncSession) -> None:
    """Restore/startup cannot vouch for server state; verification is explicit."""
    connections = (await session.exec(select(CalendarConnection))).all()
    for connection in connections:
        connection.enabled = False
        if connection.state == "connected":
            connection.state = "authentication_required"
        connection.updated_at = utc_now()
        session.add(connection)
    await session.commit()
