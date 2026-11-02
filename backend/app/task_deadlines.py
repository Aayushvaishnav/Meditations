"""Typed deadlines; calendar labels never become persisted instants."""
from datetime import date as Date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.util import normalize_dt


class NoDeadline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["none"] = "none"


class DateDeadline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["date"]
    date: Date

    @field_validator("date", mode="before")
    @classmethod
    def calendar_label(cls, value):
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("date must be YYYY-MM-DD")
        return value


class TimedDeadline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["timed"]
    at: datetime

    @field_validator("at", mode="before")
    @classmethod
    def instant(cls, value):
        if not isinstance(value, (str, datetime)) or (isinstance(value, str) and "T" not in value):
            raise ValueError("at must be an ISO datetime")
        return value

    @field_validator("at")
    @classmethod
    def utc(cls, value):
        return normalize_dt(value)


Deadline = Annotated[NoDeadline | DateDeadline | TimedDeadline, Field(discriminator="kind")]


class DeadlineInput(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def validate_deadline_fields(cls, values):
        if isinstance(values, dict):
            if "deadline_date" in values:
                raise ValueError("deadline_date is read-only")
            if "deadline" in values and (values["deadline"] is None or "due_date" in values):
                raise ValueError("deadline must be non-null and cannot accompany due_date")
        return values


def persistence_fields(data: dict) -> dict:
    if "deadline" in data:
        deadline = data.pop("deadline")
        data["due_date"] = deadline.get("at") if deadline["kind"] == "timed" else None
        data["deadline_date"] = deadline.get("date") if deadline["kind"] == "date" else None
    elif "due_date" in data:
        data["deadline_date"] = None
    return data


def deadline_value(due_date: datetime | None, deadline_date: Date | None) -> Deadline:
    if due_date is not None:
        return TimedDeadline(kind="timed", at=due_date)
    if deadline_date is not None:
        return DateDeadline(kind="date", date=deadline_date.isoformat())
    return NoDeadline()
