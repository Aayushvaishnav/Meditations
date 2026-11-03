"""Frozen v9 DDL for cross-store credential lifecycle; no credential material."""

from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_calendar_credentials(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        "ALTER TABLE calendar_connections ADD COLUMN credential_state VARCHAR "
        "NOT NULL DEFAULT 'absent' "
        "CONSTRAINT ck_calendar_connection_credential_state "
        "CHECK (credential_state IN ('absent', 'present', 'removal_pending'))"
    )
