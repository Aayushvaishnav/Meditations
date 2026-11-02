"""Explicit timed, local-clock, and all-day work-block inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.time_zones import CalendarDate, LocalDateTime, ZoneName, parse_datetime, resolve_local
from app.util import normalize_dt


def _instant(value: object) -> datetime:
    try:
        return normalize_dt(parse_datetime(value))
    except OverflowError as exc:
        raise ValueError("Datetime is outside the supported UTC range") from exc


Instant = Annotated[datetime, BeforeValidator(_instant)]


class BlockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: Annotated[str, StringConstraints(min_length=1)]


class TimedBlockWrite(BlockInput):
    kind: Literal["timed"] = "timed"
    start_at: Instant
    end_at: Instant
    timezone: ZoneName = "UTC"

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        try:
            for instant in (self.start_at, self.end_at):
                instant.replace(tzinfo=UTC).astimezone(ZoneInfo(self.timezone))
        except OverflowError as exc:
            raise ValueError("Datetime is outside the supported timezone range") from exc
        return self

    def storage_fields(self) -> dict:
        return {**self.model_dump(), "start_date": None, "end_date": None}


class LocalBlockWrite(BlockInput):
    kind: Literal["local"]
    start_local: LocalDateTime
    end_local: LocalDateTime
    timezone: ZoneName

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        start = resolve_local(self.start_local, self.timezone)
        end = resolve_local(self.end_local, self.timezone)
        if end <= start:
            raise ValueError("end_local must resolve after start_local")
        return self

    def storage_fields(self) -> dict:
        return {
            "kind": "timed", "task_id": self.task_id, "timezone": self.timezone,
            "start_at": resolve_local(self.start_local, self.timezone),
            "end_at": resolve_local(self.end_local, self.timezone),
            "start_date": None, "end_date": None,
        }


class AllDayBlockWrite(BlockInput):
    kind: Literal["all_day"]
    start_date: CalendarDate
    end_date: CalendarDate

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date (exclusive end)")
        return self

    def storage_fields(self) -> dict:
        return {
            **self.model_dump(), "timezone": None, "start_at": None, "end_at": None,
        }


def _legacy_timed(value: object) -> object:
    if isinstance(value, dict) and "kind" not in value:
        return {**value, "kind": "timed"}
    return value


TimeBlockWrite = Annotated[
    Annotated[TimedBlockWrite | LocalBlockWrite | AllDayBlockWrite, Field(discriminator="kind")],
    BeforeValidator(_legacy_timed),
]
