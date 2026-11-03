"""Task rules cannot acquire provider calendar semantics by partial parsing."""

import json
from datetime import datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest

from app import db
from app.recurrence import WEEKDAY_MAP, next_occurrence, parse_rrule


UNSUPPORTED = [
    "", "garbage", "FREQ=MONTHLY", "FREQ=YEARLY", "FREQ=DAILY;COUNT=2",
    "FREQ=WEEKLY;UNTIL=20261231T000000Z", "FREQ=DAILY;WKST=SU",
    "FREQ=DAILY;BYHOUR=9", "FREQ=WEEKLY;BYSETPOS=1", "FREQ=DAILY;X-FOO=1",
    "FREQ=DAILY;EXDATE=20261101", "FREQ=DAILY;RDATE=20261101",
    "FREQ=DAILY;BYDAY=MO", "FREQ=WEEKLY;BYDAY=1MO",
    "FREQ=WEEKLY;BYDAY=MO,BOGUS", "FREQ=WEEKLY;BYDAY=MO,",
    "FREQ=WEEKLY;BYDAY=", "FREQ=WEEKLY;BYDAY=MO,MO",
    "FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;INTERVAL=-1",
    "FREQ=DAILY;INTERVAL=+1", "FREQ=DAILY;INTERVAL=1.5",
    "FREQ=DAILY;INTERVAL=١", "FREQ=DAILY;INTERVAL=2147483648",
    "FREQ=DAILY;INTERVAL=1;INTERVAL=2", "FREQ=DAILY;FREQ=WEEKLY",
    "FREQ=DAILY;freq=DAILY", "FREQ=DAILY;", "FREQ=DAILY;BROKEN",
    "RRULE:RRULE:FREQ=DAILY", "FREQ=DAILY=", "INTERVAL=2",
    "FREQ=DAILY\nEXDATE:20261101", "RRULE:FREQ=DAILY\nRRULE:FREQ=WEEKLY",
]


@pytest.mark.parametrize("rule", UNSUPPORTED)
def test_unsupported_rules_are_not_partially_interpreted(rule):
    assert parse_rrule(rule) is None
    assert next_occurrence(rule, datetime(2026, 11, 2, 9)) is None


@pytest.mark.parametrize("rule", UNSUPPORTED)
def test_unsupported_rule_writes_are_atomic(client, rule):
    original = client.post("/api/tasks", json={"title": "Original"}).json()
    assert client.post("/api/tasks", json={"title": "Rejected", "recurrence_rule": rule}).status_code == 422
    response = client.patch(f"/api/tasks/{original['id']}", json={
        "title": "Changed", "status": "completed", "recurrence_rule": rule,
    })
    assert response.status_code == 422
    assert client.get("/api/tasks").json() == [original]


@pytest.mark.parametrize("rule", [
    "RRULE:FREQ=DAILY", "FREQ=DAILY;INTERVAL=3",
    "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "FREQ=WEEKLY;BYDAY=SA,SU",
    "FREQ=WEEKLY", " rrule: freq = weekly ; byday = mo, we ; interval = 2 ",
])
def test_supported_task_rules_keep_original_text_and_identity(client, rule):
    original = client.post("/api/tasks", json={
        "title": "Repeat", "recurrence_rule": rule,
        "deadline": {"kind": "date", "date": "2026-11-02"},
    })
    assert original.status_code == 201
    task = original.json()
    assert task["recurrence_rule"] == rule
    for status in ("completed", "todo", "completed"):
        assert client.patch(f"/api/tasks/{task['id']}", json={"status": status}).status_code == 200
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 2
    successor = next(item for item in tasks if item["id"] != task["id"])
    assert successor["recurrence_rule"] == rule
    assert successor["recurrence_series_id"] == task["recurrence_series_id"]
    assert successor["recurrence_occurrence"] == 1


def store_legacy_rule(client, task_id, rule):
    async def write():
        async with db.get_engine().begin() as conn:
            await conn.exec_driver_sql("UPDATE tasks SET recurrence_rule = ? WHERE id = ?", (rule, task_id))
    client.portal.call(write)


@pytest.mark.parametrize("rule", ["FREQ=MONTHLY", "FREQ=DAILY;COUNT=2", ""])
@pytest.mark.parametrize("resolution", ["clear", "replace"])
def test_legacy_rules_remain_readable_but_require_explicit_completion_resolution(client, rule, resolution):
    task = client.post("/api/tasks", json={"title": "Legacy", "recurrence_rule": "FREQ=DAILY"}).json()
    store_legacy_rule(client, task["id"], rule)
    url = f"/api/tasks/{task['id']}"
    legacy = client.get(url).json()
    assert legacy["recurrence_rule"] == rule
    assert client.patch(url, json={"title": "Renamed"}).status_code == 200
    before = client.get(url).json()
    assert before["recurrence_rule"] == rule
    assert client.patch(url, json={"status": "completed", "title": "Uncommitted"}).status_code == 422
    assert client.get(url).json() == before
    assert len(client.get("/api/tasks").json()) == 1
    resolved = None if resolution == "clear" else "FREQ=WEEKLY"
    response = client.patch(url, json={"status": "completed", "recurrence_rule": resolved})
    assert response.status_code == 200
    assert response.json()["recurrence_rule"] == resolved
    assert response.json()["recurrence_series_id"] == legacy["recurrence_series_id"]
    assert len(client.get("/api/tasks").json()) == (1 if resolution == "clear" else 2)


