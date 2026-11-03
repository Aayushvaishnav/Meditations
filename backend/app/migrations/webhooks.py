"""Frozen v14 outgoing automation outbox."""

from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_webhooks(conn: AsyncConnection) -> None:
    for sql in (
        "CREATE TABLE webhook_endpoints (id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL, url VARCHAR NOT NULL, enabled BOOLEAN NOT NULL, events VARCHAR NOT NULL, scope VARCHAR NOT NULL, include_titles BOOLEAN NOT NULL)",
        "CREATE TABLE webhook_versions (entity_id VARCHAR NOT NULL PRIMARY KEY, version INTEGER NOT NULL)",
        "CREATE TABLE webhook_deliveries (id VARCHAR NOT NULL PRIMARY KEY, endpoint_id VARCHAR NOT NULL, event_id VARCHAR NOT NULL, event_type VARCHAR NOT NULL, entity_id VARCHAR NOT NULL, entity_version INTEGER NOT NULL, payload VARCHAR NOT NULL, state VARCHAR NOT NULL, attempts INTEGER NOT NULL, last_error VARCHAR, next_attempt_at DATETIME NOT NULL, created_at DATETIME NOT NULL, FOREIGN KEY(endpoint_id) REFERENCES webhook_endpoints(id) ON DELETE CASCADE)",
        "CREATE INDEX ix_webhook_deliveries_endpoint_id ON webhook_deliveries (endpoint_id)",
    ):
        await conn.exec_driver_sql(sql)
