from __future__ import annotations

from datetime import datetime

import pytest


BASE = "/api/time-blocks"
START = "2026-09-10T09:00:00"
END = "2026-09-10T10:00:00"


def make_task(client, **overrides):
    response = client.post("/api/tasks", json={"title": "Scheduled work", **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def payload(task_id, **overrides):
    return {"task_id": task_id, "start_at": START, "end_at": END, **overrides}


def make_block(client, task_id, **overrides):
    response = client.post(BASE, json=payload(task_id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def list_blocks(client, **params):
    response = client.get(BASE, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_crud_and_full_replacement(client):
    first = make_task(client)
    second = make_task(client, title="Reassigned")
    block = make_block(client, first["id"])
    assert block["id"]
    assert block["task_id"] == first["id"]
    for field in ("start_at", "end_at", "created_at", "updated_at"):
        assert datetime.fromisoformat(block[field]).tzinfo is None
    assert client.get(f"{BASE}/{block['id']}").json() == block

    replacement = payload(second["id"], start_at="2026-09-11T12:00:00", end_at="2026-09-11T13:00:00")
    response = client.put(f"{BASE}/{block['id']}", json=replacement)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["id"] == block["id"]
    assert updated["created_at"] == block["created_at"]
    assert datetime.fromisoformat(updated["updated_at"]) >= datetime.fromisoformat(block["updated_at"])
    for field, value in replacement.items():
        assert updated[field] == value
    assert list_blocks(client, task_id=first["id"]) == []
    assert list_blocks(client, task_id=second["id"]) == [updated]
    assert client.delete(f"{BASE}/{block['id']}").status_code == 204
    assert client.get(f"{BASE}/{block['id']}").status_code == 404
    assert list_blocks(client) == []


@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize("field", ["task_id", "start_at", "end_at"])
@pytest.mark.parametrize("invalid", ["missing", "null"])
def test_required_fields(client, method, field, invalid):
    task = make_task(client)
    block = make_block(client, task["id"])
    body = payload(task["id"])
    if invalid == "missing":
        del body[field]
    else:
        body[field] = None
    url = BASE if method == "post" else f"{BASE}/{block['id']}"
    assert getattr(client, method)(url, json=body).status_code == 422
    assert list_blocks(client) == [block]


@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize("extra", ["unexpected", "id", "created_at", "updated_at"])
def test_extra_fields_forbidden(client, method, extra):
    task = make_task(client)
    block = make_block(client, task["id"])
    url = BASE if method == "post" else f"{BASE}/{block['id']}"
    assert getattr(client, method)(url, json=payload(task["id"], **{extra: START})).status_code == 422
    assert list_blocks(client) == [block]


@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize("start,end", [
    (START, START),
    (END, START),
    ("2026-09-10", END),
    (START, "2026-09-11"),
    ("0001-01-01T00:00:00+01:00", END),
    (START, "9999-12-31T23:59:59-01:00"),
    (1234567890, END),
    (True, END),
    ("2026-02-30T09:00:00", END),
    ("2026-09-10T10:00:00+01:00", "2026-09-10T09:00:00Z"),
    ("2026-09-10T09:00:00-02:00", "2026-09-10T10:00:00Z"),
])
def test_invalid_intervals(client, method, start, end):
    task = make_task(client)
    block = make_block(client, task["id"])
    url = BASE if method == "post" else f"{BASE}/{block['id']}"
    response = getattr(client, method)(url, json=payload(task["id"], start_at=start, end_at=end))
    assert response.status_code == 422, response.text
    assert list_blocks(client) == [block]


def test_offsets_normalized_before_interval_validation(client):
    task = make_task(client)
    block = make_block(client, task["id"], start_at="2026-09-10T10:30:00+02:00", end_at="2026-09-10T09:00:00Z")
    assert block["start_at"] == "2026-09-10T08:30:00"
    assert block["end_at"] == "2026-09-10T09:00:00"
    response = client.put(f"{BASE}/{block['id']}", json=payload(task["id"], start_at="2026-09-10T23:00:00-02:00", end_at="2026-09-11T04:00:00+02:00"))
    assert response.status_code == 200, response.text
    assert response.json()["start_at"] == "2026-09-11T01:00:00"
    assert response.json()["end_at"] == "2026-09-11T02:00:00"


def test_missing_resources_and_failed_reassignment(client):
    task = make_task(client)
    block = make_block(client, task["id"])
    assert client.post(BASE, json=payload("missing")).status_code == 404
    assert client.put(f"{BASE}/{block['id']}", json=payload("missing")).status_code == 404
    assert client.get(f"{BASE}/missing").status_code == 404
    assert client.put(f"{BASE}/missing", json=payload(task["id"])).status_code == 404
    assert client.delete(f"{BASE}/missing").status_code == 404
    assert list_blocks(client) == [block]


def test_overlap_filters_boundaries_and_stable_order(client):
    task = make_task(client)
    other = make_task(client)
    blocks = [
        make_block(client, task["id"], start_at="2026-09-10T10:00:00", end_at="2026-09-10T11:00:00"),
        make_block(client, task["id"], start_at="2026-09-10T08:00:00", end_at=START),
        make_block(client, task["id"], start_at=START, end_at=END),
        make_block(client, other["id"], start_at=START, end_at="2026-09-10T12:00:00"),
        make_block(client, task["id"], start_at="2026-09-10T08:30:00", end_at="2026-09-10T10:30:00"),
    ]
    def expected(indices):
        return sorted((blocks[i] for i in indices), key=lambda block: (block["start_at"], block["id"]))

    assert list_blocks(client) == expected(range(5))
    assert list_blocks(client, start=START, end=END) == expected([2, 3, 4])
    assert list_blocks(client, start=START) == expected([0, 2, 3, 4])
    assert list_blocks(client, end=END) == expected([1, 2, 3, 4])
    assert list_blocks(client, task_id=task["id"], start=START, end=END) == expected([2, 4])
    assert list_blocks(client, start="2026-09-10T11:00:00+02:00", end="2026-09-10T12:00:00+02:00") == expected([2, 3, 4])
    assert list_blocks(client, task_id="missing") == []


@pytest.mark.parametrize("params", [
    {"start": START, "end": START},
    {"start": END, "end": START},
    {"start": "2026-09-10T10:00:00+01:00", "end": START},
    {"start": "2026-09-10"},
    {"end": "2026-09-11"},
    {"start": "not-a-time"},
    {"start": "0001-01-01T00:00:00+01:00"},
    {"end": "9999-12-31T23:59:59-01:00"},
])
def test_invalid_filter_bounds(client, params):
    assert client.get(BASE, params=params).status_code == 422


def test_blocks_do_not_change_tasks_focus_or_scores(client):
    task = make_task(client, due_date="2026-09-10T17:00:00", estimated_minutes=90)
    other = make_task(client, title="Independent")
    score_url = "/api/scores/daily/2026-09-10"
    score = client.get(score_url).json()
    sessions = client.get("/api/focus/sessions").json()
    first = make_block(client, task["id"])
    second = make_block(client, task["id"])
    independent = make_block(client, other["id"])
    assert first["id"] != second["id"]
    assert client.put(f"{BASE}/{first['id']}", json=payload(task["id"], end_at="2026-09-10T12:00:00")).status_code == 200
    assert client.delete(f"{BASE}/{first['id']}").status_code == 204
    assert client.get(f"{BASE}/{second['id']}").json() == second
    assert client.get(f"{BASE}/{independent['id']}").json() == independent
    assert client.get(f"/api/tasks/{task['id']}").json() == task
    assert client.get(f"/api/tasks/{other['id']}").json() == other
    assert client.get("/api/focus/sessions").json() == sessions
    assert client.get(score_url).json() == score


def test_task_deletion_cascades_to_descendant_blocks_only(client):
    parent = make_task(client)
    child = make_task(client, parent_id=parent["id"])
    grandchild = make_task(client, parent_id=child["id"])
    unrelated = make_task(client)
    deleted = [make_block(client, task["id"]) for task in (parent, child, grandchild)]
    survivor = make_block(client, unrelated["id"])
    assert client.delete(f"/api/tasks/{parent['id']}").status_code == 204
    assert list_blocks(client) == [survivor]
    for block in deleted:
        assert client.get(f"{BASE}/{block['id']}").status_code == 404


@pytest.mark.parametrize("recurring", [False, True])
def test_completion_keeps_blocks_on_original_task(client, recurring):
    fields = {"recurrence_rule": "RRULE:FREQ=DAILY"} if recurring else {}
    task = make_task(client, due_date="2026-09-10T17:00:00", **fields)
    block = make_block(client, task["id"])
    response = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert list_blocks(client) == [block]
    tasks = client.get("/api/tasks").json()
    successors = [item for item in tasks if item["id"] != task["id"]]
    assert len(successors) == int(recurring)
    for successor in successors:
        assert successor["status"] == "todo"
        assert list_blocks(client, task_id=successor["id"]) == []
