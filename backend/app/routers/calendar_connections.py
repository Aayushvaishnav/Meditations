"""Local calendar connections and explicit credential-backed verification."""

from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, Literal, TypeVar
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlmodel import select

from app.calendar_sync.adapter import Calendar
from app.calendar_sync.connections import ConnectionFailure, ConnectionManager
from app.calendar_sync.credentials import Credentials
from app.calendar_sync.controls import CalendarControls
from app.calendar_sync.dependencies import get_connection_manager
from app.calendar_sync.validation import CredentialRoute
from app.calendar_sync.inbound_overlay import InboundOverlay, inbound_overlay
from app.models import CalendarConnection, CalendarLink
from app.routers.deps import SessionDep

router = APIRouter(prefix="/api/calendar/connections", tags=["calendar-connections"], route_class=CredentialRoute)


def _origin(value: str) -> tuple[str, str, int]:
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError("Calendar URLs cannot contain whitespace or control characters")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError("Use an HTTP(S) URL without credentials, query, or fragment")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


class ConnectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_url: str
    calendar_url: str

    @model_validator(mode="after")
    def check_destination(self):
        if _origin(self.server_url) != _origin(self.calendar_url):
            raise ValueError("Server and calendar must have the same origin")
        if not urlsplit(self.calendar_url).path.endswith("/"):
            raise ValueError("Calendar collection URL must end with a slash")
        return self


@router.get("", response_model=list[CalendarConnection])
async def list_connections(session: SessionDep):
    return (await session.exec(select(CalendarConnection).order_by(CalendarConnection.id))).all()


@router.post("/resume", status_code=204)
async def resume_reconciliation(request: Request):
    """App-resume signal: run one reconciliation pass over verified, enabled connections."""
    worker = request.app.state.calendar_queue_worker
    await worker.run_once()
    return Response(status_code=204)


@router.post("", response_model=CalendarConnection, status_code=201)
async def create_connection(payload: ConnectionDraft, session: SessionDep):
    connection = CalendarConnection(**payload.model_dump())
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


@router.get("/{connection_id}/links", response_model=list[CalendarLink])
async def list_links(connection_id: str, session: SessionDep):
    if await session.get(CalendarConnection, connection_id) is None:
        raise HTTPException(status_code=404, detail="Calendar connection not found")
    return (await session.exec(select(CalendarLink).where(
        CalendarLink.connection_id == connection_id,
    ).order_by(CalendarLink.id))).all()


ManagerDep = Annotated[ConnectionManager, Depends(get_connection_manager)]
T = TypeVar("T")


async def _result(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except ConnectionFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from None


class AuthenticationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1)
    password: SecretStr = Field(min_length=1)
    auth_type: Literal["basic", "digest"]

    def credentials(self) -> Credentials:
        return Credentials(self.username, self.password.get_secret_value(), self.auth_type)


class ConnectInput(AuthenticationInput):
    calendar_url: str

    @field_validator("calendar_url")
    @classmethod
    def calendar_collection(cls, value: str) -> str:
        _origin(value)
        if not urlsplit(value).path.endswith("/"):
            raise ValueError("Calendar collection URL must end with a slash")
        return value


@router.post("/{connection_id}/discover", response_model=list[Calendar])
async def discover_calendars(connection_id: str, payload: AuthenticationInput,
                             session: SessionDep, manager: ManagerDep):
    return await _result(manager.discover(session, connection_id, payload.credentials()))


@router.post("/{connection_id}/connect", response_model=CalendarConnection)
async def connect_calendar(connection_id: str, payload: ConnectInput,
                           session: SessionDep, manager: ManagerDep):
    return await _result(manager.connect(session, connection_id, payload.credentials(), payload.calendar_url))


@router.post("/{connection_id}/verify", response_model=CalendarConnection)
async def verify_connection(connection_id: str, session: SessionDep, manager: ManagerDep):
    return await _result(manager.verify(session, connection_id))


@router.post("/{connection_id}/disconnect", response_model=CalendarConnection)
async def disconnect_calendar(connection_id: str, session: SessionDep, manager: ManagerDep):
    return await _result(manager.disconnect(session, connection_id))


@router.delete("/{connection_id}", status_code=204)
async def delete_draft(connection_id: str, session: SessionDep, manager: ManagerDep):
    await _result(manager.delete_draft(session, connection_id))


def get_calendar_controls(request: Request) -> CalendarControls:
    return CalendarControls(request.app.state.calendar_queue_worker)


ControlsDep = Annotated[CalendarControls, Depends(get_calendar_controls)]


class SyncInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool


class SyncStatus(BaseModel):
    connection: CalendarConnection
    queued_count: int
    conflict_count: int
    error_count: int
    detached_count: int
    last_success_at: datetime | None
    last_success_state: Literal['observed', 'unknown', 'never']


@router.patch('/{connection_id}/sync', response_model=CalendarConnection)
async def set_sync(connection_id: str, payload: SyncInput, controls: ControlsDep):
    return await _result(controls.enable(connection_id, payload.enabled))


@router.get('/{connection_id}/status', response_model=SyncStatus)
async def sync_status(connection_id: str, controls: ControlsDep):
    return await _result(controls.status(connection_id))


@router.post('/{connection_id}/sync-now', response_model=SyncStatus)
async def sync_now(connection_id: str, controls: ControlsDep):
    return await _result(controls.sync_now(connection_id))


@router.post('/{connection_id}/blocks/{block_id}/opt-in', response_model=CalendarLink)
async def opt_in_block(connection_id: str, block_id: str, controls: ControlsDep):
    return await _result(controls.opt_in(connection_id, block_id))


@router.post('/{connection_id}/blocks/{block_id}/opt-out', response_model=CalendarLink)
async def opt_out_block(connection_id: str, block_id: str, controls: ControlsDep):
    return await _result(controls.opt_out(connection_id, block_id))


@router.post('/{connection_id}/links/{link_id}/detach', response_model=CalendarLink)
async def detach_link(connection_id: str, link_id: str, controls: ControlsDep):
    return await _result(controls.detach(connection_id, link_id))


@router.get('/{connection_id}/inbound/overlay', response_model=InboundOverlay)
async def connection_inbound_overlay(connection_id: str, session: SessionDep):
    if await session.get(CalendarConnection, connection_id) is None:
        raise HTTPException(status_code=404, detail="Calendar connection not found")
    return await inbound_overlay(session, connection_id)
