"""Validate calendars without expanding recurrences or resolving event times."""
from copy import deepcopy
from dataclasses import dataclass
import json
import re

from icalendar import Calendar
from icalendar.parser import Contentlines


class CalendarImportError(ValueError):
    """An upload cannot be retained as a valid event calendar."""


@dataclass(frozen=True)
class ParsedEvent:
    identity: str
    uid: str
    summary: str
    recurrence_kind: str
    recurrence_id: str
    time_zone: str | None
    recurrence_time_zone: str | None
    start_kind: str
    status: str
    has_recurrence: bool
    start_value: str | None
    end_value: str | None
    component: str
    component_index: int


@dataclass(frozen=True)
class ParsedCalendar:
    events: tuple[ParsedEvent, ...]
    context: str


def event_properties(content: str) -> dict[int, dict]:
    # Use the library's unfolding/tokenization; its parser otherwise accepts trailing input
    stack = []
    roots = 0
    index = -1
    properties = {}
    for line in Contentlines.from_ical(content):
        if not line:
            continue
        name, params, value = line.parts()
        if name == 'BEGIN':
            allowed = {'VCALENDAR': {'VEVENT', 'VTIMEZONE'}, 'VEVENT': {'VALARM'},
                       'VTIMEZONE': {'STANDARD', 'DAYLIGHT'}}
            if stack and value.upper() not in allowed.get(stack[-1], set()):
                raise CalendarImportError(f'Unsupported {value} inside {stack[-1]}')
            if not stack:
                roots += 1
                if value.upper() != 'VCALENDAR' or roots != 1:
                    raise CalendarImportError('Expected exactly one VCALENDAR')
            if len(stack) == 1:
                index += 1
                if value.upper() == 'VEVENT':
                    properties[index] = {}
            stack.append(value.upper())
        elif name == 'END':
            if not stack or stack.pop() != value.upper():
                raise CalendarImportError('Mismatched calendar component framing')
        elif not stack:
            raise CalendarImportError('Property outside VCALENDAR')
        else:
            if name in ('DTSTART', 'DTEND', 'RECURRENCE-ID', 'DTSTAMP', 'CREATED', 'LAST-MODIFIED'):
                _date_shape(params, value, name)
            if name in ('RDATE', 'EXDATE') and params.get('VALUE') != 'PERIOD':
                for date_value in value.split(','):
                    _date_shape(params, date_value, name)
            if name in ('RRULE', 'EXRULE'):
                parts = [part.partition('=')[0].upper() for part in value.split(';')]
                if len(parts) != len(set(parts)):
                    raise CalendarImportError('Duplicate recurrence rule part')
            if stack == ['VCALENDAR', 'VEVENT']:
                properties[index][name] = (params, value)
    if stack or roots != 1:
        raise CalendarImportError('Incomplete VCALENDAR framing')
    return properties


def _date_shape(params, value: str, name: str) -> None:
    value_type = str(params.get('VALUE', 'DATE-TIME')).upper()
    date = value_type == 'DATE'
    pattern = r'[0-9]{8}' if date else r'[0-9]{8}T[0-9]{6}Z?'
    if value_type not in ('DATE', 'DATE-TIME') or re.fullmatch(pattern, value) is None:
        raise CalendarImportError(f'Invalid {name} {value_type} shape')
    if 'TZID' in params and (date or value.endswith('Z') or not params['TZID']):
        raise CalendarImportError(f'{name} TZID requires a non-UTC local DATE-TIME')


def _kind(params, value: str) -> str:
    return ('date' if len(value) == 8 else 'utc' if value.endswith('Z')
            else 'local' if 'TZID' in params else 'floating')


def _interval(raw) -> None:
    if 'DTEND' in raw and 'DURATION' in raw:
        raise CalendarImportError('VEVENT cannot combine DTEND with DURATION')
    if 'DTSTART' not in raw or 'DTEND' not in raw:
        return
    start_params, start = raw['DTSTART']
    end_params, end = raw['DTEND']
    start_kind, end_kind = _kind(start_params, start), _kind(end_params, end)
    if (start_kind == 'date') != (end_kind == 'date'):
        raise CalendarImportError('DTSTART and DTEND must have the same value type')
    # Lexical comparison is exact only within the same original clock domain
    if start_kind == end_kind and start_params.get('TZID') == end_params.get('TZID') and end <= start:
        raise CalendarImportError('DTEND must be after DTSTART')


