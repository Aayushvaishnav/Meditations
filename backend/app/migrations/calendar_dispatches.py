"""Immutable outbound revisions survive interruption independently of source edits."""

from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_calendar_dispatches(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "ALTER TABLE calendar_links ADD COLUMN acknowledged_action VARCHAR NOT NULL "
        "DEFAULT 'unknown' CONSTRAINT ck_calendar_link_acknowledged_action "
        "CHECK (acknowledged_action IN ('unknown', 'upsert', 'delete'))"
    )
    await conn.exec_driver_sql(
        "UPDATE calendar_links SET acknowledged_action='upsert' "
        "WHERE acknowledged_revision > 0 AND etag IS NOT NULL"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE calendar_dispatches ("
        "link_id VARCHAR NOT NULL PRIMARY KEY, revision INTEGER NOT NULL, "
        "action VARCHAR NOT NULL, resource_url VARCHAR NOT NULL, uid VARCHAR NOT NULL, "
        "expected_etag VARCHAR, payload VARCHAR, attempted BOOLEAN NOT NULL, "
        "CONSTRAINT ck_calendar_dispatch_revision CHECK (revision >= 1), "
        "CONSTRAINT ck_calendar_dispatch_action CHECK (action IN ('upsert', 'delete')), "
        "CONSTRAINT ck_calendar_dispatch_payload CHECK "
        "((action = 'upsert' AND payload IS NOT NULL) OR (action = 'delete' AND payload IS NULL)), "
        "CONSTRAINT ck_calendar_dispatch_attempted CHECK (attempted IN (0, 1)), "
        "FOREIGN KEY(link_id) REFERENCES calendar_links (id) ON DELETE CASCADE)"
    )
