from datetime import date, datetime, timezone, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.calendar_export import escape_text, serialize_calendar
from app.models import Task, TimeBlock

URL = '/api/calendar/export'


def setup_block(client, **overrides):
    task = client.post('/api/tasks', json={
        'title': '😀é界' * 80 + '\\,;\r\nEND:VEVENT\rBEGIN:VEVENT',
        'description': 'PRIVATE', 'recurrence_rule': 'FREQ=DAILY',
        'due_date': '2026-12-01T12:00:00',
    }).json()
    payload = {'task_id': task['id'], 'start_at': '2026-03-08T09:00:00.123+05:30',
               'end_at': '2026-03-08T10:00:00.456+05:30', 'timezone': 'America/New_York', **overrides}
    response = client.post('/api/time-blocks', json=payload)
    assert response.status_code == 201, response.text
    return task, response.json()


def export(client, ids):
    return client.post(URL, json={'block_ids': ids})


def test_snapshot_privacy_folding_offsets_and_immutability(client):
    task, block = setup_block(client)
    second = client.post('/api/time-blocks', json={'task_id': task['id'],
        'start_at': '2026-03-09T09:00:00', 'end_at': '2026-03-09T10:00:00'}).json()
    before_tasks = client.get('/api/tasks').json()
    before_blocks = client.get('/api/time-blocks').json()
    response = export(client, [second['id'], block['id'], second['id']])
    assert response.status_code == 200
    assert response.headers['content-type'] == 'text/calendar; charset=utf-8'
    assert response.headers['content-disposition'] == 'attachment; filename="meditations-calendar.ics"'
    raw = response.content
    assert raw.endswith(b'\r\n')
    assert b'\n' not in raw.replace(b'\r\n', b'')
    for line in raw.split(b'\r\n'):
        assert len(line) <= 75
        line.decode('utf-8')
    assert b'\r\n ' in raw
    text = response.text.replace('\r\n ', '')
    assert text.count('\r\nBEGIN:VEVENT\r\n') == 2
    ids = sorted([block['id'], second['id']])
    assert text.index(str(uuid5(NAMESPACE_URL, f'journal:time-block:{ids[0]}'))) < text.index(str(uuid5(NAMESPACE_URL, f'journal:time-block:{ids[1]}')))
    assert 'DTSTART:20260308T033000Z' in text
    assert 'DTEND:20260308T043000Z' in text
    assert 'X-JOURNAL-TIMEZONE:America/New_York' in text
    assert '\\\\\\,\\;\\nEND:VEVENT\\nBEGIN:VEVENT' in text
    for forbidden in ('PRIVATE', 'DESCRIPTION', 'RRULE', 'DUE', '20261201', 'CREDENTIAL'):
        assert forbidden not in text
    assert client.get('/api/tasks').json() == before_tasks
    assert client.get('/api/time-blocks').json() == before_blocks


@pytest.mark.parametrize('status,expected', [('todo', 'CONFIRMED'), ('completed', 'CONFIRMED'), ('canceled', 'CANCELLED')])
def test_status_uid_update_and_all_day_dst_labels(client, status, expected):
    task, block = setup_block(client)
    client.patch(f'/api/tasks/{task["id"]}', json={'status': status})
    identity = uuid5(NAMESPACE_URL, f'journal:time-block:{block["id"]}')
    uid = f'UID:meditations-time-block-{identity}@journal.local'
    assert uid in export(client, [block['id']]).text.replace('\r\n ', '')
    response = client.put(f'/api/time-blocks/{block["id"]}', json={
        'task_id': task['id'], 'kind': 'all_day', 'start_date': '2026-03-08', 'end_date': '2026-03-10'})
    assert response.status_code == 200
    text = export(client, [block['id']]).text.replace('\r\n ', '')
    assert uid in text
    assert f'STATUS:{expected}' in text
    assert 'DTSTART;VALUE=DATE:20260308\r\nDTEND;VALUE=DATE:20260310' in text
    assert 'X-JOURNAL-TIMEZONE' not in text


@pytest.mark.parametrize('payload', [None, {}, [], {'block_ids': []}, {'block_ids': None},
    {'block_ids': 'abc'}, {'block_ids': [1]}, {'block_ids': [True]}, {'block_ids': ['']},
    {'block_ids': [None]}, {'block_ids': ['id'], 'extra': 1}])
def test_strict_request(client, payload):
    assert client.post(URL, json=payload).status_code == 422


