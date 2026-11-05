"""Task status transitions; callers own the transaction."""

from datetime import datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Task
from app.recurring_tasks import ensure_recurrence_identity, spawn_successor
from app.schemas import TaskStatus


async def apply_task_status(
    session: AsyncSession, task: Task, status: TaskStatus, *, at: datetime,
) -> None:
    completing = status == "completed" and task.status != "completed"
    task.status = status
    if completing:
        task.completed_at = at
    elif status != "completed":
        task.completed_at = None

    ensure_recurrence_identity(task)
    if completing:
        await spawn_successor(session, task)
