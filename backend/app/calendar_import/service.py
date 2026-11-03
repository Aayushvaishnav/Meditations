"""Atomic source-scoped replacement; absent identities are retained."""
from dataclasses import asdict

from fastapi import HTTPException
from sqlalchemy import delete, func
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.calendar_import.parser import event_properties, parse_calendar
from app.calendar_import.schemas import ImportRequest, ImportResult, NewSource, SourceInventory
from app.models import CalendarImportEvent, CalendarImportSnapshot, CalendarImportSource
from app.util import utc_now


async def require_source(session: AsyncSession, source_id: str) -> CalendarImportSource:
    source = await session.get(CalendarImportSource, source_id)
    if source is None:
        raise HTTPException(404, 'Imported calendar source not found')
    return source


async def import_calendar(session: AsyncSession, request: ImportRequest) -> ImportResult:
    parsed = parse_calendar(request.content)
    if isinstance(request.target, NewSource):
        source = CalendarImportSource(name=request.target.name)
        session.add(source)
        await session.flush()
    else:
        source = await require_source(session, request.target.source_id)
    snapshot = CalendarImportSnapshot(source_id=source.id, content=request.content, context=parsed.context)
    session.add(snapshot)
    await session.flush()
    rows = (await session.exec(select(CalendarImportEvent).where(
        CalendarImportEvent.source_id == source.id))).all()
    existing = {row.identity: row for row in rows}
    snapshots = {item.id: item for item in (await session.exec(select(
        CalendarImportSnapshot
    ).where(CalendarImportSnapshot.id.in_(
        select(CalendarImportEvent.snapshot_id).where(CalendarImportEvent.source_id == source.id)
    )))).all()}
    incoming_properties = event_properties(request.content.removeprefix('\ufeff'))
    previous_properties = {}
    created = updated = unchanged = 0
    for event in parsed.events:
        row = existing.get(event.identity)
        if row is not None and row.component == event.component and snapshots[row.snapshot_id].context == parsed.context:
            if row.snapshot_id not in previous_properties:
                previous_properties[row.snapshot_id] = event_properties(
                    snapshots[row.snapshot_id].content.removeprefix('\ufeff'))
            old = previous_properties[row.snapshot_id][row.component_index]
            new = incoming_properties[event.component_index]
            if all(old.get(key) == new.get(key) for key in ('DTSTART', 'DTEND')):
                unchanged += 1
                continue
        values = asdict(event)
        if row is None:
            row = CalendarImportEvent(source_id=source.id, snapshot_id=snapshot.id, **values)
            created += 1
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.snapshot_id = snapshot.id
            updated += 1
        session.add(row)
    source.updated_at = utc_now()
    session.add(source)
    await session.commit()
    return ImportResult(source_id=source.id, created=created, updated=updated, unchanged=unchanged)


async def sources(session: AsyncSession) -> list[SourceInventory]:
    rows = (await session.exec(select(
        CalendarImportSource, func.count(CalendarImportEvent.id)
    ).outerjoin(CalendarImportEvent, CalendarImportEvent.source_id == CalendarImportSource.id)
      .group_by(CalendarImportSource.id).order_by(CalendarImportSource.created_at, CalendarImportSource.id))).all()
    return [SourceInventory(id=s.id, name=s.name, event_count=count, updated_at=s.updated_at.isoformat())
            for s, count in rows]


async def delete_source(session: AsyncSession, source_id: str) -> None:
    await require_source(session, source_id)
    await session.exec(delete(CalendarImportSource).where(CalendarImportSource.id == source_id))
    await session.commit()
