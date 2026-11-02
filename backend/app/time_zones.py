"""IANA wall-clock resolution with explicit handling of gaps and overlaps."""

from __future__ import annotations

from datetime import UTC, date, datetime
from importlib.resources import files
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BeforeValidator


_PORTABLE_ZONES = frozenset(files("tzdata").joinpath("zones").read_text(encoding="utf-8").splitlines())


def parse_datetime(value: object) -> datetime:
    if isinstance(value, str):
        if len(value) <= 10 or value[10] not in ("T", "t", " "):
            raise ValueError("Expected an ISO datetime with a time component")
        try:
            value = datetime.fromisoformat(value.replace("t", "T"))
        except ValueError as exc:
            raise ValueError("Expected an ISO datetime") from exc
    if not isinstance(value, datetime):
        raise ValueError("Expected an ISO datetime with a time component")
    return value


def calendar_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Expected YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Expected YYYY-MM-DD") from exc
    if result.isoformat() != value:
        raise ValueError("Expected YYYY-MM-DD")
    return result


def zone_name(value: object) -> str:
    if not isinstance(value, str) or value not in _PORTABLE_ZONES:
        raise ValueError("Expected a portable IANA timezone name")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown IANA timezone") from exc
    return value


def resolve_local(value: datetime, timezone: str) -> datetime:
    """Resolve one local clock reading; offsets select folds instead of shifting gaps."""
    zone = ZoneInfo(zone_name(timezone))
    wall = value.replace(tzinfo=None)
    candidates = set()
    try:
        # ZoneInfo attaches either offset even in a gap; round trips prove existence.
        for fold in (0, 1):
            candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            projected = candidate.astimezone(zone)
            if projected.replace(tzinfo=None) != wall:
                continue
            if value.tzinfo is not None and projected.utcoffset() != value.utcoffset():
                continue
            candidates.add(candidate.replace(tzinfo=None))
    except OverflowError as exc:
        raise ValueError("Datetime is outside the supported timezone range") from exc
    if not candidates:
        raise ValueError("Local time does not exist or its offset does not match the timezone")
    if len(candidates) != 1:
        raise ValueError("Ambiguous local time; include an explicit matching UTC offset")
    return candidates.pop()


CalendarDate = Annotated[date, BeforeValidator(calendar_date)]
ZoneName = Annotated[str, BeforeValidator(zone_name)]
LocalDateTime = Annotated[datetime, BeforeValidator(parse_datetime)]
