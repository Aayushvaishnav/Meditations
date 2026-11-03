"""Explicit local opt-in and sync controls; no implicit reattachment."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.calendar_sync.connections import ConnectionFailure
from app.calendar_sync.queue_worker import QueueWorker
from app.models import CalendarConnection, CalendarLink, TimeBlock
from app.util import utc_now


class CalendarControls:
    def __init__(self, worker: QueueWorker):
        self.worker = worker
        self.manager = worker.manager
        self.sessions = worker.sessions

    @staticmethod
    def require_ready(connection: CalendarConnection) -> None:
        if connection.state != 'connected' or connection.credential_state != 'present':
            raise ConnectionFailure(409, 'Verify this calendar connection before enabling synchronization')

    async def enable(self, connection_id: str, enabled: bool) -> CalendarConnection:
        async with self.manager.lock(connection_id):
            async with self.sessions() as session:
                connection = await self.manager._load(session, connection_id)
                if enabled:
                    self.require_ready(connection)
                connection.enabled = enabled
                await self.manager._save(session, connection)
                return connection

    async def opt_in(self, connection_id: str, block_id: str) -> CalendarLink:
        async with self.manager.lock(connection_id):
            async with self.sessions() as session:
                connection = await self.manager._load(session, connection_id)
                self.require_ready(connection)
                if await session.get(TimeBlock, block_id) is None:
                    raise ConnectionFailure(404, 'Time block not found')
                existing = (await session.exec(select(CalendarLink).where(
                    CalendarLink.local_block_id == block_id,
                ))).first()
                if existing is not None:
                    if (existing.connection_id != connection_id or existing.state == 'conflict'
                            or existing.selection_state == 'detached'):
                        raise ConnectionFailure(409, 'This block mapping requires explicit reconciliation')
                    if existing.desired_action == 'delete':
                        existing.selection_state = 'opted_in'
                        existing.desired_action = 'upsert'
                        existing.local_revision += 1
                        existing.updated_at = utc_now()
                        if existing.state != 'syncing':
                            existing.state = 'pending'
                        session.add(existing)
                        await session.commit()
                        await session.refresh(existing)
                    return existing
                identity = uuid5(NAMESPACE_URL, 'journal:time-block:' + block_id)
                link = CalendarLink(connection_id=connection_id, block_id=block_id,
                                    local_block_id=block_id,
                                    uid=f'meditations-time-block-{identity}@journal.local',
                                    resource_url=connection.calendar_url + str(identity) + '.ics')
                session.add(link)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    raise ConnectionFailure(409, 'This block already has a calendar mapping') from None
                await session.refresh(link)
                return link

    async def opt_out(self, connection_id: str, block_id: str) -> CalendarLink:
        async with self.manager.lock(connection_id):
            async with self.sessions() as session:
                await self.manager._load(session, connection_id)
                link = (await session.exec(select(CalendarLink).where(
                    CalendarLink.connection_id == connection_id,
                    CalendarLink.local_block_id == block_id,
                ))).first()
                if link is None:
                    raise ConnectionFailure(404, 'Calendar link not found')
                if link.state in {'conflict', 'detached'}:
                    raise ConnectionFailure(409, 'Conflicted or detached mappings require explicit detachment')
                if link.desired_action != 'delete':
                    link.selection_state = 'opted_out'
                    link.desired_action = 'delete'
                    link.local_revision += 1
                    link.updated_at = utc_now()
                    if link.state != 'syncing':
                        link.state = 'pending'
                    session.add(link)
                    await session.commit()
                    await session.refresh(link)
                return link

    async def detach(self, connection_id: str, link_id: str) -> CalendarLink:
        async with self.sessions() as session:
            link = await session.get(CalendarLink, link_id)
            if link is None or link.connection_id != connection_id:
                raise ConnectionFailure(404, 'Calendar link not found')
        return await self.worker.outbound.detach(link_id)

    async def status(self, connection_id: str) -> dict:
        async with self.sessions() as session:
            connection = await self.manager._load(session, connection_id)
            links = (await session.exec(select(CalendarLink).where(
                CalendarLink.connection_id == connection_id,
            ))).all()
            return dict(connection=connection,
                        queued_count=sum(link.state in {'pending', 'syncing', 'error'} for link in links),
                        conflict_count=sum(link.state == 'conflict' for link in links),
                        error_count=sum(link.error_state == 'present' for link in links),
                        detached_count=sum(link.state == 'detached' for link in links),
                        last_success_state=('observed' if any(link.last_synced_at is not None for link in links)
                                            else 'unknown' if any(link.acknowledged_revision > 0 for link in links)
                                            else 'never'),
                        last_success_at=max((link.last_synced_at for link in links if link.last_synced_at is not None), default=None))

    async def sync_now(self, connection_id: str) -> dict:
        async with self.manager.lock(connection_id):
            async with self.sessions() as session:
                connection = await self.manager._load(session, connection_id)
                self.require_ready(connection)
                if not connection.enabled:
                    raise ConnectionFailure(409, 'Enable synchronization before Sync now')
        await self.worker.run_once(connection_id)
        return await self.status(connection_id)
