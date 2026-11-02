from __future__ import annotations

from datetime import datetime

import pytest


def create_recurring(client, **overrides):
    response = client.post(
        "/api/tasks",
        json={
            "title": "Daily review",
            "due_date": "2026-09-15T09:00:00",
            "recurrence_rule": "RRULE:FREQ=DAILY",
            **overrides,
        },
    )
    assert response.status_code == 201
    return response.json()


def patch(client, task, **changes):
    response = client.patch(f"/api/tasks/{task['id']}", json=changes)
    assert response.status_code == 200
    return response.json()


def identity(task):
    return task["recurrence_series_id"], task["recurrence_occurrence"]


def successor_of(client, task):
    return next(
        candidate for candidate in client.get("/api/tasks").json()
        if identity(candidate) == (task["recurrence_series_id"], task["recurrence_occurrence"] + 1)
    )


@pytest.mark.parametrize("separate_lists", [False, True])
def test_identically_named_series_each_spawn_successor(client, separate_lists):
    lists = [client.post("/api/lists", json={"name": name}).json() for name in ("Work", "Home")]
    list_ids = [item["id"] for item in lists] if separate_lists else [lists[0]["id"]] * 2
    originals = [create_recurring(client, list_id=list_id) for list_id in list_ids]
    for task in originals:
        completed = patch(client, task, status="completed")
        assert identity(completed) == identity(task)
        assert completed["completed_at"] is not None

    tasks = client.get("/api/tasks").json()
    successors = [task for task in tasks if task["status"] == "todo"]
    assert len(successors) == 2
    assert sorted(task["list_id"] for task in successors) == sorted(list_ids)
    assert {identity(task) for task in successors} == {
        (task["recurrence_series_id"], 1) for task in originals
    }


def test_recompletion_after_successor_completed_does_not_duplicate(client):
    original = create_recurring(client)
    patch(client, original, status="completed")
    successor = successor_of(client, original)
    patch(client, successor, status="completed")
    patch(client, original, status="todo")
    patch(client, original, status="completed")

    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 3
    assert sum(task["status"] == "completed" for task in tasks) == 2
    assert {identity(task) for task in tasks} == {
        (original["recurrence_series_id"], number) for number in range(3)
    }


@pytest.mark.parametrize("status", ["todo", "in_progress", "completed", "canceled"])
def test_edited_successor_remains_same_occurrence(client, status):
    original = create_recurring(client)
    patch(client, original, status="completed")
    successor = successor_of(client, original)
    target_list = client.post("/api/lists", json={"name": "Moved"}).json()
    edited = patch(
        client, successor, title="Renamed", list_id=target_list["id"],
        due_date="2026-10-03T11:00:00", status=status,
    )
    assert identity(edited) == identity(successor)
    count = len(client.get("/api/tasks").json())

    patch(client, original, status="todo", title="Changed original", recurrence_rule="RRULE:FREQ=WEEKLY")
    patch(client, original, status="completed")
    assert len(client.get("/api/tasks").json()) == count
    assert successor_of(client, original)["id"] == successor["id"]


def test_renaming_moving_and_rescheduling_root_keeps_series(client):
    original = create_recurring(client)
    target_list = client.post("/api/lists", json={"name": "New list"}).json()
    edited = patch(
        client, original, title="New title", list_id=target_list["id"], due_date="2026-10-01T11:00:00",
    )
    assert identity(edited) == identity(original)
    patch(client, original, status="completed")
    successor = successor_of(client, original)
    assert successor["title"] == "New title"
    assert successor["list_id"] == target_list["id"]
    assert successor["due_date"] == "2026-10-02T11:00:00"


def test_undated_recompletion_uses_identity_not_new_completion_time(client, monkeypatch):
    monkeypatch.setattr("app.routers.tasks.utc_now", lambda: datetime(2026, 9, 15, 9))
    original = create_recurring(client, due_date=None)
    patch(client, original, status="completed")
    successor = successor_of(client, original)
    assert successor["due_date"] == "2026-09-16T09:00:00"

    monkeypatch.setattr("app.routers.tasks.utc_now", lambda: datetime(2026, 10, 15, 9))
    patch(client, original, status="todo")
    patch(client, original, status="completed")
    assert len(client.get("/api/tasks").json()) == 2
    assert successor_of(client, original) == successor