@pytest.mark.parametrize("rule", ["FREQ=DAILY;INTERVAL=2147483647", "FREQ=WEEKLY;INTERVAL=2147483647", "FREQ=DAILY"])
def test_exhausted_date_range_does_not_commit_completion(client, rule):
    task = client.post("/api/tasks", json={
        "title": "Range", "recurrence_rule": rule,
        "deadline": {"kind": "date", "date": "9999-12-31"},
    }).json()
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}).status_code == 422
    assert client.get("/api/tasks").json() == [task]


def test_weekly_interval_arithmetic_matches_monday_based_contract():
    for weekday in range(7):
        for interval in (1, 2, 7):
            for days in ("MO", "SU", "MO,WE,FR", "MO,TU,WE,TH,FR,SA,SU"):
                anchor = datetime(2026, 11, 2, 9, 15, 32, 123456) + timedelta(days=weekday)
                rule = f"FREQ=WEEKLY;INTERVAL={interval};BYDAY={days}"
                parsed = parse_rrule(rule)
                weekdays = {WEEKDAY_MAP[day] for day in parsed["byday"]}
                candidates = []
                for offset in range(1, 7 * interval + 8):
                    candidate = anchor + timedelta(days=offset)
                    matching_week = (weekday + offset) // 7 % interval == 0
                    if candidate.weekday() in weekdays and matching_week:
                        candidates.append(candidate)
                assert next_occurrence(rule, anchor) == min(candidates)


@pytest.mark.parametrize("field,value", [
    ("recurrence_rule", "FREQ=DAILY"), ("rrule", "FREQ=WEEKLY"),
    ("recurrence_id", "2026-11-02"), ("exdate", ["2026-11-03"]),
    ("uid", "provider-series"),
])
def test_blocks_reject_calendar_recurrence_instead_of_creating_task_series(client, field, value):
    task = client.post("/api/tasks", json={"title": "Task", "recurrence_rule": "FREQ=DAILY"}).json()
    body = {"task_id": task["id"], "kind": "all_day", "start_date": "2026-11-02", "end_date": "2026-11-03"}
    block = client.post("/api/time-blocks", json=body)
    assert block.status_code == 201
    original = block.json()
    assert client.post("/api/time-blocks", json={**body, field: value}).status_code == 422
    assert client.put(f"/api/time-blocks/{original['id']}", json={**body, field: value}).status_code == 422
    assert client.get("/api/time-blocks").json() == [original]
    assert client.get("/api/tasks").json() == [task]


def test_completing_task_keeps_blocks_on_original_occurrence(client):
    task = client.post("/api/tasks", json={"title": "Repeat", "recurrence_rule": "FREQ=DAILY"}).json()
    block = client.post("/api/time-blocks", json={
        "task_id": task["id"], "kind": "all_day", "start_date": "2026-11-02", "end_date": "2026-11-03",
    }).json()
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}).status_code == 200
    assert client.get("/api/time-blocks").json() == [block]
    assert len(client.get("/api/tasks").json()) == 2


def test_portable_export_preserves_unsupported_legacy_rule_and_identity(client):
    task = client.post("/api/tasks", json={"title": "Legacy", "recurrence_rule": "FREQ=DAILY"}).json()
    raw = "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=1MO"
    store_legacy_rule(client, task["id"], raw)
    response = client.post("/api/export")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        exported = json.loads(archive.read("data.json"))["tasks"]
    assert len(exported) == 1
    assert exported[0]["recurrence_rule"] == raw
    assert exported[0]["recurrence_series_id"] == task["recurrence_series_id"]
    assert exported[0]["recurrence_occurrence"] == 0


def test_rescheduling_and_removing_blocks_cannot_complete_or_clone_tasks(client):
    task = client.post("/api/tasks", json={"title": "Repeat", "recurrence_rule": "FREQ=DAILY"}).json()
    body = {"task_id": task["id"], "kind": "all_day", "start_date": "2026-11-02", "end_date": "2026-11-03"}
    block = client.post("/api/time-blocks", json=body).json()
    url = f"/api/time-blocks/{block['id']}"
    moved = client.put(url, json={**body, "start_date": "2026-11-05", "end_date": "2026-11-06"})
    assert moved.status_code == 200
    assert moved.json()["id"] == block["id"]
    assert client.get("/api/tasks").json() == [task]
    assert client.delete(url).status_code == 204
    assert client.get("/api/tasks").json() == [task]
