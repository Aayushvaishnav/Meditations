"""Explicit durable outbound dispatch with strict payload reconciliation."""

from datetime import datetime
import re
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import case, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_export import serialize_calendar
from app.calendar_sync.adapter import AuthenticationError, CalDAVError, ConflictError, NotFoundError
from app.calendar_sync.connections import ConnectionFailure, ConnectionManager
from app.calendar_sync.credentials import CredentialStoreError
from app.calendar_sync.transport import same_origin
from app.models import CalendarConnection, CalendarDispatch, CalendarLink, Task, TimeBlock
from app.util import utc_now


class OutboundFailure(ConnectionFailure):
    """Fixed-message outbound failure; never includes remote content."""


class _PreparationFailure(OutboundFailure):
    """Local projection failure; no remote outcome to reconcile."""


def _member(connection: CalendarConnection, url: str) -> None:
    try:
        calendar, target = urlsplit(connection.calendar_url), urlsplit(url)
        parent = unquote(calendar.path).rstrip('/') + '/'
        path = unquote(target.path)
        name = path[len(parent):] if path.startswith(parent) else ''
        if (not same_origin(connection.server_url, connection.calendar_url)
                or not same_origin(connection.calendar_url, url)
                or calendar.query or calendar.fragment or target.query or target.fragment
                or not name or '/' in name or name in {'.', '..'}
                or '\\' in path or any(ord(c) <= 32 or ord(c) == 127 for c in path)):
            raise ValueError
    except ValueError:
        raise OutboundFailure(409, 'Resource is not an immediate selected calendar member') from None


