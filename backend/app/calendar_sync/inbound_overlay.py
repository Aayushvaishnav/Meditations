"""Read-only projection of live reconciled remote events; tasks stay authoritative locally."""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Calendar
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_import.overlay import DateInterval, FloatingInterval, ProjectionError, TimedInterval, _interval, _value
from app.calendar_import.parser import event_properties
from app.models import CalendarInboundEvent


class InboundOverlayItem(BaseModel):
    connection_id: str
    id: str
    uid: str
    summary: str
    status: str
    interval: Annotated[DateInterval | TimedInterval | FloatingInterval, Field(discriminator='kind')]


class InboundOverlayUnplaced(BaseModel):
    connection_id: str
    id: str
    uid: str
    summary: str
    status: str
    reason: Literal['cancelled', 'recurrence', 'missing_start', 'unsupported_duration',
                    'unknown_timezone', 'invalid_interval', 'incomparable_interval',
                    'invalid_component', 'ambiguous_local_time', 'nonexistent_local_time',
                    'unparsable_resource', 'unsupported_resource']


class InboundOverlay(BaseModel):
    connection_id: str
    items: list[InboundOverlayItem]
    unplaced: list[InboundOverlayUnplaced]


def _project(event: CalendarInboundEvent) -> tuple[InboundOverlayItem | None, InboundOverlayUnplaced | None]:
    common = dict(connection_id=event.connection_id, id=event.id,
                  uid=event.uid or '', summary=event.summary or '', status='')
    if event.component_state != 'stored':
        return None, InboundOverlayUnplaced(**common, reason='unparsable_resource')
    try:
        calendar = Calendar.from_ical(event.content.removeprefix('\ufeff'))
        zones = {str(zone['TZID']): zone.to_tz(lookup_tzid=False)
                 for zone in calendar.subcomponents if zone.name == 'VTIMEZONE'}
        raw_events = event_properties(event.content.removeprefix('\ufeff'))
        component_calendar = Calendar.from_ical(
            'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + event.component + 'END:VCALENDAR\r\n')
        component = component_calendar.subcomponents[0]
        if component.errors:
            raise ProjectionError('invalid_component')
        if str(component.get('STATUS', '')):
            common['status'] = str(component.get('STATUS', ''))
            if common['status'].upper() == 'CANCELLED':
                raise ProjectionError('cancelled')
        if any(key in component for key in ('RRULE', 'RDATE', 'EXRULE', 'EXDATE', 'RECURRENCE-ID')):
            raise ProjectionError('recurrence')
        interval = _interval(component, raw_events[event.component_index], zones)
        return InboundOverlayItem(**common, interval=interval), None
    except ProjectionError as exc:
        return None, InboundOverlayUnplaced(**common, reason=str(exc))
    except (ValueError, TypeError, KeyError, StopIteration, OverflowError):
        return None, InboundOverlayUnplaced(**common, reason='invalid_component')


async def inbound_overlay(session: AsyncSession, connection_id: str) -> InboundOverlay:
    rows = (await session.exec(select(CalendarInboundEvent).where(
        CalendarInboundEvent.connection_id == connection_id,
    ).order_by(CalendarInboundEvent.uid, CalendarInboundEvent.resource_url))).all()
    result = InboundOverlay(connection_id=connection_id, items=[], unplaced=[])
    for row in rows:
        item, unplaced = _project(row)
        if item is not None:
            result.items.append(item)
        else:
            result.unplaced.append(unplaced)
    return result
