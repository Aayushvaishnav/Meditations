"""Completion-triggered task recurrence; calendar arithmetic lives in recurrence.py."""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy.dialects.sqlite import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Task
from app.recurrence import next_occurrence
from app.util import utc_now


def ensure_recurrence_identity(task: Task) -> None:
    if task.recurrence_rule and task.recurrence_series_id is None:
        task.recurrence_series_id = task.id
        task.recurrence_occurrence = 0


async def spawn_successor(session: AsyncSession, task: Task) -> None:
    if not task.recurrence_rule:
        return
    ensure_recurrence_identity(task)
    if task.recurrence_occurrence is None:
        raise ValueError("Recurring task is missing its occurrence identity")

    anchor = (
        datetime.combine(task.deadline_date, time())
        if task.deadline_date is not None
        else task.due_date or task.completed_at or utc_now()
    )
    next_due = next_occurrence(task.recurrence_rule, anchor)
    if next_due is None:
        return

    successor = Task(
        list_id=task.list_id,
        parent_id=task.parent_id,
        title=task.title,
        description=task.description,
        priority=task.priority,
        due_date=next_due if task.deadline_date is None else None,
        deadline_date=next_due.date() if task.deadline_date is not None else None,
        estimated_minutes=task.estimated_minutes,
        recurrence_rule=task.recurrence_rule,
        recurrence_series_id=task.recurrence_series_id,
        recurrence_occurrence=task.recurrence_occurrence + 1,
        tags=list(task.tags),
        order_index=task.order_index + 1000.0,
    )
    # Flush the completed source first; both writes share the caller's transaction
    await session.flush()
    await session.exec(
        insert(Task)
        .values(**successor.model_dump())
        .on_conflict_do_nothing(index_elements=["recurrence_series_id", "recurrence_occurrence"])
    )
