"""Atomic inbound batches; remote events never acquire local task authority."""
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_import.parser import CalendarImportError, parse_calendar
from app.calendar_sync.adapter import (
    AuthenticationError, CalDAVAdapter, CalDAVError, ProtocolError, RemoteResource,
    SyncTokenInvalid, UnsupportedSyncCollection,
)
from app.calendar_sync.credentials import CredentialStoreError
from app.models import CalendarConnection, CalendarInboundEvent, CalendarInboundState
from app.util import utc_now

AdapterFactory = Callable[[CalendarConnection], AbstractAsyncContextManager[CalDAVAdapter]]


@dataclass(frozen=True)
class InboundOutcome:
    connection_id: str
    capability: str
    fetched: int
    removed: int
    rebuilt: bool


class InboundFailure(Exception):
    """The batch could not commit; cache and cursor stay unchanged."""


class SupersededBatch(InboundFailure):
    """A newer connection or reconciliation state won; do not label it failed."""


def _parse_resource(content: str, *, connection_id: str, resource_url: str,
                    etag: str) -> CalendarInboundEvent:
    event = CalendarInboundEvent(connection_id=connection_id, resource_url=resource_url,
                                 etag=etag, content=content, component_state='unparsable')
    try:
        parsed = parse_calendar(content)
    except CalendarImportError:
        return event
    if len(parsed.events) != 1:
        return event
    values = parsed.events[0]
    event.identity = values.identity
    event.uid = values.uid
    event.summary = values.summary
    event.component = values.component
    event.component_index = values.component_index
    event.component_state = 'stored'
    return event


def _fetched(resource: RemoteResource, connection_id: str, url: str, etag: str) -> CalendarInboundEvent:
    if resource.url != url or resource.etag != etag:
        raise InboundFailure('Remote resource changed during reconciliation')
    if not isinstance(resource.payload, bytes):
        raise ProtocolError('Calendar GET requires a byte payload')
    try:
        content = resource.payload.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ProtocolError('Calendar resource is not UTF-8') from exc
    return _parse_resource(content, connection_id=connection_id, resource_url=url, etag=etag)


async def _state(session: AsyncSession, connection_id: str) -> CalendarInboundState | None:
    return (await session.exec(select(CalendarInboundState).where(
        CalendarInboundState.connection_id == connection_id))).first()


def _connection_matches(connection: CalendarConnection):
    return (
        CalendarConnection.id == connection.id,
        CalendarConnection.calendar_url == connection.calendar_url,
        CalendarConnection.updated_at == connection.updated_at,
        CalendarConnection.state == 'connected',
        CalendarConnection.enabled == True,  # noqa: E712
        CalendarConnection.credential_state == 'present',
    )


def _cursor(state: CalendarInboundState | None) -> tuple:
    if state is None:
        return ('absent',)
    return (state.id, state.revision, state.capability, state.sync_token)


async def _record_error(sessions, connection: CalendarConnection, expected: tuple,
                        *, authentication: bool = False) -> None:
    async with sessions() as session:
        # Acquire SQLite's writer lock before comparing snapshots
        result = await session.exec(update(CalendarConnection).where(
            *_connection_matches(connection)).values(enabled=True))
        if result.rowcount != 1 or _cursor(await _state(session, connection.id)) != expected:
            return
        state = await _state(session, connection.id)
        state = state or CalendarInboundState(connection_id=connection.id)
        state.error_state = 'present'
        state.last_error = ('Verify this calendar connection before refreshing appointments'
                            if authentication else 'Calendar refresh failed; the last successful cache is retained')
        session.add(state)
        if authentication:
            await session.exec(update(CalendarConnection).where(
                *_connection_matches(connection)).values(
                    state='authentication_required', enabled=False, updated_at=utc_now()))
        await session.commit()