def test_missing_atomic(client):
    _, block = setup_block(client)
    response = export(client, [block['id'], 'missing'])
    assert response.status_code == 404
    assert 'BEGIN:VCALENDAR' not in response.text


def test_subsecond_rejection(client):
    _, block = setup_block(client, start_at='2026-01-01T00:00:00.1Z', end_at='2026-01-01T00:00:00.9Z')
    response = export(client, [block['id']])
    assert response.status_code == 422
    assert 'second precision' in response.text
    assert client.get(f'/api/time-blocks/{block["id"]}').json() == block


def test_aware_instants_and_unsafe_uid():
    zone = timezone(timedelta(hours=5, minutes=30))
    block = TimeBlock(id='bad\r\nSUMMARY:hijack', task_id='task',
        start_at=datetime(2026, 1, 1, 9, tzinfo=zone), end_at=datetime(2026, 1, 1, 10, tzinfo=zone))
    text = serialize_calendar([(block, Task(id='task', title='Title'))],
        exported_at=datetime(2026, 1, 1, 9, tzinfo=zone))
    assert 'DTSTART:20260101T033000Z' in text
    assert 'DTSTAMP:20260101T033000Z' in text
    assert 'hijack' not in text


@pytest.mark.parametrize('code', [*range(9), 11, 12, *range(14, 32), 127])
@pytest.mark.parametrize('field', ['title', 'timezone'])
def test_forbidden_text_controls(code, field):
    task = Task(id='task', title='Title')
    block = TimeBlock(id='block', task_id='task',
        start_at=datetime(2026, 1, 1), end_at=datetime(2026, 1, 2))
    setattr(task if field == 'title' else block, field, f'before{chr(code)}after')
    with pytest.raises(ValueError, match='forbidden control'):
        serialize_calendar([(block, task)], exported_at=datetime(2026, 1, 1))


def test_allowed_text_whitespace_and_escaping():
    assert escape_text('a\tb\r\nc\rd\ne\\f;g,h') == 'a\tb\\nc\\nd\\ne\\\\f\\;g\\,h'


@pytest.mark.parametrize('year', [1, 9, 99, 999, 9999])
@pytest.mark.parametrize('kind', ['timed', 'all_day'])
def test_extreme_years(year, kind):
    block = TimeBlock(id='block', task_id='task', kind=kind,
        start_at=datetime(year, 12, 30, 23, 59, 58),
        end_at=datetime(year, 12, 31, 23, 59, 59),
        start_date=date(year, 12, 30), end_date=date(year, 12, 31),
        created_at=datetime(year, 1, 1), updated_at=datetime(year, 1, 1))
    task = Task(id='task', title='Title', updated_at=datetime(year, 1, 1))
    text = serialize_calendar([(block, task)], exported_at=datetime(year, 1, 1)).replace('\r\n ', '')
    prefix = f'{year:04d}'
    assert f'DTSTAMP:{prefix}0101T000000Z' in text
    if kind == 'all_day':
        assert f'DTSTART;VALUE=DATE:{prefix}1230' in text
        assert f'DTEND;VALUE=DATE:{prefix}1231' in text
    else:
        assert f'DTSTART:{prefix}1230T235958Z' in text
        assert f'DTEND:{prefix}1231T235959Z' in text


def test_uid_stability_and_latest_normalized_modification():
    block = TimeBlock(id='block', task_id='task',
        start_at=datetime(2026, 1, 1), end_at=datetime(2026, 1, 2),
        updated_at=datetime(2026, 1, 1, 9))
    task = Task(id='task', title='Original', updated_at=datetime(2026, 1, 1, 8))
    uid = f'UID:meditations-time-block-{uuid5(NAMESPACE_URL, "journal:time-block:block")}@journal.local'
    for title, status, updated, expected in [
        ('Original', 'todo', datetime(2026, 1, 1, 8), '090000'),
        ('Renamed', 'todo', datetime(2026, 1, 1, 10), '100000'),
        ('Renamed', 'canceled', datetime(2026, 1, 1, 16, tzinfo=timezone(timedelta(hours=5))), '110000'),
    ]:
        task.title, task.status, task.updated_at = title, status, updated
        text = serialize_calendar([(block, task)], exported_at=datetime(2026, 1, 2)).replace('\r\n ', '')
        assert uid in text
        assert f'SUMMARY:{title}' in text
        assert f'LAST-MODIFIED:20260101T{expected}Z' in text
        assert ('STATUS:CANCELLED' if status == 'canceled' else 'STATUS:CONFIRMED') in text
