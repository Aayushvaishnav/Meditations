from datetime import date, datetime

import pytest

from app.calendar_export import serialize_calendar
from app.calendar_sync.outbound import OutboundFailure, _member, _validate
from app.models import CalendarConnection, Task, TimeBlock


@pytest.fixture
def event():
    block = TimeBlock(id='block', task_id='task', kind='all_day', timezone=None,
                      start_date=date(2026, 11, 1), end_date=date(2026, 11, 3))
    payload = serialize_calendar([(block, Task(id='task', title='Café, read; rest'))],
                                 exported_at=datetime(2026, 11, 1))
    uid = next(line[4:] for line in payload.replace('\r\n ', '').split('\r\n') if line.startswith('UID:'))
    return payload, uid


def test_supported_projection_and_folded_unicode(event):
    payload, uid = event
    _validate(payload.encode(), uid)
    _validate(payload.replace('SUMMARY:Café', 'SUMMARY:Ca\r\n fé').encode(), uid)


@pytest.mark.parametrize('extra', [
    'RRULE:FREQ=DAILY', 'RDATE;VALUE=DATE:20261104', 'EXDATE;VALUE=DATE:20261102',
    'RECURRENCE-ID;VALUE=DATE:20261101', 'ATTENDEE:mailto:person@example.test',
    'ORGANIZER:mailto:person@example.test', 'BEGIN:VALARM', 'BEGIN:VEVENT',
    'X-UNKNOWN:unsupported', 'UID:duplicate', 'SUMMARY:duplicate',
    'DTSTART;VALUE=DATE:20261101', 'DESCRIPTION:external private content',
])
def test_unsupported_remote_semantics_fail_closed(event, extra):
    payload, uid = event
    with pytest.raises(OutboundFailure):
        _validate(payload.replace('END:VEVENT', extra + '\r\nEND:VEVENT').encode(), uid)


@pytest.mark.parametrize('old,new', [
    ('VERSION:2.0', 'VERSION:1.0'),
    ('VERSION:2.0\r\n', ''),
    ('20261101', '20261301'),
    ('DTSTART;VALUE=DATE:20261101', 'DTSTART;VALUE=DATE:'),
    ('DTEND;VALUE=DATE:20261103', 'DTEND;VALUE=DATE:20261031'),
    ('DTEND;VALUE=DATE:20261103', 'DTEND:20261103T000000Z'),
    ('DTSTAMP:20261101T000000Z', 'DTSTAMP:invalid'),
    ('STATUS:CONFIRMED', 'STATUS:unknown'),
    ('SUMMARY:Café', 'SUMMARY:Ca\x00fé'),
    ('END:VCALENDAR\r\n', 'END:VCALENDAR'),
    ('\r\n', '\n'),
])
def test_malformed_remote_content_is_rejected(event, old, new):
    payload, uid = event
    with pytest.raises(OutboundFailure):
        _validate(payload.replace(old, new).encode(), uid)


def test_wrong_uid_or_multiple_events_are_rejected(event):
    payload, uid = event
    with pytest.raises(OutboundFailure):
        _validate(payload.encode(), 'different-uid')
    event_body = payload[payload.index('BEGIN:VEVENT'):payload.index('END:VCALENDAR')]
    with pytest.raises(OutboundFailure):
        _validate(payload.replace('END:VCALENDAR', event_body + 'END:VCALENDAR').encode(), uid)


@pytest.mark.parametrize('target', [
    'https://other.test/events/a.ics', 'http://calendar.test/events/a.ics',
    'https://calendar.test/other/a.ics', 'https://calendar.test/events2/a.ics',
    'https://calendar.test/events/', 'https://calendar.test/events/a/b.ics',
    'https://calendar.test/events/../a.ics', 'https://calendar.test/events/%2e%2e',
    'https://calendar.test/events/a%2fb.ics', 'https://calendar.test/events/a%5cb.ics',
    'https://calendar.test/events/a.ics?replace=other',
    'https://calendar.test/events/a.ics#fragment',
    'https://user:secret@calendar.test/events/a.ics',
    'https://calendar.test/events/a%0ab.ics',
    'https://calendar.test:8443/events/a.ics',
])
def test_only_recorded_calendar_immediate_members_are_writable(target):
    connection = CalendarConnection(server_url='https://calendar.test/',
                                    calendar_url='https://calendar.test/events/')
    with pytest.raises(OutboundFailure):
        _member(connection, target)


@pytest.mark.parametrize('target', [
    'https://calendar.test/events/a.ics', 'https://calendar.test:443/events/a.ics',
    'https://calendar.test/events/caf%C3%A9.ics',
])
def test_valid_selected_members(target):
    _member(CalendarConnection(server_url='https://calendar.test/',
                               calendar_url='https://calendar.test/events/'), target)
