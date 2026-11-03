"""Persist observed successful acknowledgments; historical timestamps are unknown."""

from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_calendar_sync_status(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql('ALTER TABLE calendar_links ADD COLUMN last_synced_at DATETIME')
    await conn.exec_driver_sql(
        "ALTER TABLE calendar_links ADD COLUMN selection_state VARCHAR NOT NULL DEFAULT 'opted_in' "
        "CONSTRAINT ck_calendar_link_selection_state "
        "CHECK (selection_state IN ('opted_in', 'opted_out', 'detached'))"
    )
    await conn.exec_driver_sql(
        "UPDATE calendar_links SET selection_state='detached' WHERE state='detached'"
    )
