"""Frozen v15 inbound calendar cache; live reconciled events stay external to tasks."""
from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_calendar_inbound(conn: AsyncConnection) -> None:
    for sql in (
        'CREATE TABLE calendar_inbound_state (id VARCHAR NOT NULL PRIMARY KEY, '
        'connection_id VARCHAR NOT NULL, capability VARCHAR NOT NULL, revision INTEGER NOT NULL DEFAULT \'0\', sync_token VARCHAR, '
        'last_synced_at DATETIME, error_state VARCHAR NOT NULL DEFAULT \'none\', last_error VARCHAR, '
        'CONSTRAINT uq_calendar_inbound_connection UNIQUE (connection_id), '
        'CONSTRAINT ck_calendar_inbound_revision CHECK (revision >= 0), '
        'CONSTRAINT ck_calendar_inbound_capability CHECK (capability IN (\'unknown\', \'sync_token\', \'listing\')), '
        'CONSTRAINT ck_calendar_inbound_token CHECK ((capability = \'sync_token\' AND sync_token IS NOT NULL) '
        'OR capability != \'sync_token\'), '
        'FOREIGN KEY(connection_id) REFERENCES calendar_connections(id) ON DELETE CASCADE)',
        'CREATE INDEX ix_calendar_inbound_state_connection_id ON calendar_inbound_state (connection_id)',
        'CREATE TABLE calendar_inbound_events (id VARCHAR NOT NULL PRIMARY KEY, '
        'connection_id VARCHAR NOT NULL, resource_url VARCHAR NOT NULL, etag VARCHAR NOT NULL, '
        'content VARCHAR NOT NULL, identity VARCHAR, uid VARCHAR, summary VARCHAR, component VARCHAR, '
        'component_index INTEGER, component_state VARCHAR NOT NULL, fetched_at DATETIME NOT NULL, '
        'CONSTRAINT uq_calendar_inbound_resource UNIQUE (connection_id, resource_url), '
        'CONSTRAINT ck_calendar_inbound_component CHECK (component_state IN (\'stored\', \'unparsable\')), '
        'CONSTRAINT ck_calendar_inbound_content CHECK ((component_state = \'stored\' AND identity IS NOT NULL '
        'AND uid IS NOT NULL AND summary IS NOT NULL AND component IS NOT NULL AND component_index IS NOT NULL) OR '
        '(component_state = \'unparsable\' AND identity IS NULL AND uid IS NULL AND summary IS NULL '
        'AND component IS NULL AND component_index IS NULL)), '
        'FOREIGN KEY(connection_id) REFERENCES calendar_connections(id) ON DELETE CASCADE)',
        'CREATE INDEX ix_calendar_inbound_events_connection_id ON calendar_inbound_events (connection_id)',
    ):
        await conn.exec_driver_sql(sql)
