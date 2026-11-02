from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.models import Task, TimeBlock
from app.routers.deps import SessionDep
from app.time_blocks import Instant, TimeBlockWrite
from app.time_zones import CalendarDate
from app.util import utc_now

router = APIRouter(prefix="/api/time-blocks", tags=["time-blocks"])


async def _block(session: SessionDep, block_id: str) -> TimeBlock:
    block = await session.get(TimeBlock, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Time block not found")
    return block


async def _require_task(session: SessionDep, task_id: str) -> None:
    if await session.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")


@router.get("", response_model=list[TimeBlock])
async def list_blocks(
    session: SessionDep,
    task_id: str | None = None,
    start: Annotated[Instant | None, Query()] = None,
    end: Annotated[Instant | None, Query()] = None,
    start_date: Annotated[CalendarDate | None, Query()] = None,
    end_date: Annotated[CalendarDate | None, Query()] = None,
    kind: Literal["timed", "all_day"] | None = None,
):
    timed_range = start is not None or end is not None
    date_range = start_date is not None or end_date is not None
    if timed_range and date_range:
        raise HTTPException(status_code=422, detail="Use either instant or date bounds")
    if (timed_range and kind == "all_day") or (date_range and kind == "timed"):
        raise HTTPException(status_code=422, detail="Range does not match the block kind")
    if start is not None and end is not None and end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if start_date is not None and end_date is not None and end_date <= start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")
    query = select(TimeBlock)
    if kind is not None:
        query = query.where(TimeBlock.kind == kind)
    if task_id is not None:
        query = query.where(TimeBlock.task_id == task_id)
    if start is not None:
        query = query.where(TimeBlock.end_at > start)
    if end is not None:
        query = query.where(TimeBlock.start_at < end)
    if start_date is not None:
        query = query.where(TimeBlock.end_date > start_date)
    if end_date is not None:
        query = query.where(TimeBlock.start_date < end_date)
    return (await session.exec(query.order_by(
        TimeBlock.kind, TimeBlock.start_at, TimeBlock.start_date, TimeBlock.id,
    ))).all()


@router.post("", response_model=TimeBlock, status_code=201)
async def create_block(payload: TimeBlockWrite, session: SessionDep):
    await _require_task(session, payload.task_id)
    block = TimeBlock(**payload.storage_fields())
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return block


@router.get("/{block_id}", response_model=TimeBlock)
async def get_block(block_id: str, session: SessionDep):
    return await _block(session, block_id)


@router.put("/{block_id}", response_model=TimeBlock)
async def replace_block(block_id: str, payload: TimeBlockWrite, session: SessionDep):
    block = await _block(session, block_id)
    await _require_task(session, payload.task_id)
    block.sqlmodel_update(payload.storage_fields())
    block.updated_at = utc_now()
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return block


@router.delete("/{block_id}", status_code=204)
async def delete_block(block_id: str, session: SessionDep):
    block = await _block(session, block_id)
    await session.delete(block)
    await session.commit()
