from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app import db

NOW = datetime(2026, 11, 5, 10, 30, 12, 345678)


@pytest.fixture(autouse=True)
def freeze_completion_time(monkeypatch):
    monkeypatch.setattr("app.routers.tasks.utc_now", lambda: NOW)


def create_completed(client, **fields):
    response = client.post("/api/tasks", json={
        "title": "Already finished", "status": "completed", **fields,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_completed_creation_persists_timestamp_and_counts_in_telemetry(client):
    task = create_completed(client)
    assert task["completed_at"] == NOW.isoformat()
    assert client.get(f"/api/tasks/{task['id']}").json() == task
    metrics = client.get(f"/api/scores/daily/{NOW.date()}").json()["metrics"]
    assert metrics["tasks_completed"] == 1


@pytest.mark.parametrize("deadline, expected", [
    ({"due_date": "2026-11-05T09:00:00"}, "2026-11-06T09:00:00"),
    ({"deadline": {"kind": "date", "date": "2026-11-05"}}, "2026-11-06"),
    ({}, "2026-11-06T10:30:12.345678"),
])
def test_completed_recurring_creation_spawns_one_configured_successor(client, deadline, expected):
    task = create_completed(
        client, recurrence_rule="RRULE:FREQ=DAILY", priority=3,
        importance="important", urgency="not_urgent", tags=["review"], **deadline,
    )
    assert task["completed_at"] == NOW.isoformat()
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 2
    successor = next(row for row in tasks if row["id"] != task["id"])
    assert task["recurrence_series_id"] == task["id"]
    assert task["recurrence_occurrence"] == 0
    assert successor["recurrence_series_id"] == task["id"]
    assert successor["recurrence_occurrence"] == 1
    assert successor["status"] == "todo"
    assert successor["completed_at"] is None
    for field in ("title", "priority", "importance", "urgency", "tags", "recurrence_rule"):
        assert successor[field] == task[field]
    if "deadline" in deadline:
        assert successor["deadline"] == {"kind": "date", "date": expected}
    else:
        assert successor["due_date"] == expected


@pytest.mark.parametrize("status", ["todo", "in_progress", "canceled"])
def test_noncompleted_creation_has_no_completion_or_successor(client, status):
    response = client.post("/api/tasks", json={
        "title": "Not completed", "status": status, "recurrence_rule": "RRULE:FREQ=DAILY",
    })
    assert response.status_code == 201
    assert response.json()["completed_at"] is None
    assert len(client.get("/api/tasks").json()) == 1


def test_completion_retry_edit_and_recompletion_preserve_occurrence_identity(client, monkeypatch):
    original = create_completed(client, recurrence_rule="RRULE:FREQ=DAILY")
    path = f"/api/tasks/{original['id']}"
    successor = next(row for row in client.get("/api/tasks").json() if row["id"] != original["id"])
    later = datetime(2026, 11, 6, 12)
    monkeypatch.setattr("app.routers.tasks.utc_now", lambda: later)
    for changes in ({"status": "completed"}, {"title": "Edited"}):
        response = client.patch(path, json=changes)
        assert response.status_code == 200
        assert response.json()["completed_at"] == NOW.isoformat()
    assert client.patch(f"/api/tasks/{successor['id']}", json={"status": "completed"}).status_code == 200
    for status in ("todo", "in_progress", "canceled"):
        reopened = client.patch(path, json={"status": status})
        assert reopened.status_code == 200
        assert reopened.json()["completed_at"] is None
        recompleted = client.patch(path, json={"status": "completed"})
        assert recompleted.status_code == 200
        assert recompleted.json()["completed_at"] == later.isoformat()
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 3
    assert {row["recurrence_occurrence"] for row in tasks} == {0, 1, 2}


def test_successor_insert_failure_rolls_back_creation_and_can_retry(client):
    async def install_trigger():
        async with db.get_engine().begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TRIGGER block_created_successor BEFORE INSERT ON tasks "
                "WHEN NEW.recurrence_occurrence > 0 "
                "BEGIN SELECT RAISE(ABORT, 'injected successor failure'); END"
            )

    client.portal.call(install_trigger)
    payload = {"title": "Atomic creation", "status": "completed", "recurrence_rule": "RRULE:FREQ=DAILY"}
    with pytest.raises(IntegrityError, match="injected successor failure"):
        client.post("/api/tasks", json=payload)
    assert client.get("/api/tasks").json() == []

    async def remove_trigger():
        async with db.get_engine().begin() as conn:
            await conn.exec_driver_sql("DROP TRIGGER block_created_successor")

    client.portal.call(remove_trigger)
    assert client.post("/api/tasks", json=payload).status_code == 201
    assert len(client.get("/api/tasks").json()) == 2


def test_next_occurrence_overflow_rolls_back_completed_creation(client):
    response = client.post("/api/tasks", json={
        "title": "No next date", "status": "completed",
        "due_date": "9999-12-31T09:00:00", "recurrence_rule": "RRULE:FREQ=DAILY",
    })
    assert response.status_code == 422
    assert client.get("/api/tasks").json() == []


def test_successful_post_repeated_creates_independent_series(client):
    roots = [create_completed(client, recurrence_rule="RRULE:FREQ=DAILY") for _ in range(2)]
    assert roots[0]["id"] != roots[1]["id"]
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 4
    for root in roots:
        series = [row for row in tasks if row["recurrence_series_id"] == root["id"]]
        assert {row["recurrence_occurrence"] for row in series} == {0, 1}


def test_unsupported_rule_rejects_completed_creation_without_writes(client):
    response = client.post("/api/tasks", json={
        "title": "Invalid series", "status": "completed", "recurrence_rule": "RRULE:FREQ=MONTHLY",
    })
    assert response.status_code == 422
    assert client.get("/api/tasks").json() == []
