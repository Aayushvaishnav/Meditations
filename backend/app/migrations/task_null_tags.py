"""Repair JSON null tags persisted by task PATCH requests before validation."""

from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_task_null_tags(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "UPDATE tasks SET tags = '[]' WHERE json_valid(tags) AND json_type(tags) = 'null'"
    )
