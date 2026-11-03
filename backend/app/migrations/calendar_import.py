"""Frozen v13 opaque calendar inventory; independent of outbound calendar state."""
from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_calendar_import(conn: AsyncConnection) -> None:
    for sql in (
        'CREATE TABLE calendar_import_sources (id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL, '
        'created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)',
        'CREATE TABLE calendar_import_snapshots (id VARCHAR NOT NULL PRIMARY KEY, source_id VARCHAR NOT NULL, '
        'content VARCHAR NOT NULL, context VARCHAR NOT NULL, imported_at DATETIME NOT NULL, '
        'FOREIGN KEY(source_id) REFERENCES calendar_import_sources(id) ON DELETE CASCADE)',
        'CREATE INDEX ix_calendar_import_snapshots_source_id ON calendar_import_snapshots (source_id)',
        'CREATE TABLE calendar_import_events (id VARCHAR NOT NULL PRIMARY KEY, source_id VARCHAR NOT NULL, '
        'snapshot_id VARCHAR NOT NULL, identity VARCHAR NOT NULL, uid VARCHAR NOT NULL, summary VARCHAR NOT NULL, '
        'recurrence_kind VARCHAR NOT NULL, recurrence_id VARCHAR NOT NULL, time_zone VARCHAR, recurrence_time_zone VARCHAR, start_kind VARCHAR NOT NULL, status VARCHAR NOT NULL, '
        'has_recurrence BOOLEAN NOT NULL, start_value VARCHAR, end_value VARCHAR, component VARCHAR NOT NULL, '
        'component_index INTEGER NOT NULL, '
        'CONSTRAINT uq_calendar_import_identity UNIQUE (source_id, identity), '
        'FOREIGN KEY(source_id) REFERENCES calendar_import_sources(id) ON DELETE CASCADE, '
        'FOREIGN KEY(snapshot_id) REFERENCES calendar_import_snapshots(id) ON DELETE CASCADE)',
        'CREATE INDEX ix_calendar_import_events_source_id ON calendar_import_events (source_id)',
    ):
        await conn.exec_driver_sql(sql)
