"""Transactional source capture; immutable dispatches belong to the outbound worker."""

from sqlalchemy.ext.asyncio import AsyncConnection


_CAPTURE = """
    local_revision = local_revision + 1,
    payload_state = 'unprepared', payload = NULL,
    state = CASE WHEN state IN ('conflict', 'syncing') THEN state ELSE 'pending' END,
    error_state = CASE WHEN state IN ('conflict', 'syncing') THEN error_state ELSE 'none' END,
    last_error = CASE WHEN state IN ('conflict', 'syncing') THEN last_error ELSE NULL END,
    updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')
"""
_ACTIVE = "state != 'detached' AND desired_action = 'upsert'"


async def migrate_calendar_queue(conn: AsyncConnection) -> None:
    # Orphans may still have an uncertain in-flight upsert; retain its dispatch
    await conn.exec_driver_sql(
        f"UPDATE calendar_links SET {_CAPTURE}, desired_action = 'delete' "
        f"WHERE block_id IS NULL AND {_ACTIVE}"
    )
    columns = ('kind', 'timezone', 'start_at', 'end_at', 'start_date', 'end_date', 'task_id')
    changed = ' OR '.join(f'OLD.{column} IS NOT NEW.{column}' for column in columns)
    await conn.exec_driver_sql(f"""
        CREATE TRIGGER calendar_queue_block_update
        AFTER UPDATE OF {', '.join(columns)} ON time_blocks
        WHEN {changed}
        BEGIN
            UPDATE calendar_links SET {_CAPTURE}
            WHERE block_id = NEW.id AND {_ACTIVE};
        END
    """)
    await conn.exec_driver_sql(f"""
        CREATE TRIGGER calendar_queue_task_update
        AFTER UPDATE OF title, status ON tasks
        WHEN OLD.title IS NOT NEW.title
            OR (OLD.status = 'canceled') IS NOT (NEW.status = 'canceled')
        BEGIN
            UPDATE calendar_links SET {_CAPTURE}
            WHERE block_id IN (SELECT id FROM time_blocks WHERE task_id = NEW.id)
                AND {_ACTIVE};
        END
    """)
    # BEFORE is required; FK SET NULL otherwise erases the source identity first
    await conn.exec_driver_sql(f"""
        CREATE TRIGGER calendar_queue_block_delete
        BEFORE DELETE ON time_blocks
        BEGIN
            UPDATE calendar_links SET {_CAPTURE}, desired_action = 'delete'
            WHERE block_id = OLD.id AND {_ACTIVE};
        END
    """)
