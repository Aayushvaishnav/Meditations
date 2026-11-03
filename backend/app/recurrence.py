"""Strict completion-triggered task rules; provider recurrence has separate ownership."""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, TypedDict

from pydantic import AfterValidator

WEEKDAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


class TaskRecurrenceError(ValueError):
    """A task rule cannot produce a supported successor."""


class ParsedRule(TypedDict):
    freq: str
    interval: int
    byday: list[str]


def parse_rrule(rule: str) -> ParsedRule | None:
    value = rule.strip().upper()
    if value.startswith("RRULE:"):
        value = value[len("RRULE:"):]
    parts: dict[str, str] = {}
    for chunk in value.split(";"):
        if chunk.count("=") != 1:
            return None
        key, value = (part.strip() for part in chunk.split("="))
        if key not in {"FREQ", "INTERVAL", "BYDAY"} or key in parts or not value:
            return None
        parts[key] = value

    freq = parts.get("FREQ")
    if freq not in ("DAILY", "WEEKLY"):
        return None
    interval_text = parts.get("INTERVAL", "1")
    if re.fullmatch(r"[0-9]+", interval_text) is None:
        return None
    try:
        interval = int(interval_text)
    except ValueError:
        return None
    # RFC 5545 INTEGER uses a signed 32-bit range; INTERVAL must be positive
    if not 1 <= interval <= 2_147_483_647:
        return None
    byday: list[str] = []
    if "BYDAY" in parts:
        byday = [day.strip() for day in parts["BYDAY"].split(",")]
        if freq != "WEEKLY" or any(day not in WEEKDAY_MAP for day in byday):
            return None
        if len(set(byday)) != len(byday):
            return None
    return {"freq": freq, "interval": interval, "byday": byday}


def validate_task_rule(rule: str) -> str:
    if parse_rrule(rule) is None:
        raise TaskRecurrenceError(
            "Unsupported task recurrence; use DAILY or WEEKLY, a positive INTERVAL, "
            "and optional weekly BYDAY. Clear or replace unsupported stored rules "
            "before completion."
        )
    return rule


TaskRule = Annotated[str, AfterValidator(validate_task_rule)]


def next_occurrence(rule: str, after: dt.datetime) -> dt.datetime | None:
    """Next task deadline; None means unsupported rule or exhausted date range."""
    parsed = parse_rrule(rule)
    if parsed is None:
        return None
    base = after.date()
    if parsed["freq"] == "DAILY":
        offset = parsed["interval"]
    else:
        weekday = base.weekday()
        days = [WEEKDAY_MAP[d] for d in parsed["byday"]] or [weekday]
        same_week = [day - weekday for day in days if day > weekday]
        offset = min(same_week) if same_week else 7 * parsed["interval"] + min(days) - weekday
    ordinal = base.toordinal() + offset
    if ordinal > dt.date.max.toordinal():
        return None
    return dt.datetime.combine(dt.date.fromordinal(ordinal), after.timetz())
