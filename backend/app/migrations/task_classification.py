"""Frozen additive task classification migration; legacy values remain unassigned."""

from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_task_classification(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "ALTER TABLE tasks ADD COLUMN importance VARCHAR NOT NULL DEFAULT 'unassigned' "
        "CONSTRAINT ck_task_importance "
        "CHECK (importance IN ('unassigned', 'important', 'not_important'))"
    )
    await conn.exec_driver_sql(
        "ALTER TABLE tasks ADD COLUMN urgency VARCHAR NOT NULL DEFAULT 'unassigned' "
        "CONSTRAINT ck_task_urgency "
        "CHECK (urgency IN ('unassigned', 'urgent', 'not_urgent'))"
    )
