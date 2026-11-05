from __future__ import annotations

import pytest


@pytest.mark.parametrize("field", ["title", "priority", "status", "tags"])
def test_required_task_fields_reject_explicit_null_without_changes(client, field):
    original = client.post("/api/tasks", json={
        "title": "Keep original", "priority": 2, "status": "in_progress",
        "tags": ["keep"], "description": "Keep description",
    }).json()

    response = client.patch(f"/api/tasks/{original['id']}", json={
        field: None, "description": "Must not be persisted",
    })

    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
    assert client.get(f"/api/tasks/{original['id']}").json() == original
    assert client.get("/api/tasks").json() == [original]


def test_task_patch_preserves_omitted_fields_and_allows_clearing(client):
    task_list = client.post("/api/lists", json={"name": "Temporary"}).json()
    parent = client.post("/api/tasks", json={"title": "Parent"}).json()
    original = client.post("/api/tasks", json={
        "title": "Keep original", "priority": 3, "status": "in_progress",
        "tags": ["keep"], "description": "Clear me", "list_id": task_list["id"],
        "parent_id": parent["id"], "due_date": "2026-11-05T10:00:00",
        "estimated_minutes": 30, "recurrence_rule": "FREQ=DAILY",
    }).json()
    assert "id" in original
    url = f"/api/tasks/{original['id']}"
    unchanged = client.patch(url, json={})
    assert unchanged.status_code == 200
    assert {k: v for k, v in unchanged.json().items() if k != "updated_at"} == {
        k: v for k, v in original.items() if k != "updated_at"
    }

    response = client.patch(url, json={
        "description": None, "list_id": None, "parent_id": None,
        "due_date": None, "estimated_minutes": None, "recurrence_rule": None, "tags": [],
    })
    assert response.status_code == 200
    updated = response.json()
    for field in ("description", "list_id", "parent_id", "due_date", "estimated_minutes", "recurrence_rule"):
        assert updated[field] is None
    assert updated["tags"] == []
    for field in ("title", "priority", "status", "importance", "urgency"):
        assert updated[field] == original[field]
    assert client.get(url).json() == updated
    response = client.patch(url, json={"priority": 0})
    assert response.status_code == 200
    assert response.json()["priority"] == 0
    assert client.get(url).json()["priority"] == 0
