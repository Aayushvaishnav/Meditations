"""Frozen v7 DDL for timed and all-day time blocks."""

from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_time_block_shapes(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "CREATE TABLE time_blocks_v7 ("
        "id VARCHAR NOT NULL PRIMARY KEY, task_id VARCHAR NOT NULL, "
        "kind VARCHAR NOT NULL, timezone VARCHAR, "
        "start_at DATETIME, end_at DATETIME, start_date DATE, end_date DATE, "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
        "CONSTRAINT ck_time_block_shape CHECK ("
        "(kind = 'timed' AND timezone IS NOT NULL "
        "AND start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at "
        "AND start_date IS NULL AND end_date IS NULL) OR "
        "(kind = 'all_day' AND timezone IS NULL "
        "AND start_at IS NULL AND end_at IS NULL "
        "AND start_date IS NOT NULL AND end_date IS NOT NULL AND end_date > start_date)), "
        "FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE)"
    )
    await conn.exec_driver_sql(
        "INSERT INTO time_blocks_v7 "
        "(id, task_id, kind, timezone, start_at, end_at, start_date, end_date, created_at, updated_at) "
        "SELECT id, task_id, 'timed', 'UTC', start_at, end_at, NULL, NULL, created_at, updated_at "
        "FROM time_blocks"
    )
    await conn.exec_driver_sql("DROP TABLE time_blocks")
    await conn.exec_driver_sql("ALTER TABLE time_blocks_v7 RENAME TO time_blocks")
    for column in ("task_id", "start_at", "end_at", "start_date", "end_date"):
        await conn.exec_driver_sql(f"CREATE INDEX ix_time_blocks_{column} ON time_blocks ({column})")
