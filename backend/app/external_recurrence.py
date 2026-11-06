"""Bounded read-only RFC recurrence subset; daily/weekly/monthly/yearly only."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
import json
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from fastapi import HTTPException
from icalendar import Calendar

from app.calendar_import.parser import event_properties, _rules

MAX_CANDIDATES = 20000


def validate_window(start: date | None, end: date | None) -> None:
    if (start is None) != (end is None):
        raise HTTPException(422, 'start and end must be supplied together')
    if start is not None and not 0 < (end - start).days <= 370:
        raise HTTPException(422, 'Window must be positive and at most 370 days; end is exclusive')


def project(rows, start, end):
    """Rows are (common metadata, original calendar text, component index)."""
    from app.calendar_import.overlay import ProjectionError, _interval, _value
    groups = {}
    output, failures = [], []
    for common, content, index in rows:
        groups.setdefault(common['uid'], []).append((common, content, index))
    for entries in groups.values():
        pending = []
        try:
            parsed = []
            for common, content, index in entries:
                cal = Calendar.from_ical(content.removeprefix('\ufeff'))
                zones = {str(z['TZID']): z.to_tz(lookup_tzid=False)
                         for z in cal.subcomponents if z.name == 'VTIMEZONE'}
                raw = event_properties(content.removeprefix('\ufeff'))[index]
                comp = cal.subcomponents[index]
                if comp.errors:
                    raise ProjectionError('invalid_component')
                parsed.append((common, comp, raw, zones))
            masters = [p for p in parsed if 'RECURRENCE-ID' not in p[1]]
            if len(masters) != 1:
                raise ProjectionError('unsupported_recurrence')
            common, comp, raw, zones = masters[0]
            if str(comp.get('STATUS', '')).upper() == 'CANCELLED':
                continue
            recurring = any(k in comp for k in ('RRULE', 'RDATE', 'EXDATE', 'EXRULE')) or len(parsed) > 1
            if not recurring:
                candidates = [(common, comp, raw, zones)]
            else:
                if 'EXRULE' in comp or 'DTSTART' not in raw:
                    raise ProjectionError('unsupported_recurrence')
                _rules(comp)
                if 'DTEND' in raw:
                    start_params, start_clock = raw['DTSTART']
                    end_params, end_clock = raw['DTEND']
                    if (start_params.get('TZID'), start_clock.endswith('Z'), len(start_clock) == 8) != (end_params.get('TZID'), end_clock.endswith('Z'), len(end_clock) == 8):
                        raise ProjectionError('unsupported_recurrence')
                kind, _ = _value(raw['DTSTART'], zones)
                # Generate in the source wall-clock domain, not UTC; DST must not shift the clock
                params, clock = raw['DTSTART']
                dtstart = date.fromisoformat(clock) if kind == 'date' else datetime.fromisoformat(clock)
                if params.get('TZID'):
                    zone_id = str(params['TZID'])
                    dtstart = dtstart.replace(tzinfo=zones.get(zone_id) or ZoneInfo(zone_id))
                is_date = not isinstance(dtstart, datetime)
                seed = datetime.combine(dtstart, time()) if is_date else dtstart
                dates = {seed}
                def source_value(value, property_params):
                    if isinstance(value, tuple):
                        raise ProjectionError('unsupported_recurrence')
                    if isinstance(value, datetime) != isinstance(dtstart, datetime):
                        raise ProjectionError('unsupported_recurrence')
                    if is_date:
                        return datetime.combine(value, time())
                    if property_params.get('TZID'):
                        zone_id = str(property_params['TZID'])
                        value = value.replace(tzinfo=zones.get(zone_id) or ZoneInfo(zone_id))
                    if (value.tzinfo is None) != (seed.tzinfo is None):
                        raise ProjectionError('unsupported_recurrence')
                    return value.astimezone(seed.tzinfo) if value.tzinfo else value
                rules = comp.get('RRULE', [])
                if not isinstance(rules, list):
                    rules = [rules]
                if len(rules) > 1:
                    raise ProjectionError('unsupported_recurrence')
                for rule in rules:
                    allowed = {'FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY', 'BYMONTHDAY', 'BYMONTH', 'WKST', 'BYSETPOS'}
                    if set(rule) - allowed or str(rule['FREQ'][0]) not in {'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'}:
                        raise ProjectionError('unsupported_recurrence')
                    frequency = str(rule['FREQ'][0])
                    if frequency in {'DAILY', 'WEEKLY'} and any(str(day)[:-2] for day in rule.get('BYDAY', [])):
                        raise ProjectionError('unsupported_recurrence')
                    if frequency == 'WEEKLY' and 'BYMONTHDAY' in rule:
                        raise ProjectionError('unsupported_recurrence')
                    if 'BYSETPOS' in rule and not any(key.startswith('BY') and key != 'BYSETPOS' for key in rule):
                        raise ProjectionError('unsupported_recurrence')
                    if (end - seed.date()).days > MAX_CANDIDATES:
                        raise ProjectionError('recurrence_limit')
                    cutoff = datetime.combine(end, time(), tzinfo=seed.tzinfo) + timedelta(days=2)
                    if 'UNTIL' in rule:
                        original_until = rule['UNTIL'][0]
                        if not isinstance(original_until, datetime):
                            original_until = datetime.combine(original_until, time(), tzinfo=seed.tzinfo)
                        cutoff = min(cutoff, original_until)
                    bounded_rule = deepcopy(rule)
                    count = int(bounded_rule.pop('COUNT')[0]) if 'COUNT' in bounded_rule else MAX_CANDIDATES + 1
                    iterator = rrulestr(bounded_rule.to_ical().decode(), dtstart=seed).replace(until=cutoff)
                    for n, value in enumerate(iterator):
                        if n >= count:
                            break
                        if n >= MAX_CANDIDATES:
                            raise ProjectionError('recurrence_limit')
                        if value.date() > end + timedelta(days=2):
                            break
                        dates.add(value)
                def values(key):
                    props = comp.get(key, [])
                    if not isinstance(props, list):
                        props = [props]
                    result = set()
                    for prop in props:
                        for v in prop.dts:
                            result.add(source_value(v.dt, prop.params))
                    return result
                dates |= values('RDATE')
                dates -= values('EXDATE')
                if len(dates) > MAX_CANDIDATES:
                    raise ProjectionError('recurrence_limit')
                overrides = {}
                for p in parsed:
                    if 'RECURRENCE-ID' in p[1]:
                        rid = p[1]['RECURRENCE-ID']
                        if rid.params.get('RANGE'):
                            raise ProjectionError('unsupported_recurrence')
                        value = source_value(rid.dt, rid.params)
                        if value in overrides:
                            raise ProjectionError('unsupported_recurrence')
                        overrides[value] = p
                dates |= set(overrides)
                if len(dates) > MAX_CANDIDATES:
                    raise ProjectionError('recurrence_limit')
                candidates = []
                for value in sorted(dates):
                    identity = json.dumps([common['uid'], kind,
                                           value.replace(tzinfo=None).isoformat(),
                                           str(params.get('TZID', 'UTC' if clock.endswith('Z') else ''))], ensure_ascii=False)
                    metadata = dict(common, id=identity)
                    if value in overrides:
                        oc, component, original, oz = overrides[value]
                        candidates.append((dict(oc, id=identity), component, original, oz))
                        continue
                    duration = timedelta(days=1) if is_date else timedelta()
                    if 'DTEND' in raw:
                        duration = max(duration, datetime.fromisoformat(raw['DTEND'][1]).replace(tzinfo=None)
                                       - datetime.fromisoformat(clock).replace(tzinfo=None))
                    if value.date() >= end + timedelta(days=2) or value.date() < start - duration - timedelta(days=2):
                        continue
                    original = deepcopy(raw)
                    delta = value.replace(tzinfo=None) - seed.replace(tzinfo=None)
                    for key in ('DTSTART', 'DTEND'):
                        if key in original:
                            field_params, field_clock = original[key]
                            shifted = datetime.fromisoformat(field_clock) + delta
                            original[key] = (field_params, shifted.strftime('%Y%m%d') if is_date else shifted.strftime('%Y%m%dT%H%M%S') + ('Z' if field_clock.endswith('Z') else ''))
                    candidates.append((metadata, comp, original, zones))
            for metadata, component, original, oz in candidates:
                if str(component.get('STATUS', '')).upper() == 'CANCELLED':
                    continue
                interval = _interval(component, original, oz)
                a = datetime.fromisoformat(interval.start.replace('Z', '+00:00'))
                b = datetime.fromisoformat(interval.end.replace('Z', '+00:00'))
                lo = datetime.combine(start, time(), tzinfo=a.tzinfo)
                hi = datetime.combine(end, time(), tzinfo=a.tzinfo)
                if a < hi and (b > lo or a == b and a >= lo):
                    pending.append(dict(metadata, interval=interval))
            output.extend(pending)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, AttributeError) as exc:
            reason = str(exc) if isinstance(exc, ProjectionError) else 'unsupported_recurrence'
            failures.extend(dict(common, reason=reason) for common, _, _ in entries)
    return output, failures
