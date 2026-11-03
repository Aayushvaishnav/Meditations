"""Periodic outbound queue draining; SQLite retains intent between worker runs."""

import asyncio
import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_sync.adapter import AuthenticationError, CalDAVError
from app.calendar_sync.connections import ConnectionManager
from app.calendar_sync.credentials import CredentialStoreError
from app.calendar_sync.inbound import reconcile_connections
from app.calendar_sync.outbound import OutboundFailure, OutboundService
from app.calendar_sync.worker import inspect_once
from app.models import CalendarConnection, CalendarDispatch, CalendarLink

logger = logging.getLogger(__name__)


class QueueWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], manager: ConnectionManager):
        self.sessions = sessions
        self.manager = manager
        self.outbound = OutboundService(sessions, manager)
        self._run_lock = asyncio.Lock()

    @asynccontextmanager
    async def _adapter(self, connection: CalendarConnection):
        credentials = await self.manager.store.get(connection.id)
        if credentials is None:
            raise AuthenticationError()
        async with self.manager.adapters(connection.server_url, credentials) as adapter:
            yield adapter

    async def run_once(self, connection_id: str | None = None) -> None:
        # Serialize passes; each processes a finite snapshot
        async with self._run_lock:
            async with self.sessions() as session:
                connections = (await session.exec(select(CalendarConnection.id).where(
                    CalendarConnection.state == 'connected',
                    CalendarConnection.enabled == True,  # noqa: E712
                    CalendarConnection.credential_state == 'present',
                ).order_by(CalendarConnection.id))).all()
            for selected_id in connections:
                if connection_id is not None and selected_id != connection_id:
                    continue
                await self._drain(selected_id)
                try:
                    async with self.manager.lock(selected_id):
                        await inspect_once(self.sessions, self._adapter, connection_id=selected_id)
                except (CalDAVError, CredentialStoreError, ValueError):
                    logger.warning('Calendar inspection unavailable; retry on the next queue pass')
                try:
                    async with self.manager.lock(selected_id):
                        await reconcile_connections(self.sessions, self._adapter, connection_id=selected_id)
                except (CalDAVError, CredentialStoreError, ValueError):
                    logger.warning('Inbound reconciliation unavailable; retry on the next queue pass')

    async def _drain(self, connection_id: str) -> None:
        async with self.sessions() as session:
            dispatch = select(CalendarDispatch.link_id).where(
                CalendarDispatch.link_id == CalendarLink.id,
            ).exists()
            links = (await session.exec(select(CalendarLink.id).where(
                CalendarLink.connection_id == connection_id,
                CalendarLink.state.in_(['pending', 'syncing', 'error']),
                (CalendarLink.local_revision > CalendarLink.acknowledged_revision)
                | dispatch | (CalendarLink.state == 'syncing'),
            ).order_by(CalendarLink.created_at, CalendarLink.id))).all()
        for link_id in links:
            try:
                await self.outbound.dispatch(link_id)
            except OutboundFailure:
                # Dispatch persists failures; connection/link gates are rechecked under lock
                continue


async def serve(
    sessions: async_sessionmaker[AsyncSession], manager: ConnectionManager,
    *, interval_seconds: float = 30, worker: QueueWorker | None = None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError('Queue interval must be positive')
    worker = worker or QueueWorker(sessions, manager)
    while True:
        try:
            await worker.run_once()
        except Exception:
            logger.exception('Calendar queue pass failed; durable work will be retried')
        await asyncio.sleep(interval_seconds)