def test_enabling_disabling_and_reenabling_recurrence_preserves_identity(client):
    task = client.post("/api/tasks", json={"title": "One-off"}).json()
    assert identity(task) == (None, None)
    enabled = patch(client, task, recurrence_rule="RRULE:FREQ=DAILY")
    assert identity(enabled) == (task["id"], 0)
    patch(client, task, status="completed")
    patch(client, task, status="todo", recurrence_rule=None)
    disabled = patch(client, task, status="completed")
    assert identity(disabled) == identity(enabled)
    assert len(client.get("/api/tasks").json()) == 2
    patch(client, task, status="todo", recurrence_rule="RRULE:FREQ=WEEKLY")
    patch(client, task, status="completed")
    assert len(client.get("/api/tasks").json()) == 2


def test_successor_copies_configuration_not_completion_or_focus_history(client):
    parent = client.post("/api/tasks", json={"title": "Parent"}).json()
    original = create_recurring(
        client, parent_id=parent["id"], description="Checklist", tags=["habit"],
        priority=3, estimated_minutes=25,
    )
    focus = client.post("/api/focus/sessions", json={"task_id": original["id"], "duration_minutes": 25})
    assert focus.status_code == 201
    completed = patch(client, original, status="completed")
    successor = successor_of(client, original)
    for key in ("parent_id", "description", "tags", "priority", "estimated_minutes", "recurrence_rule"):
        assert successor[key] == original[key]
    assert completed["actual_minutes"] == 25
    assert successor["actual_minutes"] == 0
    assert successor["completed_at"] is None
    assert successor["id"] != original["id"]
    assert client.get(f"/api/tasks/{original['id']}").json() == completed


def test_deleting_series_root_does_not_break_surviving_occurrences(client):
    original = create_recurring(client)
    patch(client, original, status="completed")
    successor = successor_of(client, original)
    assert client.delete(f"/api/tasks/{original['id']}").status_code == 204
    patch(client, successor, status="completed")
    assert identity(successor_of(client, successor)) == (original["recurrence_series_id"], 2)


def test_deleted_successor_can_be_regenerated_with_same_occurrence_identity(client):
    original = create_recurring(client)
    patch(client, original, status="completed")
    successor = successor_of(client, original)
    client.delete(f"/api/tasks/{successor['id']}")
    patch(client, original, status="todo")
    patch(client, original, status="completed")
    assert identity(successor_of(client, original)) == identity(successor)
    assert len(client.get("/api/tasks").json()) == 2


def test_identity_is_server_managed(client):
    original = create_recurring(client, recurrence_series_id="forged", recurrence_occurrence=50)
    assert identity(original) == (original["id"], 0)
    edited = patch(client, original, recurrence_series_id="other", recurrence_occurrence=99)
    assert identity(edited) == identity(original)


def test_unsupported_recurrence_does_not_spawn(client):
    original = create_recurring(client, recurrence_rule="RRULE:FREQ=MONTHLY")
    patch(client, original, status="completed")
    assert len(client.get("/api/tasks").json()) == 1


def test_successor_failure_rolls_back_source_completion(client):
    from sqlalchemy.exc import IntegrityError

    from app import db

    original = create_recurring(client)

    async def block_successors():
        async with db.get_engine().begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TRIGGER block_successors BEFORE INSERT ON tasks "
                "WHEN NEW.recurrence_occurrence > 0 "
                "BEGIN SELECT RAISE(ABORT, 'injected successor failure'); END"
            )

    client.portal.call(block_successors)
    with pytest.raises(IntegrityError, match="injected successor failure"):
        client.patch(f"/api/tasks/{original['id']}", json={"status": "completed"})
    assert client.get(f"/api/tasks/{original['id']}").json() == original
    assert len(client.get("/api/tasks").json()) == 1
