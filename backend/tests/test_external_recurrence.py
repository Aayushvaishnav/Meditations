from datetime import date

import pytest
from fastapi import HTTPException

from app.external_recurrence import project, validate_window


def calendar(*events):
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + ''.join(
        'BEGIN:VEVENT\r\nUID:series\r\n' + event.replace('\n', '\r\n') + '\r\nEND:VEVENT\r\n'
        for event in events) + 'END:VCALENDAR\r\n'


def expand(content, start='2026-03-07', end='2026-03-11'):
    from app.calendar_import.parser import parse_calendar
    parsed = parse_calendar(content)
    return project([(dict(source_id='s', id=str(i), uid=e.uid, summary=e.summary, status=e.status),
                     content, e.component_index) for i, e in enumerate(parsed.events)],
                   date.fromisoformat(start), date.fromisoformat(end))


def test_dst_and_refresh_identity():
    content = calendar('DTSTART;TZID=America/New_York:20260307T090000\nDTEND;TZID=America/New_York:20260307T100000\nRRULE:FREQ=DAILY;COUNT=4')
    items, errors = expand(content)
    assert not errors
    assert [i['interval'].start for i in items] == ['2026-03-07T14:00:00Z', '2026-03-08T13:00:00Z', '2026-03-09T13:00:00Z', '2026-03-10T13:00:00Z']
    assert [i['id'] for i in items] == [i['id'] for i in expand(content)[0]]


def test_moved_in_out_cancelled_and_exdates():
    content = calendar(
        'DTSTART:20260301T090000\nRRULE:FREQ=DAILY;COUNT=10\nEXDATE:20260309T090000\nRDATE:20260310T120000',
        'RECURRENCE-ID:20260301T090000\nDTSTART:20260308T100000',
        'RECURRENCE-ID:20260307T090000\nDTSTART:20260401T090000',
        'RECURRENCE-ID:20260308T090000\nSTATUS:CANCELLED')
    items, errors = expand(content)
    assert not errors
    assert [i['interval'].start for i in items] == ['2026-03-08T10:00:00', '2026-03-10T09:00:00', '2026-03-10T12:00:00']
    assert '2026-03-01' in items[0]['id']


@pytest.mark.parametrize('rule,reason', [('FREQ=HOURLY', 'unsupported_recurrence'), ('FREQ=DAILY', 'recurrence_limit')])
def test_atomic_rejection(rule, reason):
    items, errors = expand(calendar('DTSTART:19000101T090000\nRRULE:' + rule))
    assert not items
    assert errors[0]['reason'] == reason


@pytest.mark.parametrize('start,end', [(date(2026, 1, 1), None), (None, date(2026, 1, 1)), (date(2026, 1, 1), date(2026, 1, 1)), (date(2026, 1, 1), date(2028, 1, 1))])
def test_window_validation(start, end):
    with pytest.raises(HTTPException) as exc:
        validate_window(start, end)
    assert exc.value.status_code == 422


@pytest.mark.parametrize('rule,expected', [
    ('FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4', ['2026-03-02', '2026-03-04', '2026-03-09', '2026-03-11']),
    ('FREQ=MONTHLY;BYDAY=1MO;COUNT=3', ['2026-03-02', '2026-04-06', '2026-05-04']),
    ('FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1;COUNT=3', ['2026-03-02', '2026-04-01', '2026-05-01']),
    ('FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=2;COUNT=1', ['2026-03-02']),
])
def test_calendar_frequency_subsets(rule, expected):
    items, errors = expand(calendar('DTSTART;VALUE=DATE:20260302\nRRULE:' + rule), '2026-03-01', '2026-06-01')
    assert not errors
    assert [item['interval'].start for item in items] == expected


def test_exclusive_end_and_cancelled_master():
    content = calendar('DTSTART;VALUE=DATE:20260307\nRRULE:FREQ=DAILY;COUNT=5')
    assert len(expand(content)[0]) == 4
    assert expand(content.replace('RRULE:', 'STATUS:CANCELLED\r\nRRULE:')) == ([], [])


def test_cross_zone_rdate_and_exdate_normalize_to_source_clock():
    content = calendar('DTSTART;TZID=America/New_York:20260307T090000\nRRULE:FREQ=DAILY;COUNT=1\nRDATE:20260309T130000Z')
    items, errors = expand(content)
    assert not errors
    assert items[1]['interval'].start == '2026-03-09T13:00:00Z'
    assert '2026-03-09T09:00:00' in items[1]['id']
    assert len(expand(content.replace('RDATE:', 'EXDATE:20260307T140000Z\nRDATE:'))[0]) == 1


def test_sparse_ancient_rule_rejected_before_iteration():
    items, errors = expand(calendar('DTSTART:19000101T090000\nRRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30'))
    assert not items
    assert errors[0]['reason'] == 'recurrence_limit'


def test_long_duration_overlap_survives_subsequent_candidates():
    items, errors = expand(calendar('DTSTART:20260301T090000\nDTEND:20260320T090000\nRRULE:FREQ=DAILY;COUNT=3'))
    assert not errors
    assert len(items) == 3


@pytest.mark.parametrize('rule', ['FREQ=DAILY;BYDAY=1MO', 'FREQ=WEEKLY;BYMONTHDAY=2', 'FREQ=MONTHLY;BYSETPOS=1'])
def test_invalid_rule_combinations_reject(rule):
    items, errors = expand(calendar('DTSTART:20260307T090000\nRRULE:' + rule))
    assert not items
    assert errors[0]['reason'] == 'unsupported_recurrence'


def test_mixed_end_domain_rejected():
    items, errors = expand(calendar('DTSTART;TZID=America/New_York:20260307T090000\nDTEND:20260307T150000Z\nRRULE:FREQ=DAILY;COUNT=4'))
    assert not items
    assert errors[0]['reason'] == 'unsupported_recurrence'


@pytest.mark.parametrize('clock,reason', [('20260308T023000', 'nonexistent_local_time'), ('20261101T013000', 'ambiguous_local_time')])
def test_unsafe_occurrence_is_explicit(clock, reason):
    items, errors = expand(calendar('DTSTART;TZID=America/New_York:' + clock + '\nRRULE:FREQ=DAILY;COUNT=1'), clock[:4] + '-' + clock[4:6] + '-01', clock[:4] + '-' + clock[4:6] + '-20')
    assert not items
    assert errors[0]['reason'] == reason


@pytest.mark.parametrize('suffix,expected', [('COUNT=2', ['2024-02-29', '2028-02-29']), ('UNTIL=20280229', ['2024-02-29', '2028-02-29'])])
def test_yearly_leap_count_until(suffix, expected):
    items, errors = expand(calendar('DTSTART;VALUE=DATE:20240229\nRRULE:FREQ=YEARLY;' + suffix), '2028-01-01', '2029-01-01')
    assert not errors
    assert [i['interval'].start for i in items] == expected[1:]


def test_cross_window_identity_for_moved_override():
    content = calendar('DTSTART:20260307T090000\nRRULE:FREQ=DAILY;COUNT=3',
                       'RECURRENCE-ID:20260308T090000\nDTSTART:20260309T120000')
    broad, _ = expand(content)
    narrow, _ = expand(content, '2026-03-09', '2026-03-10')
    moved = next(i for i in broad if i['interval'].start.endswith('12:00:00'))
    assert moved in narrow
    assert '2026-03-08T09:00:00' in moved['id']
