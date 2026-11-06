"""Recurrence regression contracts; no database or network."""
from datetime import date, datetime

from test_external_recurrence import calendar, expand
from test_calendar_overlay import custom_zone
from app import external_recurrence as recurrence
from app.calendar_import.parser import parse_calendar


def test_impossible_rule_has_internal_until(monkeypatch):
    real = recurrence.rrulestr
    cutoffs = []
    class Observe:
        def __init__(self, rule):
            self.rule = rule
        def replace(self, **kwargs):
            cutoffs.append(kwargs['until'])
            return self.rule.replace(**kwargs)
    monkeypatch.setattr(recurrence, 'rrulestr', lambda *a, **kw: Observe(real(*a, **kw)))
    items, errors = expand(calendar('DTSTART:20260301T090000\nRRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30'))
    assert not errors and not items
    assert cutoffs == [datetime(2026, 3, 13)]
    items, errors = expand(calendar('DTSTART:20260301T090000\nRRULE:FREQ=MONTHLY;BYMONTH=2;BYMONTHDAY=30;BYSETPOS=1;UNTIL=20260305T090000'))
    assert not errors and not items
    assert cutoffs[-1] == datetime(2026, 3, 5, 9)


def test_day_budget_before_iteration(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('ancient rule entered dateutil')
    monkeypatch.setattr(recurrence, 'rrulestr', forbidden)
    items, errors = expand(calendar('DTSTART:19000101T090000\nRRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30'))
    assert not items and errors[0]['reason'] == 'recurrence_limit'


def test_ny_rdate_and_equivalent_utc_moved_rid():
    master = 'DTSTART;TZID=America/New_York:20260307T090000\nRRULE:FREQ=DAILY;COUNT=4\nRDATE:20260309T130000Z'
    items, errors = expand(calendar(master, 'RECURRENCE-ID:20260309T130000Z\nDTSTART:20260310T160000Z'))
    assert not errors and len(items) == 4
    moved = [i for i in items if i['interval'].start == '2026-03-10T16:00:00Z']
    assert len(moved) == 1 and '2026-03-09T09:00:00' in moved[0]['id']
    assert not any(i['interval'].start == '2026-03-09T13:00:00Z' for i in items)


def test_raw_snapshot_custom_zone_rdate_and_rid():
    def content(offset):
        body = calendar('DTSTART;TZID=Review/Local:20260307T090000\nRRULE:FREQ=DAILY;COUNT=1\nRDATE;TZID=Review/Local:20260309T090000',
                        'RECURRENCE-ID;TZID=Review/Local:20260309T090000\nDTSTART;TZID=Review/Local:20260310T110000')
        return body.replace('END:VCALENDAR', custom_zone('Review/Local', offset) + 'END:VCALENDAR')
    a, b = content('+0530'), content('+0200')
    # Populate the library timezone cache with conflicting snapshots
    parse_calendar(a)
    parse_calendar(b)
    for raw, expected in [(a, ['2026-03-07T03:30:00Z', '2026-03-10T05:30:00Z']),
                          (b, ['2026-03-07T07:00:00Z', '2026-03-10T09:00:00Z']),
                          (a, ['2026-03-07T03:30:00Z', '2026-03-10T05:30:00Z'])]:
        items, errors = expand(raw)
        assert not errors
        assert [i['interval'].start for i in items] == expected


def test_long_all_day_overlap():
    items, errors = expand(calendar('DTSTART;VALUE=DATE:20260301\nDTEND;VALUE=DATE:20260310\nRRULE:FREQ=DAILY;COUNT=4'), '2026-03-09', '2026-03-11')
    assert not errors and len(items) == 4
    assert [i['interval'].start for i in items] == ['2026-03-01', '2026-03-02', '2026-03-03', '2026-03-04']


def test_live_component_identity_inputs_unique():
    raw = calendar('DTSTART:20260308T090000Z').replace('UID:series', 'UID:a')
    extra = calendar('DTSTART:20260308T120000Z').replace('UID:series', 'UID:b')
    unsupported = calendar('DTSTART:20260308T090000Z\nRRULE:FREQ=HOURLY', 'RECURRENCE-ID:20260309T090000Z\nSTATUS:CANCELLED')
    raw = raw.replace('END:VCALENDAR\r\n', '') + extra.split('VERSION:2.0\r\n')[1].replace('END:VCALENDAR\r\n', '') + unsupported.split('VERSION:2.0\r\n')[1]
    entries = [(dict(connection_id='c', id=f'resource:{e.identity}', uid=e.uid, summary=e.summary, status=e.status), raw, e.component_index) for e in parse_calendar(raw).events]
    items, errors = recurrence.project(entries, date(2026, 3, 7), date(2026, 3, 11))
    ids = [i['id'] for i in items + errors]
    assert len(items) == 2 and len(errors) == 2 and len(set(ids)) == 4