class InboundService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def reconcile(self, connection: CalendarConnection, adapter: CalDAVAdapter) -> InboundOutcome:
        """Caller serializes network work with the connection manager's lifecycle lock."""
        async with self.sessions() as session:
            state = await _state(session, connection.id)
            expected = _cursor(state)
            cached = {row.resource_url: row for row in (await session.exec(
                select(CalendarInboundEvent).where(
                    CalendarInboundEvent.connection_id == connection.id))).all()}
        try:
            capability = state.capability if state is not None else 'unknown'
            token = state.sync_token if state is not None else None
            if capability == 'unknown':
                capability = ('sync_token' if await adapter.supports_sync_collection(connection.calendar_url)
                              else 'listing')
            full = True
            next_token = None
            if capability == 'sync_token':
                try:
                    try:
                        report = await adapter.sync_collection(connection.calendar_url, token)
                    except SyncTokenInvalid:
                        if token is None:
                            raise
                        token = None
                        report = await adapter.sync_collection(connection.calendar_url, None)
                    if not report.token:
                        raise ProtocolError('Sync report requires a continuation token')
                    next_token = report.token
                    full = token is None
                    versions = {change.url: change.etag for change in report.changes}
                except UnsupportedSyncCollection:
                    capability = 'listing'
            if capability == 'listing':
                listing = await adapter.list_resources(connection.calendar_url)
                versions = {resource.url: resource.etag for resource in listing}
            fetches = {}
            for url, etag in versions.items():
                if etag is not None and (url not in cached or cached[url].etag != etag):
                    fetches[url] = _fetched(await adapter.get_resource(url), connection.id, url, etag)
            removed = {url for url in cached
                       if (full and url not in versions) or (url in versions and versions[url] is None)}
            async with self.sessions() as session:
                result = await session.exec(update(CalendarConnection).where(
                    *_connection_matches(connection)).values(enabled=True))
                current = await _state(session, connection.id)
                if result.rowcount != 1 or _cursor(current) != expected:
                    raise SupersededBatch('Reconciliation snapshot is no longer current')
                if removed:
                    await session.exec(delete(CalendarInboundEvent).where(
                        CalendarInboundEvent.connection_id == connection.id,
                        CalendarInboundEvent.resource_url.in_(removed)))
                for url, incoming in fetches.items():
                    previous = cached.get(url)
                    if previous is not None:
                        incoming.id = previous.id
                    # merge updates existing resource identities without remount churn
                    await session.merge(incoming)
                current = current or CalendarInboundState(connection_id=connection.id)
                current.revision += 1
                current.capability = capability
                current.sync_token = next_token
                current.last_synced_at = utc_now()
                current.error_state = 'none'
                current.last_error = None
                session.add(current)
                await session.commit()
            return InboundOutcome(connection.id, capability, len(fetches), len(removed), full)
        except SupersededBatch:
            raise
        except (CalDAVError, InboundFailure) as exc:
            await _record_error(self.sessions, connection, expected,
                                authentication=isinstance(exc, AuthenticationError))
            raise


async def reconcile_connections(
    sessions: async_sessionmaker[AsyncSession], adapters: AdapterFactory,
    *, connection_id: str | None = None,
) -> None:
    """Called under each connection lifecycle lock by the queue worker."""
    async with sessions() as session:
        query = select(CalendarConnection).where(
            CalendarConnection.state == 'connected', CalendarConnection.enabled == True,  # noqa: E712
            CalendarConnection.credential_state == 'present')
        if connection_id is not None:
            query = query.where(CalendarConnection.id == connection_id)
        connections = (await session.exec(query.order_by(CalendarConnection.id))).all()
    for connection in connections:
        async with sessions() as session:
            expected = _cursor(await _state(session, connection.id))
        try:
            async with adapters(connection) as adapter:
                await InboundService(sessions).reconcile(connection, adapter)
        except SupersededBatch:
            continue
        except (CalDAVError, InboundFailure, CredentialStoreError, ValueError) as exc:
            await _record_error(sessions, connection, expected,
                                authentication=isinstance(exc, AuthenticationError))
