"""Explicit selected-block calendar snapshots; no subscription or recurrence."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlmodel import select

from app.calendar_export import serialize_calendar
from app.models import Task, TimeBlock
from app.routers.deps import SessionDep
from app.util import utc_now

router = APIRouter(prefix='/api/calendar', tags=['calendar'])
BlockID = Annotated[str, StringConstraints(strict=True, min_length=1)]


class CalendarExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    block_ids: Annotated[list[BlockID], Field(min_length=1)]


@router.post('/export')
async def export_calendar(payload: CalendarExportRequest, session: SessionDep):
    ids = sorted(set(payload.block_ids))
    events = (await session.exec(
        select(TimeBlock, Task).join(Task, TimeBlock.task_id == Task.id)
        .where(TimeBlock.id.in_(ids)).order_by(TimeBlock.id)
    )).all()
    if len(events) != len(ids):
        raise HTTPException(status_code=404, detail='Selected time block not found')
    try:
        calendar = serialize_calendar(events, exported_at=utc_now())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(calendar, media_type='text/calendar; charset=utf-8', headers={
        'Content-Disposition': 'attachment; filename="meditations-calendar.ics"',
    })
