"""Opaque import identity, atomicity, context, and read-only isolation."""
import asyncio

import pytest
from sqlalchemy import text

from app import db
from app.calendar_import.parser import CalendarImportError, parse_calendar

BASE = '/api/calendar/imports'


def calendar(*events, extra=''):
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n' + extra + ''.join(
        'BEGIN:VEVENT\r\n' + e + '\r\nEND:VEVENT\r\n' for e in events
    ) + 'END:VCALENDAR\r\n'


def upload(client, content, source=None):
    target = {'kind': 'new', 'name': 'Imported'} if source is None else {'kind': 'existing', 'source_id': source}
    return client.post(BASE, json={'target': target, 'content': content})


def test_merge_explicit_replacement_omissions_sources_and_snapshots(client):
    original = calendar('UID:a\r\nSUMMARY:first\r\nSEQUENCE:90', 'UID:b')
    response = upload(client, original)
    assert response.status_code == 200, response.text
    result = response.json()
    source = result['source_id']
    assert result == {'source_id': source, 'created': 2, 'updated': 0, 'unchanged': 0}
    assert upload(client, original, source).json()['unchanged'] == 2
    changed = calendar('UID:a\r\nSUMMARY:last explicitly imported\r\nSEQUENCE:1')
    assert upload(client, changed, source).json()['updated'] == 1
    events = client.get(f'{BASE}/{source}/events').json()
    assert len(events) == 2
    assert events[0]['summary'] == 'last explicitly imported'
    assert events[0]['representation'] == 'opaque'
    assert events[0]['recurrence_kind'] == 'master'
    other = upload(client, original).json()['source_id']
    assert other != source
    assert len(client.get(BASE).json()) == 2
    assert {r['event_count'] for r in client.get(BASE).json()} == {2}
    snapshots = client.get(f'{BASE}/{source}/snapshots').json()
    assert [s['content'] for s in snapshots] == [original, original, changed]


def test_typed_recurrence_identity_without_expansion(client):
    events = ['UID:series\r\nDTSTART:20260101T120000\r\nRRULE:FREQ=DAILY;COUNT=1000000\r\n'
              'RDATE:20261201T120000\r\nEXDATE:20260102T120000']
    for rid in [';VALUE=DATE:20260101', ':20260101T120000Z', ';TZID=UTC:20260101T120000',
                ';TZID=Custom:20260101T120000', ':20260101T120000']:
        events.append('UID:series\r\nRECURRENCE-ID' + rid + '\r\nSTATUS:CANCELLED')
    content = calendar(*events)
    response = upload(client, content)
    assert response.status_code == 200, response.text
    source = response.json()['source_id']
    rows = client.get(f'{BASE}/{source}/events').json()
    assert len(rows) == 6
    assert {e['recurrence_kind'] for e in rows} == {'master', 'date', 'utc', 'local', 'floating'}
    assert {e['recurrence_time_zone'] for e in rows if e['recurrence_kind'] == 'local'} == {'UTC', 'Custom'}
    assert all(e['recurrence_id'] == '20260101T120000' for e in rows if e['recurrence_kind'] == 'local')
    assert sum(e['has_recurrence'] for e in rows) == 1
    assert sum(e['status'] == 'CANCELLED' for e in rows) == 5


def test_unknown_properties_timezones_alarms_range_and_exact_original(client):
    timezone = ('BEGIN:VTIMEZONE\r\nTZID:Custom\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\n'
                'TZOFFSETFROM:+0530\r\nTZOFFSETTO:+0530\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n')
    event = ('UID:opaque\r\nRECURRENCE-ID;TZID=Custom;RANGE=THISANDFUTURE:20260101T120000\r\n'
             'DTSTART;TZID=Custom:20260101T130000\r\nX-UNKNOWN;X-PARAM=secret:opaque\r\n'
             'SUMMARY:folded\r\n text\r\nATTACH:https://example.invalid/private\r\n'
             'BEGIN:VALARM\r\nACTION:PROCEDURE\r\nATTACH:file:///never-execute\r\nTRIGGER:-PT5M\r\nEND:VALARM')
    content = calendar(event, extra=timezone)
    source = upload(client, content).json()['source_id']
    assert client.get(f'{BASE}/{source}/snapshots').json()[0]['content'] == content
    assert client.get(f'{BASE}/{source}/events').json()[0]['start_value'] == '20260101T130000'
    assert upload(client, content.replace('+0530', '+0600'), source).json()['updated'] == 1


