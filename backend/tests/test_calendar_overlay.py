"""Standalone overlay API contracts; imported data never becomes tasks."""
import pytest

from test_calendar_import import BASE, calendar, upload


def project(client, *events, extra=''):
    response = upload(client, calendar(*events, extra=extra))
    assert response.status_code == 200, response.text
    source = response.json()['source_id']
    response = client.get(f'{BASE}/{source}/overlay')
    assert response.status_code == 200, response.text
    return source, response.json()


@pytest.mark.parametrize(('properties', 'expected'), [
    ('DTSTART;VALUE=DATE:20260131', {'kind': 'date', 'start': '2026-01-31', 'end': '2026-02-01'}),
    ('DTSTART;VALUE=DATE:20260131\r\nDTEND;VALUE=DATE:20260203',
     {'kind': 'date', 'start': '2026-01-31', 'end': '2026-02-03'}),
    ('DTSTART:20260101T120000Z', {'kind': 'timed', 'start': '2026-01-01T12:00:00Z', 'end': '2026-01-01T12:00:00Z'}),
    ('DTSTART:20260101T120000\r\nDTEND:20260101T130000',
     {'kind': 'floating', 'start': '2026-01-01T12:00:00', 'end': '2026-01-01T13:00:00'}),
    ('DTSTART:20260101T120000', {'kind': 'floating', 'start': '2026-01-01T12:00:00', 'end': '2026-01-01T12:00:00'}),
    ('DTSTART;TZID=America/New_York:20260308T013000\r\nDTEND;TZID=America/New_York:20260308T033000',
     {'kind': 'timed', 'start': '2026-03-08T06:30:00Z', 'end': '2026-03-08T07:30:00Z'}),
    ('DTSTART;TZID=Asia/Kolkata:20260101T120000\r\nDTEND:20260101T070000Z',
     {'kind': 'timed', 'start': '2026-01-01T06:30:00Z', 'end': '2026-01-01T07:00:00Z'}),
])
def test_intervals(client, properties, expected):
    source, data = project(client, 'UID:a\r\nSUMMARY:hello\r\nSTATUS:TENTATIVE\r\n' + properties)
    assert data['unplaced'] == []
    item = data['items'][0]
    assert item['interval'] == expected
    assert item['source_id'] == source
    assert item['uid'] == 'a'
    assert item['status'] == 'TENTATIVE'
    assert item['id'] == client.get(f'{BASE}/{source}/events').json()[0]['id']


@pytest.mark.parametrize(('properties', 'reason'), [
    ('', 'missing_start'),
    ('DTSTART:20260101T120000Z\r\nSTATUS:CANCELLED', 'cancelled'),
    ('DTSTART:20260101T120000Z\r\nRRULE:FREQ=DAILY', 'recurrence'),
    ('DTSTART:20260101T120000Z\r\nRDATE:20260102T120000Z', 'recurrence'),
    ('DTSTART:20260101T120000Z\r\nEXDATE:20260102T120000Z', 'recurrence'),
    ('DTSTART:20260101T120000Z\r\nRECURRENCE-ID:20260101T120000Z', 'recurrence'),
    ('DTSTART;TZID=No/Such_Zone:20260101T120000', 'unknown_timezone'),
    ('DTSTART:20260101T120000\r\nDTEND:20260101T130000Z', 'incomparable_interval'),
    ('DTSTART;TZID=Asia/Kolkata:20260101T120000\r\nDTEND:20260101T060000Z', 'invalid_interval'),
    ('DTSTART:20260101T120000Z\r\nDURATION:PT1H', 'unsupported_duration'),
    ('DTSTART;VALUE=DATE:20260101\r\nDURATION:P1D', 'unsupported_duration'),
    ('DTSTART;TZID=America/New_York:20260308T023000', 'nonexistent_local_time'),
    ('DTSTART;TZID=America/New_York:20261101T013000', 'ambiguous_local_time'),
])
def test_unplaced(client, properties, reason):
    _, data = project(client, 'UID:a\r\n' + properties)
    assert data['items'] == []
    assert data['unplaced'][0]['reason'] == reason


def test_exception_blocks_apparently_standalone_master_and_no_expansion(client):
    _, data = project(client, 'UID:a\r\nDTSTART:20260101T120000Z',
                      'UID:a\r\nRECURRENCE-ID:20260102T120000Z\r\nDTSTART:20260102T130000Z',
                      'UID:b\r\nDTSTART:20260101T120000Z\r\nRRULE:FREQ=SECONDLY;COUNT=1000000000')
    assert data['items'] == []
    assert len(data['unplaced']) == 3
    assert {r['reason'] for r in data['unplaced']} == {'recurrence'}


def test_read_only_private_and_source_deletion(client):
    before = {path: client.get(path).json() for path in ['/api/tasks', '/api/time-blocks', '/api/journal/days']}
    source, data = project(client, 'UID:a\r\nDTSTART:20260101T120000Z\r\nDESCRIPTION:private-secret\r\n'
                           'ATTACH:https://example.invalid/never-fetch\r\nBEGIN:VALARM\r\nACTION:PROCEDURE\r\n'
                           'TRIGGER:-PT5M\r\nATTACH:file:///never-execute\r\nEND:VALARM')
    snapshots = client.get(f'{BASE}/{source}/snapshots').json()
    sources = client.get(BASE).json()
    assert 'private-secret' not in str(data)
    assert 'never-fetch' not in str(data)
    assert client.get(f'{BASE}/{source}/overlay').json() == data
    assert client.get(f'{BASE}/{source}/snapshots').json() == snapshots
    assert client.get(BASE).json() == sources
    assert {path: client.get(path).json() for path in before} == before
    assert client.delete(f'{BASE}/{source}').status_code == 204
    assert client.get(f'{BASE}/{source}/overlay').status_code == 404
    assert client.get(f'{BASE}/missing/overlay').status_code == 404


