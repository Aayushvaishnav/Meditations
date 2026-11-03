"""Local opaque calendar imports; never connected to scheduling or sync."""
from fastapi import APIRouter, HTTPException, Response
from sqlmodel import select

from app.calendar_import import service
from app.calendar_import.overlay import CalendarOverlay, overlay
from app.calendar_import.parser import CalendarImportError
from app.calendar_import.schemas import (
    EventInventory, ImportRequest, ImportResult, SnapshotInventory, SourceInventory,
)
from app.models import CalendarImportEvent, CalendarImportSnapshot
from app.routers.deps import SessionDep

router = APIRouter(prefix='/api/calendar/imports', tags=['calendar imports'])


@router.get('', response_model=list[SourceInventory])
async def list_sources(session: SessionDep):
    return await service.sources(session)


@router.post('', response_model=ImportResult)
async def import_calendar(body: ImportRequest, session: SessionDep):
    try:
        return await service.import_calendar(session, body)
    except CalendarImportError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/{source_id}/events', response_model=list[EventInventory])
async def events(source_id: str, session: SessionDep):
    await service.require_source(session, source_id)
    rows = (await session.exec(select(CalendarImportEvent).where(
        CalendarImportEvent.source_id == source_id
    ).order_by(CalendarImportEvent.uid, CalendarImportEvent.identity))).all()
    return [EventInventory.model_validate(row, from_attributes=True) for row in rows]


@router.get('/{source_id}/snapshots', response_model=list[SnapshotInventory])
async def snapshots(source_id: str, session: SessionDep):
    await service.require_source(session, source_id)
    rows = (await session.exec(select(CalendarImportSnapshot).where(
        CalendarImportSnapshot.source_id == source_id
    ).order_by(CalendarImportSnapshot.imported_at, CalendarImportSnapshot.id))).all()
    return [SnapshotInventory(id=row.id, content=row.content, imported_at=row.imported_at.isoformat()) for row in rows]


@router.delete('/{source_id}', status_code=204)
async def delete_source(source_id: str, session: SessionDep):
    await service.delete_source(session, source_id)
    return Response(status_code=204)


@router.get('/{source_id}/overlay', response_model=CalendarOverlay)
async def imported_overlay(source_id: str, session: SessionDep):
    return await overlay(session, source_id)