@pytest.mark.parametrize('content', [
    '', 'BEGIN:VCALENDAR\nVERSION:2.0', calendar('UID:a') + 'junk',
    calendar('UID:a').replace('END:VEVENT', 'END:VTODO'),
    calendar('UID:a') + calendar('UID:b'), calendar('UID:a', 'UID:a'),
    calendar('UID:a\r\nRECURRENCE-ID:20260101T120000', 'UID:a\r\nRECURRENCE-ID:20260101T120000'),
    calendar('SUMMARY:no UID'), calendar('UID:a\r\nUID:b'),
    calendar('UID:a\r\nDTSTART:20260230'), calendar('UID:a\r\nDTEND:invalid'),
    calendar('UID:a\r\nRDATE:invalid'), calendar('UID:a\r\nEXDATE:20261340'),
    calendar('UID:a\r\nRRULE:FREQ=NOPE'), calendar('UID:a\r\nRRULE:FREQ=DAILY;BYMONTH=99'),
    calendar('UID:a\r\nRRULE:FREQ=DAILY;BYDAY=99MO'),
    calendar('UID:a\r\nRRULE:FREQ=DAILY;BYDAY=0MO'),
    calendar('UID:a\r\nRRULE:FREQ=DAILY;FREQ=WEEKLY'),
    calendar('UID:a\r\nRRULE:FREQ=DAILY;INTERVAL=0'), calendar('UID:a\r\nRRULE:COUNT=3'),
    calendar('UID:a\r\nRRULE:FREQ=DAILY;COUNT=1;UNTIL=20260101'),
    calendar('UID:a').replace('VEVENT', 'VTODO'), calendar('UID:a').replace('VEVENT', 'VJOURNAL'),
])
def test_invalid_upload_rejected_atomically(client, content):
    original = calendar('UID:existing')
    source = upload(client, original).json()['source_id']
    before = client.get(BASE).json()
    assert upload(client, content, source).status_code == 422
    assert upload(client, content).status_code == 422
    assert client.get(BASE).json() == before
    assert len(client.get(f'{BASE}/{source}/snapshots').json()) == 1
    assert len(client.get(f'{BASE}/{source}/events').json()) == 1


def test_delete_cascades_and_no_operational_writes(client):
    source = upload(client, calendar('UID:a\r\nDTSTART:20260101T120000Z')).json()['source_id']

    async def counts():
        async with db.get_sessionmaker()() as session:
            return {t: (await session.exec(text(f'SELECT count(*) FROM {t}'))).scalar_one()
                    for t in ['calendar_import_sources', 'calendar_import_events', 'calendar_import_snapshots',
                              'tasks', 'time_blocks', 'daily_scores', 'calendar_links', 'calendar_dispatches']}

    assert all(v == 0 for k, v in asyncio.run(counts()).items() if not k.startswith('calendar_import'))
    assert client.delete(f'{BASE}/{source}').status_code == 204
    assert all(v == 0 for v in asyncio.run(counts()).values())
    for suffix in ('events', 'snapshots'):
        assert client.get(f'{BASE}/{source}/{suffix}').status_code == 404
    assert upload(client, calendar('UID:a'), source).status_code == 404
    assert client.delete(f'{BASE}/{source}').status_code == 404


def test_all_day_floating_and_utc_start_values_are_not_materialized():
    for value, end, params in [('20260101', '20260102', ';VALUE=DATE'),
                               ('20260101T120000', '20260101T130000', ''),
                               ('20260101T120000Z', '20260101T130000Z', '')]:
        parsed = parse_calendar(calendar(f'UID:a\r\nDTSTART{params}:{value}\r\nDTEND{params}:{end}'))
        assert parsed.events[0].start_value == value
        assert parsed.events[0].end_value == end


