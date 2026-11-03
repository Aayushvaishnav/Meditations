"""Capability-aware inbound reconciliation of external CalDAV events.

Read-only with respect to tasks, deadlines, focus, and scores: remote events are
cached for an overlay projection and never modify local task data. Durable state
advances only after the relevant listing/change batch completes; a failed batch
leaves the previous cache and sync token intact.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_import.parser import CalendarImportError, parse_calendar
from app.calendar_sync.adapter import (
    AuthenticationError,
    CalDAVAdapter,
    CalDAVError,
    SyncTokenInvalid,
)
from app.models import CalendarConnection, CalendarInboundEvent, CalendarInboundState
from app.util import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundOutcome:
    connection_id: str
    capability: str  # sync_token | listing
    fetched: int
    removed: int
    rebuilt: bool


class InboundFailure(Exception):
    """Reconciliation could not complete; durable state was left untouched."""


def _text(payload) -> str:
    return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)


def _parse_resource(content: str, *, connection_id: str, resource_url: str, etag: str,
                    ) -> CalendarInboundEvent:
    """Cache one remote resource; text is retained even when it cannot be projected."""
    event = CalendarInboundEvent(
        connection_id=connection_id, resource_url=resource_url, etag=etag,
        content=content, component_state="unparsable",
    )
    try:
        parsed = parse_calendar(content)
        if len(parsed.events) != 1:
            return event
        values = parsed.events[0]
    except (CalendarImportError, ValueError):
        return event
    event.identity = values.identity
    event.uid = values.uid
    event.summary = values.summary
    event.component = values.component
    event.component_index = values.component_index
    event.component_state = "stored"
    return event


async def _state_row(session: AsyncSession, connection_id: str) -> CalendarInboundState:
    state = (await session.exec(select(CalendarInboundState).where(
        CalendarInboundState.connection_id == connection_id))).first()
    if state is None:
        state = CalendarInboundState(connection_id=connection_id)
        session.add(state)
        await session.flush()
    return state


class InboundService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def _cached_etags(self, connection_id: str) -> dict[str, str]:
        async with self.sessions() as session:
            rows = (await session.exec(select(CalendarInboundEvent).where(
                CalendarInboundEvent.connection_id == connection_id))).all()
        return {row.resource_url: row.etag for row in rows}

    async def reconcile(self, connection: CalendarConnection, adapter: CalDAVAdapter) -> InboundOutcome:
        """Bring the inbound cache up to date; one atomic commit per completed batch."""
        try:
            return await self._reconcile(connection, adapter)
        except (CalDAVError, InboundFailure) as exc:
            # Durable state is untouched; record the failure for status surfaces
            async with self.sessions() as session:
                state = await _state_row(session, connection.id)
                state.error_state = "present"
                state.last_error = str(exc)[:2000]
                session.add(state)
                await session.commit()
            raise

    async def _reconcile(self, connection: CalendarConnection, adapter: CalDAVAdapter) -> InboundOutcome:
        async with self.sessions() as session:
            state = await _state_row(session, connection.id)
            persisted_capability = state.capability
        if persisted_capability == "unknown":
            # Persisted capability stays 'unknown' until a completed pass provides a token
            capability = ("sync_token"
                          if await adapter.supports_sync_collection(connection.calendar_url)
                          else "listing")
        else:
            capability = persisted_capability
        if capability == "sync_token":
            token = state.sync_token if persisted_capability == "sync_token" else None
            try:
                return await self._sync_token_pass(connection, adapter, token)
            except SyncTokenInvalid:
                logger.warning("Stored sync token rejected; rebuilding the inbound cache")
                # An initial sync-collection report replaces the expired token atomically
                return await self._sync_token_pass(connection, adapter, None)
        return await self._rebuild(connection, adapter, capability="listing")

    async def _sync_token_pass(self, connection: CalendarConnection, adapter: CalDAVAdapter,
                                token: str | None) -> InboundOutcome:
        result = await adapter.sync_collection(connection.calendar_url, token)
        if result.token is None:
            # No continuation token: fall back to complete-listing reconciliation
            return await self._rebuild(connection, adapter, capability="sync_token")
        cached = await self._cached_etags(connection.id)
        fetches, removes = {}, []
        for change in result.changes:
            if change.url == connection.calendar_url:
                continue
            if change.etag is None:
                removes.append(change.url)
            elif cached.get(change.url) != change.etag:
                resource = await adapter.get_resource(change.url)
                fetches[change.url] = _parse_resource(
                    _text(resource.payload),
                    connection_id=connection.id, resource_url=change.url, etag=change.etag)
        async with self.sessions() as session:
            state = await _state_row(session, connection.id)
            if state.capability not in ("unknown", "sync_token"):
                raise InboundFailure("Inbound capability changed during reconciliation")
            if removes:
                await session.exec(delete(CalendarInboundEvent).where(
                    CalendarInboundEvent.connection_id == connection.id,
                    CalendarInboundEvent.resource_url.in_(removes)))
            for url, event in fetches.items():
                await session.exec(delete(CalendarInboundEvent).where(
                    CalendarInboundEvent.connection_id == connection.id,
                    CalendarInboundEvent.resource_url == url))
                session.add(event)
            state.capability = "sync_token"
            state.sync_token = result.token
            state.error_state = "none"
            state.last_error = None
            state.last_synced_at = utc_now()
            session.add(state)
            await session.commit()
        return InboundOutcome(connection.id, "sync_token", len(fetches), len(removes), rebuilt=token is None)

    async def _rebuild(self, connection: CalendarConnection, adapter: CalDAVAdapter,
                       *, capability: str) -> InboundOutcome:
        """Complete listing replacement; deletions are only inferred from a full batch."""
        listing = await adapter.list_resources(connection.calendar_url)
        versions = {resource.url: resource.etag for resource in listing
                    if resource.url != connection.calendar_url}
        async with self.sessions() as session:
            cached_rows = (await session.exec(select(CalendarInboundEvent).where(
                CalendarInboundEvent.connection_id == connection.id))).all()
        cached = {row.resource_url: row for row in cached_rows}
        fetches = {}
        for url, etag in versions.items():
            if url not in cached or cached[url].etag != etag:
                resource = await adapter.get_resource(url)
                fetches[url] = _parse_resource(
                    _text(resource.payload),
                    connection_id=connection.id, resource_url=url, etag=etag)
        removed = [url for url in cached if url not in versions]
        async with self.sessions() as session:
            state = await _state_row(session, connection.id)
            if capability != "sync_token":
                state.sync_token = None
            state.capability = capability
            await session.exec(delete(CalendarInboundEvent).where(
                CalendarInboundEvent.connection_id == connection.id))
            for url, etag in versions.items():
                if url in fetches:
                    session.add(fetches[url])
                else:
                    # Retain the unchanged cached copy verbatim
                    row = cached[url]
                    session.add(CalendarInboundEvent(
                        connection_id=connection.id, resource_url=row.resource_url,
                        etag=versions[url], content=row.content, identity=row.identity,
                        uid=row.uid, summary=row.summary, component=row.component,
                        component_index=row.component_index, component_state=row.component_state,
                        fetched_at=row.fetched_at))
            state.error_state = "none"
            state.last_error = None
            state.last_synced_at = utc_now()
            session.add(state)
            await session.commit()
        return InboundOutcome(connection.id, capability, len(fetches), len(removed), rebuilt=True)


async def reconcile_connections(
    sessions: async_sessionmaker[AsyncSession], adapters,
    *, connection_id: str | None = None,
) -> None:
    """Reconcile enabled, verified connections; failures leave durable state untouched."""
    service = InboundService(sessions)
    async with sessions() as session:
        query = select(CalendarConnection).where(
            CalendarConnection.state == "connected",
            CalendarConnection.enabled == True,  # noqa: E712
            CalendarConnection.credential_state == "present",
        ).order_by(CalendarConnection.id)
        if connection_id is not None:
            query = query.where(CalendarConnection.id == connection_id)
        connections = (await session.exec(query)).all()
    for connection in connections:
        try:
            async with adapters(connection) as adapter:
                await service.reconcile(connection, adapter)
        except AuthenticationError:
            async with sessions() as session:
                await session.exec(update(CalendarConnection).where(
                    CalendarConnection.id == connection.id,
                    CalendarConnection.state == "connected",
                ).values(state="authentication_required", enabled=False, updated_at=utc_now()))
                await session.commit()
        except CalDAVError as exc:
            await _record_error(sessions, connection.id, str(exc))
        except InboundFailure as exc:
            await _record_error(sessions, connection.id, str(exc))


async def _record_error(sessions: async_sessionmaker[AsyncSession],
                        connection_id: str, message: str) -> None:
    async with sessions() as session:
        state = await _state_row(session, connection_id)
        state.error_state = "present"
        state.last_error = message[:2000]
        session.add(state)
        await session.commit()
