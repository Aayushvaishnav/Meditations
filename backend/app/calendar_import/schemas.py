"""Read-only inventory and explicit import targets."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class NewSource(BaseModel):
    kind: Literal['new']
    name: Name


class ExistingSource(BaseModel):
    kind: Literal['existing']
    source_id: str


class ImportRequest(BaseModel):
    target: Annotated[NewSource | ExistingSource, Field(discriminator='kind')]
    content: str


class ImportResult(BaseModel):
    source_id: str
    created: int
    updated: int
    unchanged: int


class SourceInventory(BaseModel):
    id: str
    name: str
    event_count: int
    updated_at: str


class EventInventory(BaseModel):
    id: str
    uid: str
    summary: str
    recurrence_kind: Literal['master', 'date', 'utc', 'local', 'floating']
    recurrence_id: str
    time_zone: str | None
    recurrence_time_zone: str | None
    start_kind: Literal['date', 'utc', 'local', 'floating', 'unspecified']
    status: str
    has_recurrence: bool
    start_value: str | None
    end_value: str | None
    representation: Literal['opaque'] = 'opaque'


class SnapshotInventory(BaseModel):
    id: str
    content: str
    imported_at: str