@pytest.mark.parametrize('body', [
    'UID:a\r\nBEGIN:VTODO\r\nUID:todo\r\nEND:VTODO',
    'UID:a\r\nBEGIN:VEVENT\r\nUID:nested\r\nEND:VEVENT',
    'UID:a\r\nBEGIN:VTIMEZONE\r\nTZID:nested\r\nEND:VTIMEZONE',
    'UID:a\r\nRECURRENCE-ID;VALUE=DATE:20260101T120000',
    'UID:a\r\nRECURRENCE-ID;TZID=UTC:20260101T120000Z',
    'UID:a\r\nRECURRENCE-ID;TZID=UTC;VALUE=DATE:20260101',
    'UID:a\r\nDTSTART;VALUE=DATE:20260101T120000',
    'UID:a\r\nDTSTART;TZID=UTC:20260101T120000Z',
    'UID:a\r\nDTSTART:20260101',
    'UID:a\r\nRRULE:FREQ=DAILY;BOGUS=YES',
    'UID:a\r\nDTSTART:20260101T120000Z\r\nDTEND:20260101T110000Z',
    'UID:a\r\nDTSTART:20260101T120000\r\nDTEND:20260101T120000',
    'UID:a\r\nDTSTART;TZID=Custom:20260101T120000\r\nDTEND;TZID=Custom:20260101T110000',
    'UID:a\r\nDTSTART;VALUE=DATE:20260102\r\nDTEND;VALUE=DATE:20260101',
    'UID:a\r\nDTSTART;VALUE=DATE:20260101\r\nDTEND:20260101T120000',
    'UID:a\r\nDTEND:20260101T130000\r\nDURATION:PT1H',
])
def test_hierarchy_typed_values_and_comparable_intervals_rejected_atomically(client, body):
    source = upload(client, calendar('UID:existing')).json()['source_id']
    response = upload(client, calendar(body), source)
    assert response.status_code == 422, response.text
    assert len(client.get(f'{BASE}/{source}/snapshots').json()) == 1
    assert client.get(f'{BASE}/{source}/events').json()[0]['uid'] == 'existing'


def test_bom_and_start_vs_recurrence_timezones(client):
    content = '\ufeff' + calendar('UID:a\r\nDTSTART;TZID=America/New_York:20260101T120000\r\n'
                                  'RECURRENCE-ID;TZID=Europe/London:20260101T120000')
    response = upload(client, content)
    assert response.status_code == 200, response.text
    source = response.json()['source_id']
    row = client.get(f'{BASE}/{source}/events').json()[0]
    assert row['time_zone'] == 'America/New_York'
    assert row['recurrence_time_zone'] == 'Europe/London'
    assert row['start_kind'] == 'local'
    assert row['recurrence_kind'] == 'local'
    assert client.get(f'{BASE}/{source}/snapshots').json()[0]['content'] == content
    master = upload(client, calendar('UID:master\r\nDTSTART;TZID=America/New_York:20260101T120000'), source)
    assert master.status_code == 200
    row = next(r for r in client.get(f'{BASE}/{source}/events').json() if r['uid'] == 'master')
    assert row['time_zone'] == 'America/New_York'
    assert row['recurrence_time_zone'] is None
    assert row['recurrence_kind'] == 'master'


def test_cross_zone_intervals_are_not_resolved_and_rule_extensions_retained():
    content = calendar('UID:a\r\nDTSTART;TZID=Custom-A:20260101T120000\r\n'
                       'DTEND;TZID=Custom-B:20260101T110000\r\nRRULE:FREQ=DAILY;X-FUTURE=opaque')
    assert parse_calendar(content).events[0].start_value == '20260101T120000'


def test_storage_failure_rolls_back_source_snapshot_and_all_events(client):
    from sqlalchemy.exc import IntegrityError

    async def reject_second_event():
        async with db.get_sessionmaker()() as session:
            await session.exec(text("CREATE TRIGGER fail_import BEFORE INSERT ON calendar_import_events "
                                    "WHEN NEW.uid='fail' BEGIN SELECT RAISE(ABORT,'injected failure'); END"))
            await session.commit()

    asyncio.run(reject_second_event())
    with pytest.raises(IntegrityError, match='injected failure'):
        upload(client, calendar('UID:good', 'UID:fail'))
    assert client.get(BASE).json() == []

    async def counts():
        async with db.get_sessionmaker()() as session:
            return [(await session.exec(text(f'SELECT count(*) FROM {table}'))).scalar_one()
                    for table in ('calendar_import_sources', 'calendar_import_snapshots', 'calendar_import_events')]

    assert asyncio.run(counts()) == [0, 0, 0]