def _payload_identity(payload: bytes, uid: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Validate narrow grammar; ignore only folding and component-local ordering."""
    try:
        text = payload.decode('utf-8')
        if not text.endswith('\r\n') or '\n' in text.replace('\r\n', '') or '\r' in text.replace('\r\n', ''):
            raise ValueError
        lines = []
        for line in text[:-2].split('\r\n'):
            if line.startswith((' ', '\t')):
                if not lines:
                    raise ValueError
                lines[-1] += line[1:]
            else:
                lines.append(line)
        if lines[:1] != ['BEGIN:VCALENDAR'] or lines[-1:] != ['END:VCALENDAR']:
            raise ValueError
        calendar_lines, event_lines = [], []
        state, seen, event_count = 'calendar', set(), 0
        values = {}
        version = False
        for line in lines[1:-1]:
            if line == 'BEGIN:VEVENT' and state == 'calendar' and event_count == 0:
                if not version:
                    raise ValueError
                state, seen, event_count = 'event', set(), 1
                continue
            if line == 'END:VEVENT' and state == 'event':
                if not {'UID', 'DTSTART', 'DTEND'} <= seen:
                    raise ValueError
                start_key, start = values['DTSTART']
                end_key, end = values['DTEND']
                if (';VALUE=DATE' in start_key) != (';VALUE=DATE' in end_key) or start >= end:
                    raise ValueError
                state = 'finished'
                continue
            key, sep, value = line.partition(':')
            name = key.split(';')[0]
            allowed = ({'VERSION', 'PRODID', 'CALSCALE'} if state == 'calendar' else
                       {'UID', 'DTSTAMP', 'CREATED', 'LAST-MODIFIED', 'DTSTART', 'DTEND',
                        'SUMMARY', 'STATUS', 'X-JOURNAL-TIMEZONE', 'X-JOURNAL-DISPATCH'} if state == 'event' else set())
            if not sep or name not in allowed or name in seen:
                raise ValueError
            if key != name and not (name in {'DTSTART', 'DTEND'} and key == name + ';VALUE=DATE'):
                raise ValueError
            if name == 'UID' and value != uid:
                raise ValueError
            if any(ord(c) < 32 and c != '\t' or ord(c) == 127 for c in value):
                raise ValueError
            if name == 'VERSION':
                if value != '2.0':
                    raise ValueError
                version = True
            if name == 'STATUS' and value not in {'CONFIRMED', 'CANCELLED', 'TENTATIVE'}:
                raise ValueError
            if name in {'DTSTART', 'DTEND', 'DTSTAMP', 'CREATED', 'LAST-MODIFIED'}:
                date_only = key.endswith(';VALUE=DATE')
                pattern = r'[0-9]{8}' if date_only else r'[0-9]{8}T[0-9]{6}Z'
                if not re.fullmatch(pattern, value):
                    raise ValueError
                datetime.strptime(value, '%Y%m%d' if date_only else '%Y%m%dT%H%M%SZ')
                values[name] = (key, value)
            (calendar_lines if state == 'calendar' else event_lines).append(line)
            seen.add(name)
        if state != 'finished':
            raise ValueError
        return tuple(sorted(calendar_lines)), tuple(sorted(event_lines))
    except (ValueError, UnicodeError, AttributeError, TypeError):
        raise OutboundFailure(409, 'Remote calendar content is malformed or unsupported') from None


def _validate(payload: bytes, uid: str) -> None:
    _payload_identity(payload, uid)


class OutboundService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], manager: ConnectionManager) -> None:
        self.sessions = sessions
        self.manager = manager

    async def _connection_id(self, link_id: str) -> str:
        async with self.sessions() as session:
            link = await session.get(CalendarLink, link_id)
            if link is None:
                raise OutboundFailure(404, 'Calendar link not found')
            return link.connection_id

    async def _load(self, session: AsyncSession, link_id: str) -> tuple[CalendarLink, CalendarConnection]:
        link = await session.get(CalendarLink, link_id)
        if link is None:
            raise OutboundFailure(404, 'Calendar link not found')
        connection = await session.get(CalendarConnection, link.connection_id)
        if connection is None or connection.state != 'connected' or not connection.enabled or connection.credential_state != 'present':
            raise OutboundFailure(409, 'Calendar connection is not enabled and authenticated')
        if link.state in {'conflict', 'detached'}:
            raise OutboundFailure(409, 'Calendar link requires explicit detachment')
        uid = f'meditations-time-block-{uuid5(NAMESPACE_URL, "journal:time-block:" + link.local_block_id)}@journal.local'
        if link.uid != uid or link.block_id not in {None, link.local_block_id}:
            raise OutboundFailure(409, 'Calendar source identity is invalid')
        _member(connection, link.resource_url)
        return link, connection

    async def prepare(self, link_id: str) -> CalendarLink:
        async with self.manager.lock(await self._connection_id(link_id)):
            return await self._prepare_checked(link_id)

    async def _prepare_checked(self, link_id: str) -> CalendarLink:
        try:
            return await self._prepare(link_id)
        except _PreparationFailure:
            await self._record(link_id, 'Calendar source cannot be represented')
            raise

    async def _prepare(self, link_id: str) -> CalendarLink:
        async with self.sessions() as session:
            link, _ = await self._load(session, link_id)
            dispatch = await session.get(CalendarDispatch, link_id)
            if (link.desired_action == 'delete' and link.acknowledged_revision == 0
                    and link.etag is None and link.state != 'syncing'
                    and (dispatch is None or (
                        not dispatch.attempted and dispatch.action == 'upsert'
                        and dispatch.expected_etag is None
                        and dispatch.uid == link.uid and dispatch.resource_url == link.resource_url
                        and 0 < dispatch.revision <= link.local_revision))):
                # A never-attempted create has no remote ownership to delete
                if dispatch is not None:
                    await session.delete(dispatch)
                link.acknowledged_revision = link.local_revision
                link.acknowledged_action = 'delete'
                link.state, link.error_state, link.last_error = 'detached', 'none', None
                link.updated_at = utc_now()
                session.add(link)
                await session.commit()
                await session.refresh(link)
                return link
            if dispatch is not None:
                return link
            if (link.state == 'syncing' or (link.acknowledged_revision > 0 and link.etag is None
                                           and link.acknowledged_action != 'delete')):
                link.state, link.error_state = 'conflict', 'present'
                link.last_error = 'Prior remote outcome requires explicit detachment'
                link.updated_at = utc_now()
                session.add(link)
                await session.commit()
                await session.refresh(link)
                return link
            if link.local_revision == link.acknowledged_revision:
                return link
            payload = None
            if link.desired_action == 'upsert':
                block = await session.get(TimeBlock, link.block_id) if link.block_id else None
                task = await session.get(Task, block.task_id) if block else None
                if block is None or task is None or block.id != link.local_block_id:
                    raise _PreparationFailure(409, 'Calendar source is unavailable')
                try:
                    payload = serialize_calendar([(block, task)], exported_at=utc_now())
                    payload = payload.replace('END:VEVENT\r\n', f'X-JOURNAL-DISPATCH:{uuid4()}\r\nEND:VEVENT\r\n')
                    _validate(payload.encode('utf-8'), link.uid)
                except (ValueError, UnicodeError, AttributeError, OutboundFailure):
                    raise _PreparationFailure(422, 'Calendar source cannot be represented') from None
                link.payload, link.payload_state = payload, 'prepared'
            session.add(CalendarDispatch(link_id=link.id, revision=link.local_revision,
                action=link.desired_action, resource_url=link.resource_url, uid=link.uid,
                expected_etag=link.etag, payload=payload, attempted=False))
            link.state, link.updated_at = 'pending', utc_now()
            session.add(link)
            await session.commit()
            await session.refresh(link)
            return link

    async def _record(self, link_id: str, message: str, *, conflict: bool = False,
                      auth: bool = False) -> CalendarLink:
        async with self.sessions() as session:
            link = await session.get(CalendarLink, link_id)
            link.state = 'conflict' if conflict else 'error'
            link.error_state, link.last_error, link.updated_at = 'present', message, utc_now()
            session.add(link)
            if auth:
                connection = await session.get(CalendarConnection, link.connection_id)
                connection.state, connection.enabled = 'authentication_required', False
                connection.updated_at = utc_now()
                session.add(connection)
            await session.commit()
            await session.refresh(link)
            return link

    async def dispatch(self, link_id: str) -> CalendarLink:
        async with self.manager.lock(await self._connection_id(link_id)):
            prepared = await self._prepare_checked(link_id)
            if prepared.state in {'conflict', 'detached'}:
                return prepared
            async with self.sessions() as session:
                link, connection = await self._load(session, link_id)
                row = await session.get(CalendarDispatch, link_id)
                if row is None:
                    return link
                invalid = (row.resource_url != link.resource_url or row.uid != link.uid
                           or not link.acknowledged_revision < row.revision <= link.local_revision
                           or row.expected_etag != link.etag)
            if invalid:
                return await self._record(link_id, 'Dispatch identity or revision is invalid; detach explicitly', conflict=True)
            async with self.sessions() as session:
                link, connection = await self._load(session, link_id)
                _member(connection, row.resource_url)
            try:
                credentials = await self.manager.store.get(connection.id)
                if credentials is None:
                    raise AuthenticationError()
                async with self.manager.adapters(connection.server_url, credentials) as adapter:
                    try:
                        remote = await adapter.get_resource(row.resource_url)
                    except NotFoundError:
                        remote = None
                    payload = row.payload.encode('utf-8') if row.payload is not None else None
                    if remote is not None:
                        _validate(remote.payload, row.uid)
                    acknowledged = False
                    if row.action == 'upsert':
                        if (row.attempted and remote is not None and payload is not None
                                and _payload_identity(remote.payload, row.uid) == _payload_identity(payload, row.uid)):
                            acknowledged = True
                        elif row.expected_etag is None:
                            if remote is not None:
                                raise ConflictError()
                        elif remote is None or remote.etag != row.expected_etag:
                            raise ConflictError()
                    elif remote is None:
                        if not row.attempted:
                            raise ConflictError()
                        acknowledged = True
                    elif row.expected_etag is None or remote.etag != row.expected_etag:
                        raise ConflictError()
                    if not acknowledged:
                        async with self.sessions() as session:
                            current, _ = await self._load(session, link_id)
                            durable = await session.get(CalendarDispatch, link_id)
                            durable.attempted = True
                            current.state, current.updated_at = 'syncing', utc_now()
                            session.add(durable)
                            session.add(current)
                            await session.commit()
                        if row.action == 'upsert':
                            remote = await adapter.put_resource(row.resource_url, payload, etag=row.expected_etag)
                        else:
                            await adapter.delete_resource(row.resource_url, etag=row.expected_etag)
                    async with self.sessions() as session:
                        durable = await session.get(CalendarDispatch, link_id)
                        # Evaluate the revision at UPDATE time; source capture can race the acknowledgment
                        await session.exec(update(CalendarLink).where(CalendarLink.id == link_id).values(
                            acknowledged_revision=row.revision,
                            acknowledged_action=row.action,
                            etag=remote.etag if row.action == 'upsert' else None,
                            state=case(
                                (CalendarLink.local_revision > row.revision, 'pending'),
                                else_='detached' if row.action == 'delete' else 'synced',
                            ),
                            error_state='none', last_error=None, updated_at=utc_now(),
                            last_synced_at=utc_now(),
                        ))
                        await session.delete(durable)
                        await session.commit()
                        current = await session.get(CalendarLink, link_id)
                        await session.refresh(current)
                        return current
            except (ConflictError, OutboundFailure):
                return await self._record(link_id, 'Remote resource conflicts with dispatched intent; detach explicitly', conflict=True)
            except AuthenticationError:
                message = 'Calendar authentication is required'
                await self._record(link_id, message, auth=True)
                raise OutboundFailure(401, message) from None
            except (CalDAVError, CredentialStoreError, ValueError):
                message = 'Calendar dispatch failed; retain intent and retry reconciliation'
                await self._record(link_id, message)
                raise OutboundFailure(502, message) from None

    async def detach(self, link_id: str) -> CalendarLink:
        async with self.manager.lock(await self._connection_id(link_id)):
            async with self.sessions() as session:
                link = await session.get(CalendarLink, link_id)
                link.selection_state = 'detached'
                link.state, link.updated_at = 'detached', utc_now()
                session.add(link)
                await session.commit()
                await session.refresh(link)
                return link
