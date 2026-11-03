"""Payload identity permits syntax-only server rewrites, never semantic edits."""
import itertools

import pytest

from app.calendar_sync.adapter import RemoteResource
from app.calendar_sync.outbound import OutboundFailure, _payload_identity
from app.models import CalendarDispatch
from tests.test_calendar_outbound import change, env, saved


UID = 'identity@journal.local'
HEADER = ['VERSION:2.0', 'PRODID:-//Journal//EN', 'CALSCALE:GREGORIAN']
EVENT = [f'UID:{UID}', 'DTSTART;VALUE=DATE:20261101', 'DTEND;VALUE=DATE:20261102',
         'SUMMARY: Café 日記 😀  ', 'X-JOURNAL-DISPATCH:unique-marker',
         'STATUS:CONFIRMED']


def payload(header=HEADER, event=EVENT):
    return ('\r\n'.join(['BEGIN:VCALENDAR', *header, 'BEGIN:VEVENT', *event,
                          'END:VEVENT', 'END:VCALENDAR']) + '\r\n').encode()


def test_component_property_permutations():
    expected = _payload_identity(payload(), UID)
    for header in itertools.permutations(HEADER):
        for event in itertools.permutations(EVENT):
            assert _payload_identity(payload(header, event), UID) == expected


@pytest.mark.parametrize('continuation', [' ', '\t'])
def test_folding_at_every_unicode_character_boundary(continuation):
    original = payload()
    expected = _payload_identity(original, UID)
    line = EVENT[3]
    for index in range(1, len(line)):
        folded = line[:index] + '\r\n' + continuation + line[index:]
        assert _payload_identity(original.replace(line.encode(), folded.encode()), UID) == expected


@pytest.mark.parametrize('old,new', [
    (' Café', 'Café'), ('😀  ', '😀 '), ('Café', 'Café'),
    (' 日記', '\t日記'), ('unique-marker', 'other-marker'),
    ('CONFIRMED', 'TENTATIVE'), ('20261102', '20261103'),
    ('PRODID:-//Journal//EN', 'PRODID:-//Other//EN'),
    ('SUMMARY: Café', 'SUMMARY: café'),
])
def test_values_are_exact(old, new):
    original = payload()
    assert _payload_identity(original.replace(old.encode(), new.encode()), UID) != _payload_identity(original, UID)


@pytest.mark.parametrize('extra', [
    'SUMMARY:duplicate', 'SUMMARY: Café 日記 😀  ', 'UID:' + UID,
    'X-JOURNAL-DISPATCH:unique-marker', 'RRULE:FREQ=DAILY',
    'RDATE;VALUE=DATE:20261103', 'EXDATE;VALUE=DATE:20261101',
    'RECURRENCE-ID;VALUE=DATE:20261101', 'X-UNKNOWN:value',
    'BEGIN:VEVENT', 'BEGIN:VALARM',
])
def test_duplicate_or_unsupported_properties_rejected(extra):
    with pytest.raises(OutboundFailure):
        _payload_identity(payload(event=[*EVENT, extra]), UID)


@pytest.mark.parametrize('old,new', [
    ('DTSTART;VALUE=DATE', 'DTSTART;VALUE=DATE;VALUE=DATE'),
    ('DTSTART;VALUE=DATE', 'DTSTART;VALUE=DATE;TZID=UTC'),
    ('SUMMARY:', 'SUMMARY;LANGUAGE=en:'),
    ('VERSION:2.0', 'VERSION:2.0\r\nVERSION:2.0'),
    ('BEGIN:VEVENT', 'SUMMARY:wrong-component\r\nBEGIN:VEVENT'),
    ('END:VEVENT', 'END:VEVENT\r\nPRODID:wrong-component'),
    ('END:VCALENDAR', 'BEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR'),
    ('END:VCALENDAR', 'END:VCALENDAR\r\nBEGIN:VCALENDAR\r\nEND:VCALENDAR'),
    ('\r\n', '\n'), ('SUMMARY:', 'summary:'),
    ('SUMMARY:', 'SUMMARY:\x00'),
])
def test_malformed_or_cross_component_changes_rejected(old, new):
    with pytest.raises(OutboundFailure):
        _payload_identity(payload().replace(old.encode(), new.encode()), UID)


@pytest.mark.anyio
@pytest.mark.parametrize('attempted', [False, True])
async def test_reordered_remote_adopted_only_after_attempt(env, attempted):
    await env.service.prepare(env.link.id)
    row = await saved(env, CalendarDispatch)
    # Reverse properties without moving component boundaries; retain dispatch identity
    text = row.payload.replace('\r\n ', '')
    before, rest = text.split('BEGIN:VEVENT\r\n')
    event, after = rest.split('END:VEVENT\r\n')
    header = before.split('\r\n')[1:-1]
    reordered = '\r\n'.join(['BEGIN:VCALENDAR', *reversed(header), 'BEGIN:VEVENT',
                               *reversed(event.split('\r\n')[:-1]), 'END:VEVENT']) + '\r\n' + after
    env.adapter.resources[row.resource_url] = RemoteResource(row.resource_url, '"reordered"', reordered.encode())
    await change(env, CalendarDispatch, env.link.id, attempted=attempted)
    result = await env.service.dispatch(env.link.id)
    assert result.state == ('synced' if attempted else 'conflict')
    assert not any(call[0] == 'put' for call in env.adapter.calls)