def test_custom_timezone_uses_event_snapshot_context(client):
    zone = ('BEGIN:VTIMEZONE\r\nTZID:Overlay/Custom\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\n'
            'TZOFFSETFROM:+0530\r\nTZOFFSETTO:+0530\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n')
    source, data = project(client, 'UID:a\r\nDTSTART;TZID=Overlay/Custom:20260101T120000', extra=zone)
    assert data['items'][0]['interval']['start'] == '2026-01-01T06:30:00Z'
    response = upload(client, calendar('UID:b\r\nDTSTART:20260101T120000Z'), source)
    assert response.status_code == 200
    assert client.get(f'{BASE}/{source}/overlay').json()['items'][0]['interval']['start'] == '2026-01-01T06:30:00Z'


@pytest.mark.parametrize('duration', ['-PT1H', 'P1W', 'PT0S', 'P1DT2H'])
def test_duration_never_silently_dropped(client, duration):
    _, data = project(client, f'UID:a\r\nDTSTART:20260101T120000Z\r\nDURATION:{duration}')
    assert data['items'] == []
    assert data['unplaced'][0]['reason'] == 'unsupported_duration'


def custom_zone(tzid, offset):
    return (f'BEGIN:VTIMEZONE\r\nTZID:{tzid}\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\n'
            f'TZOFFSETFROM:{offset}\r\nTZOFFSETTO:{offset}\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n')


def test_snapshot_zone_definitions_are_isolated_across_sources_and_reimports(client):
    tzid = 'Overlay/SnapshotIsolation'
    event = f'UID:a\r\nDTSTART;TZID={tzid}:20260101T120000'
    first, data = project(client, event, extra=custom_zone(tzid, '+0530'))
    assert data['items'][0]['interval']['start'] == '2026-01-01T06:30:00Z'
    second, data = project(client, event, extra=custom_zone(tzid, '+0200'))
    assert data['items'][0]['interval']['start'] == '2026-01-01T10:00:00Z'
    assert client.get(f'{BASE}/{first}/overlay').json()['items'][0]['interval']['start'] == '2026-01-01T06:30:00Z'
    response = upload(client, calendar(event, extra=custom_zone(tzid, '+0300')), first)
    assert response.status_code == 200
    assert client.get(f'{BASE}/{first}/overlay').json()['items'][0]['interval']['start'] == '2026-01-01T09:00:00Z'
    assert client.get(f'{BASE}/{second}/overlay').json()['items'][0]['interval']['start'] == '2026-01-01T10:00:00Z'


def test_snapshot_zone_definition_takes_precedence_over_iana_registry(client):
    _, data = project(client, 'UID:a\r\nDTSTART;TZID=Asia/Kolkata:20260101T120000',
                      extra=custom_zone('Asia/Kolkata', '+0200'))
    assert data['items'][0]['interval']['start'] == '2026-01-01T10:00:00Z'


def test_timezone_absent_from_snapshot_cannot_leak_from_another_source(client):
    tzid = 'Overlay/AbsentFromSnapshot'
    project(client, f'UID:a\r\nDTSTART;TZID={tzid}:20260101T120000',
            extra=custom_zone(tzid, '+0530'))
    _, data = project(client, f'UID:a\r\nDTSTART;TZID={tzid}:20260101T120000')
    assert data['items'] == []
    assert data['unplaced'][0]['reason'] == 'unknown_timezone'


def test_retained_events_use_their_own_snapshot_zone_definitions(client):
    tzid = 'Overlay/RetainedSnapshot'
    source, _ = project(client, f'UID:a\r\nDTSTART;TZID={tzid}:20260101T120000',
                        extra=custom_zone(tzid, '+0530'))
    response = upload(client, calendar(f'UID:b\r\nDTSTART;TZID={tzid}:20260101T120000',
                                      extra=custom_zone(tzid, '+0200')), source)
    assert response.status_code == 200
    data = client.get(f'{BASE}/{source}/overlay').json()
    assert {item['uid']: item['interval']['start'] for item in data['items']} == {
        'a': '2026-01-01T06:30:00Z', 'b': '2026-01-01T10:00:00Z',
    }


def test_original_timezone_parameters_survive_library_utc_canonicalization(client):
    _, data = project(client, 'UID:a\r\nDTSTART;TZID=UTC:20260101T120000\r\n'
                      'DTEND;TZID=UTC:20260101T130000', extra=custom_zone('UTC', '+0200'))
    assert data['unplaced'] == []
    assert data['items'][0]['interval'] == {
        'kind': 'timed', 'start': '2026-01-01T10:00:00Z', 'end': '2026-01-01T11:00:00Z',
    }


def test_reimport_detects_changed_original_clock_parameters(client):
    zone = custom_zone('UTC', '+0200')
    source, data = project(client, 'UID:a\r\nDTSTART:20260101T090000Z\r\n'
                           'DTEND;TZID=UTC:20260101T140000', extra=zone)
    assert data['items'][0]['interval']['end'] == '2026-01-01T12:00:00Z'
    response = upload(client, calendar('UID:a\r\nDTSTART:20260101T090000Z\r\n'
                                      'DTEND:20260101T140000Z', extra=zone), source)
    assert response.status_code == 200
    assert response.json()['updated'] == 1
    data = client.get(f'{BASE}/{source}/overlay').json()
    assert data['items'][0]['interval']['end'] == '2026-01-01T14:00:00Z'
