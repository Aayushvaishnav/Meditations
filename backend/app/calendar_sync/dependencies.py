"""Application-scoped connection manager and database-scoped credential identity."""

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.calendar_sync.connections import ConnectionManager
from app.calendar_sync.credentials import OSCredentialStore


def create_manager(engine: AsyncEngine) -> ConnectionManager:
    database = engine.url.database
    identity = (f"memory:{uuid4()}" if database in {None, "", ":memory:"}
                else str(Path(database).resolve()))
    namespace = sha256(identity.encode()).hexdigest()
    return ConnectionManager(OSCredentialStore(namespace))


def get_connection_manager(request: Request) -> ConnectionManager:
    return request.app.state.calendar_connection_manager
