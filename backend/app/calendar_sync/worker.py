"""Explicitly invoked, read-only calendar inspection worker."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_sync.adapter import AuthenticationError, CalDAVAdapter
from app.calendar_sync.service import LinkSnapshot, inspect_links
from app.models import CalendarConnection, CalendarLink
from app.util import utc_now

AdapterFactory = Callable[[CalendarConnection], AbstractAsyncContextManager[CalDAVAdapter]]


async def inspect_once(
    sessions: async_sessionmaker[AsyncSession], adapters: AdapterFactory,
    *, connection_id: str | None = None,
) -> None:
    """Inspect acknowledged links only; never create, update, or delete events."""
    async with sessions() as session:
        query = select(CalendarConnection).where(
            CalendarConnection.enabled == True,  # noqa: E712
            CalendarConnection.state == "connected",
        )
        if connection_id is not None:
            query = query.where(CalendarConnection.id == connection_id)
        connections = (await session.exec(query)).all()
    for connection in connections:
        async with sessions() as session:
            rows = (await session.exec(select(CalendarLink).where(
                CalendarLink.connection_id == connection.id,
                CalendarLink.state == "synced",
                CalendarLink.acknowledged_revision == CalendarLink.local_revision,
            ))).all()
            links = [LinkSnapshot(row.id, row.resource_url, row.etag, row.local_revision)
                     for row in rows if row.etag is not None]
        if not links:
            continue
        async with sessions() as session:
            active_connection = (await session.exec(select(CalendarConnection.id).where(
                CalendarConnection.id == connection.id,
                CalendarConnection.state == "connected",
                CalendarConnection.enabled == True,  # noqa: E712
                CalendarConnection.updated_at == connection.updated_at,
            ))).first()
        if active_connection is None:
            continue
        try:
            async with adapters(connection) as adapter:
                inspections = await inspect_links(adapter, connection.calendar_url, links)
        except AuthenticationError:
            async with sessions() as session:
                await session.exec(update(CalendarConnection).where(
                    CalendarConnection.id == connection.id,
                    CalendarConnection.state == "connected",
                    CalendarConnection.enabled == True,  # noqa: E712
                    CalendarConnection.updated_at == connection.updated_at,
                ).values(state="authentication_required", enabled=False, updated_at=utc_now()))
                await session.commit()
            continue
        for inspection in inspections:
            if inspection.outcome == "unchanged":
                continue
            link = inspection.link
            async with sessions() as session:
                # Compare the snapshot; an edit or disconnect wins over stale inspection
                active = select(CalendarConnection.id).where(
                    CalendarConnection.id == connection.id,
                    CalendarConnection.state == "connected",
                    CalendarConnection.enabled == True,  # noqa: E712
                    CalendarConnection.updated_at == connection.updated_at,
                ).exists()
                await session.exec(update(CalendarLink).where(
                    CalendarLink.id == link.id,
                    CalendarLink.state == "synced",
                    CalendarLink.local_revision == link.local_revision,
                    CalendarLink.etag == link.etag,
                    active,
                ).values(state="conflict", error_state="present",
                         last_error=f"Remote resource {inspection.outcome}", updated_at=utc_now()))
                await session.commit()
