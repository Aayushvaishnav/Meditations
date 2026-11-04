"""Task classification is independent from deterministic score telemetry."""

from datetime import datetime

import pytest


@pytest.mark.parametrize("importance", ["unassigned", "important", "not_important"])
@pytest.mark.parametrize("urgency", ["unassigned", "urgent", "not_urgent"])
def test_classification_preserves_daily_score(client, monkeypatch, importance, urgency):
    from app.routers import tasks

    monkeypatch.setattr(tasks, "utc_now", lambda: datetime(2026, 11, 5, 12))
    task_ids = []
    for title in ("Planned", "Finished"):
        response = client.post("/api/tasks", json={
            "title": title,
            "deadline": {"kind": "date", "date": "2026-11-05"},
        })
        assert response.status_code == 201
        task_ids.append(response.json()["id"])
    assert client.patch(f"/api/tasks/{task_ids[1]}", json={"status": "completed"}).status_code == 200
    before = client.get("/api/scores/daily/2026-11-05")
    assert before.status_code == 200
    assert before.json()["metrics"]["tasks_planned"] == 2
    assert before.json()["metrics"]["tasks_completed"] == 1

    for task_id in task_ids:
        response = client.patch(f"/api/tasks/{task_id}", json={
            "importance": importance, "urgency": urgency,
        })
        assert response.status_code == 200
    after = client.get("/api/scores/daily/2026-11-05")
    assert after.status_code == 200
    assert after.json() == before.json()
