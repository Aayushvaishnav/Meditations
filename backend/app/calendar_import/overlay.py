"""Read-only standalone projections; recurrence and durations stay opaque."""
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Calendar
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_import.parser import event_properties
from app.calendar_import.service import require_source
from app.models import CalendarImportEvent, CalendarImportSnapshot


class DateInterval(BaseModel):
    kind: Literal['date'] = 'date'
    start: str
    end: str


class TimedInterval(BaseModel):
    kind: Literal['timed'] = 'timed'
    start: str
    end: str


class FloatingInterval(BaseModel):
    kind: Literal['floating'] = 'floating'
    start: str
    end: str


class OverlayEvent(BaseModel):
    source_id: str
    id: str
    uid: str
    summary: str
    status: str


class PlacedEvent(OverlayEvent):
    interval: Annotated[DateInterval | TimedInterval | FloatingInterval, Field(discriminator='kind')]


class UnplacedEvent(OverlayEvent):
    reason: Literal['cancelled', 'recurrence', 'missing_start', 'unsupported_duration',
                    'unknown_timezone', 'invalid_interval', 'incomparable_interval',
                    'invalid_component', 'ambiguous_local_time', 'nonexistent_local_time']


class CalendarOverlay(BaseModel):
    source_id: str
    items: list[PlacedEvent]
    unplaced: list[UnplacedEvent]


class ProjectionError(ValueError):
    pass


def _value(raw, zones: dict[str, tzinfo]):
    params, clock = raw
    if len(clock) == 8:
        return 'date', date.fromisoformat(clock)
    value = datetime.fromisoformat(clock)
    if zone_id := params.get('TZID'):
        zone = zones.get(str(zone_id))
        if zone is None:
            try:
                zone = ZoneInfo(str(zone_id))
            except (ZoneInfoNotFoundError, ValueError):
                raise ProjectionError('unknown_timezone') from None
        value = value.replace(tzinfo=zone, fold=0)
    if value.tzinfo is None:
        return 'floating', value
    utc = value.astimezone(timezone.utc)
    # A gap cannot round-trip; ambiguous folds cannot identify one exact instant
    if utc.astimezone(value.tzinfo).replace(tzinfo=None) != value.replace(tzinfo=None):
        raise ProjectionError('nonexistent_local_time')
    if value.replace(fold=0).utcoffset() != value.replace(fold=1).utcoffset():
        raise ProjectionError('ambiguous_local_time')
    return 'timed', utc


def _interval(component, raw, zones: dict[str, tzinfo]):
    if 'DURATION' in component:
        raise ProjectionError('unsupported_duration')
    if 'DTSTART' not in raw:
        raise ProjectionError('missing_start')
    kind, start = _value(raw['DTSTART'], zones)
    if 'DTEND' in raw:
        end_kind, end = _value(raw['DTEND'], zones)
        if kind != end_kind:
            raise ProjectionError('incomparable_interval')
        if end <= start:
            raise ProjectionError('invalid_interval')
    else:
        end = start + timedelta(days=1) if kind == 'date' else start
    def encode(value):
        return value.isoformat().replace('+00:00', 'Z')
    interval_type = {'date': DateInterval, 'timed': TimedInterval, 'floating': FloatingInterval}[kind]
    return interval_type(start=encode(start), end=encode(end))


async def overlay(session: AsyncSession, source_id: str) -> CalendarOverlay:
    await require_source(session, source_id)
    rows = (await session.exec(select(CalendarImportEvent).where(
        CalendarImportEvent.source_id == source_id
    ).order_by(CalendarImportEvent.uid, CalendarImportEvent.identity))).all()
    snapshots = {snapshot.id: snapshot for snapshot in (await session.exec(
        select(CalendarImportSnapshot).where(CalendarImportSnapshot.id.in_(
            select(CalendarImportEvent.snapshot_id).where(CalendarImportEvent.source_id == source_id)
        ))
    )).all()}
    parsed_snapshots = {}
    series = {row.uid for row in rows if row.has_recurrence or row.recurrence_kind != 'master'}
    result = CalendarOverlay(source_id=source_id, items=[], unplaced=[])
    for row in rows:
        common = dict(source_id=source_id, id=row.id, uid=row.uid, summary=row.summary, status=row.status)
        try:
            if row.status.upper() == 'CANCELLED':
                raise ProjectionError('cancelled')
            if row.uid in series:
                raise ProjectionError('recurrence')
            if row.snapshot_id not in parsed_snapshots:
                snapshot = snapshots[row.snapshot_id]
                calendar = Calendar.from_ical(snapshot.context)
                zones = {
                    str(zone['TZID']): zone.to_tz(lookup_tzid=False)
                    for zone in calendar.subcomponents if zone.name == 'VTIMEZONE'
                }
                # Serialization can erase TZID; resolve original snapshot clock properties
                raw_events = event_properties(snapshot.content.removeprefix('\ufeff'))
                parsed_snapshots[row.snapshot_id] = (zones, raw_events)
            zones, raw_events = parsed_snapshots[row.snapshot_id]
            component_calendar = Calendar.from_ical(
                'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + row.component + 'END:VCALENDAR\r\n')
            component = component_calendar.subcomponents[0]
            if component.errors:
                raise ProjectionError('invalid_component')
            if any(key in component for key in ('RRULE', 'RDATE', 'EXRULE', 'EXDATE', 'RECURRENCE-ID')):
                raise ProjectionError('recurrence')
            result.items.append(PlacedEvent(**common, interval=_interval(component, raw_events[row.component_index], zones)))
        except ProjectionError as exc:
            result.unplaced.append(UnplacedEvent(**common, reason=str(exc)))
        except (ValueError, TypeError, KeyError, StopIteration, OverflowError):
            result.unplaced.append(UnplacedEvent(**common, reason='invalid_component'))
    return result
