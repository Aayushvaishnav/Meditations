"""Frozen v8 DDL for explicit outbound calendar ownership; no credentials or triggers."""

from sqlalchemy.ext.asyncio import AsyncConnection


STATEMENTS = (
    """CREATE TABLE calendar_connections (
    id VARCHAR NOT NULL,
    server_url VARCHAR NOT NULL,
    calendar_url VARCHAR NOT NULL,
    state VARCHAR NOT NULL,
    enabled BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_calendar_connection_state CHECK (state IN ('disconnected', 'connected', 'authentication_required'))
)""",
    """CREATE TABLE calendar_links (
    id VARCHAR NOT NULL,
    connection_id VARCHAR NOT NULL,
    block_id VARCHAR,
    local_block_id VARCHAR NOT NULL,
    uid VARCHAR NOT NULL,
    resource_url VARCHAR NOT NULL,
    etag VARCHAR,
    state VARCHAR NOT NULL,
    local_revision INTEGER NOT NULL,
    acknowledged_revision INTEGER NOT NULL,
    desired_action VARCHAR NOT NULL,
    payload_state VARCHAR NOT NULL,
    payload VARCHAR,
    error_state VARCHAR NOT NULL,
    last_error VARCHAR,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_calendar_link_local_block UNIQUE (local_block_id),
    CONSTRAINT uq_calendar_link_resource UNIQUE (connection_id, resource_url),
    CONSTRAINT ck_calendar_link_state CHECK (state IN ('pending', 'syncing', 'synced', 'conflict', 'error', 'detached')),
    CONSTRAINT ck_calendar_link_action CHECK (desired_action IN ('upsert', 'delete')),
    CONSTRAINT ck_calendar_link_revisions CHECK (local_revision >= 1 AND acknowledged_revision >= 0 AND acknowledged_revision <= local_revision),
    CONSTRAINT ck_calendar_link_payload CHECK ((payload_state = 'unprepared' AND payload IS NULL) OR (payload_state = 'prepared' AND payload IS NOT NULL)),
    CONSTRAINT ck_calendar_link_error CHECK ((error_state = 'none' AND last_error IS NULL) OR (error_state = 'present' AND last_error IS NOT NULL)),
    CONSTRAINT ck_calendar_link_block_identity CHECK (block_id IS NULL OR block_id = local_block_id),
    FOREIGN KEY(connection_id) REFERENCES calendar_connections (id) ON DELETE RESTRICT,
    FOREIGN KEY(block_id) REFERENCES time_blocks (id) ON DELETE SET NULL
)""",
    """CREATE INDEX ix_calendar_links_block_id ON calendar_links (block_id)""",
    """CREATE INDEX ix_calendar_links_connection_id ON calendar_links (connection_id)""",
)


async def migrate_calendar_sync(conn: AsyncConnection) -> None:
    for statement in STATEMENTS:
        await conn.exec_driver_sql(statement)