def _rules(component) -> None:
    # vRecur validates types, but not RFC 5545 integer bounds
    bounds = {'BYSECOND': (0, 60), 'BYMINUTE': (0, 59), 'BYHOUR': (0, 23),
              'BYMONTH': (1, 12), 'BYMONTHDAY': (-31, 31), 'BYYEARDAY': (-366, 366),
              'BYWEEKNO': (-53, 53), 'BYSETPOS': (-366, 366)}
    for key in ('RRULE', 'EXRULE'):
        rules = component.get(key, [])
        if not isinstance(rules, list):
            rules = [rules]
        for rule in rules:
            known = {'FREQ', 'UNTIL', 'COUNT', 'INTERVAL', 'BYSECOND', 'BYMINUTE', 'BYHOUR',
                     'BYDAY', 'BYMONTHDAY', 'BYYEARDAY', 'BYWEEKNO', 'BYMONTH', 'BYSETPOS',
                     'WKST', 'RSCALE', 'SKIP'}
            if any(part not in known and not part.startswith('X-') for part in rule):
                raise CalendarImportError('Unknown non-extension recurrence rule part')
            if 'FREQ' not in rule or ('COUNT' in rule and 'UNTIL' in rule):
                raise CalendarImportError('Recurrence requires FREQ and cannot combine COUNT with UNTIL')
            for part in ('FREQ', 'COUNT', 'UNTIL', 'INTERVAL', 'WKST'):
                if len(rule.get(part, [])) > 1:
                    raise CalendarImportError(f'Recurrence {part} must have one value')
            for weekday in rule.get('BYDAY', []):
                ordinal = str(weekday)[:-2]
                if ordinal and (not -53 <= int(ordinal) <= 53 or int(ordinal) == 0):
                    raise CalendarImportError('Invalid recurrence BYDAY ordinal')
            for part in ('COUNT', 'INTERVAL'):
                if any(int(v) < 1 for v in rule.get(part, [])):
                    raise CalendarImportError(f'Invalid recurrence {part}')
            for part, (low, high) in bounds.items():
                for v in rule.get(part, []):
                    n = int(v)
                    if not low <= n <= high or (low < 0 and n == 0):
                        raise CalendarImportError(f'Invalid recurrence {part}')


def parse_calendar(content: str) -> ParsedCalendar:
    try:
        parsing_content = content.removeprefix('\ufeff')
        raw_events = event_properties(parsing_content)
        calendar = Calendar.from_ical(parsing_content)
        if str(calendar.get('VERSION', '')) != '2.0':
            raise CalendarImportError('VCALENDAR VERSION must be 2.0')
        for component in calendar.walk():
            if component.errors:
                raise CalendarImportError(f'Invalid {component.name}: {component.errors}')
            _rules(component)
        events = []
        identities = set()
        for index, component in enumerate(calendar.subcomponents):
            if component.name != 'VEVENT':
                continue
            for key in ('UID', 'RECURRENCE-ID', 'DTSTART', 'DTEND', 'SUMMARY', 'STATUS'):
                if isinstance(component.get(key), list):
                    raise CalendarImportError(f'Duplicate event property {key}')
            uid = str(component.get('UID', ''))
            if not uid.strip():
                raise CalendarImportError('Every VEVENT requires a nonempty UID')
            rid = component.get('RECURRENCE-ID')
            raw = raw_events[index]
            _interval(raw)
            params, value = raw.get('RECURRENCE-ID', ({}, ''))
            zone = str(params['TZID']) if 'TZID' in params else None
            kind = 'master' if rid is None else _kind(params, value)
            identity = json.dumps([uid, kind, value, zone], ensure_ascii=False)
            if identity in identities:
                raise CalendarImportError('Duplicate UID/RECURRENCE-ID identity in upload')
            identities.add(identity)
            start_params, start_value = raw.get('DTSTART', ({}, None))
            events.append(ParsedEvent(
                identity=identity, uid=uid, summary=str(component.get('SUMMARY', '')),
                recurrence_kind=kind, recurrence_id=value, recurrence_time_zone=zone,
                time_zone=str(start_params['TZID']) if 'TZID' in start_params else None,
                start_kind=_kind(start_params, start_value) if start_value is not None else 'unspecified',
                status=str(component.get('STATUS', '')),
                has_recurrence=any(k in component for k in ('RRULE', 'RDATE', 'EXDATE', 'EXRULE')),
                start_value=start_value, end_value=raw['DTEND'][1] if 'DTEND' in raw else None,
                component=component.to_ical().decode('utf-8'), component_index=index,
            ))
        context = deepcopy(calendar)
        context.subcomponents = [c for c in context.subcomponents if c.name != 'VEVENT']
        return ParsedCalendar(tuple(events), context.to_ical().decode('utf-8'))
    except CalendarImportError:
        raise
    except Exception as exc:
        raise CalendarImportError(f'Invalid iCalendar: {exc}') from exc
