"""Endpoint compositions protecting contracts shared by independent features."""

from datetime import datetime, timedelta, timezone

import pytest

from app import agents, search
from app import ai_orchestration as review_routes

NOW = datetime(2030, 6, 20, 12)


@pytest.fixture(autouse=True)
def deterministic_services(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = NOW.replace(tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz is not None else NOW

    # Model factories retain utc_now references; freeze the clock they read too
    monkeypatch.setattr("app.util.datetime", FrozenDateTime)
    monkeypatch.setattr(search, "embed_texts", lambda texts: None)
    monkeypatch.setattr("app.routers.insights.utc_now", lambda: NOW)
    monkeypatch.setattr("app.routers.tasks.utc_now", lambda: NOW)
    monkeypatch.setattr("app.ai_orchestration.utc_now", lambda: NOW)

    async def request_model(session, fast=False):
        return object()

    monkeypatch.setattr(review_routes, "_request_model", request_model)


def save(client, day, **fields):
    response = client.put(f"/api/journal/{day}", json=fields)
    assert response.status_code == 200, response.text
    return response.json()


def insights(client, days):
    response = client.get("/api/insights", params={"days": days})
    assert response.status_code == 200, response.text
    return response.json()


def test_chart_window_does_not_truncate_calendar_or_lifetime_streaks(client):
    today = NOW.date()
    habit_response = client.post("/api/habits", json={"name": "Read"})
    assert habit_response.status_code == 201
    habit = habit_response.json()
    for offset in range(35):
        day = today - timedelta(days=offset)
        save(client, day, raw_markdown="", mood=4)
        response = client.put(f"/api/habits/{habit['id']}/logs", json={"date": str(day), "completed": True})
        assert response.status_code == 200
    future = today + timedelta(days=1)
    save(client, future, raw_markdown="Future plan")
    assert client.put(f"/api/habits/{habit['id']}/logs", json={"date": str(future), "completed": True}).status_code == 200

    short, long = insights(client, 14), insights(client, 90)
    assert len(short["series"]) == 14
    assert short["series"] == long["series"][-14:]
    for body in (short, long):
        assert body["journaling_streak"] == body["journaling_best"] == 35
        assert body["habits"] == [{"id": habit["id"], "name": "Read", "current_streak": 35, "rate_30": 1.0}]
        assert all(row["date"] <= str(today) for row in body["series"])
    calendar = client.get("/api/journal/days", params={"from": str(today - timedelta(days=40)), "to": str(future)})
    assert calendar.status_code == 200
    assert len(calendar.json()) == 36
    assert {row["date"] for row in calendar.json()} > {row["date"] for row in short["series"]}


def test_completed_creation_flows_through_activity_journal_score_and_next_day(client, monkeypatch):
    today = NOW.date()
    response = client.post("/api/tasks", json={
        "title": "Daily reading", "status": "completed", "recurrence_rule": "RRULE:FREQ=DAILY",
        "deadline": {"kind": "date", "date": str(today)},
    })
    assert response.status_code == 201, response.text
    root = response.json()
    successor = next(row for row in client.get("/api/tasks").json() if row["id"] != root["id"])
    assert successor["deadline"] == {"kind": "date", "date": str(today + timedelta(days=1))}
    assert successor["status"] == "todo"

    def assert_day(day, task_id):
        activity = client.get(f"/api/journal/{day}/activity").json()
        assert [row["id"] for row in activity["tasks_done"]] == [task_id]
        assert activity["tasks_planned"] == 1
        saved = save(client, day, raw_markdown="Finished reading")
        assert (saved["tasks_done"], saved["tasks_planned"]) == (1, 1)
        metrics = client.get(f"/api/scores/daily/{day}").json()["metrics"]
        assert (metrics["tasks_completed"], metrics["tasks_planned"]) == (1, 1)
        chart = next(row for row in insights(client, 14)["series"] if row["date"] == str(day))
        assert (chart["tasks_completed"], chart["tasks_planned"]) == (1, 1)

    assert_day(today, root["id"])
    tomorrow = today + timedelta(days=1)
    assert client.get(f"/api/journal/{tomorrow}/activity").json()["tasks_done"] == []
    monkeypatch.setattr("app.routers.tasks.utc_now", lambda: NOW + timedelta(days=1))
    monkeypatch.setattr("app.routers.insights.utc_now", lambda: NOW + timedelta(days=1))
    assert client.patch(f"/api/tasks/{successor['id']}", json={"status": "completed"}).status_code == 200
    assert_day(tomorrow, successor["id"])
    assert_day(today, root["id"])
    assert insights(client, 14)["totals"]["tasks_done"] == 2
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 3
    assert sum(row["status"] == "todo" for row in tasks) == 1


def test_historical_review_target_survives_newer_rollups_and_remains_searchable(client, monkeypatch):
    calls = []

    async def weekly(deps, **kwargs):
        calls.append(deps)
        return agents.WeeklyReviewOutput(wins=f"weekmarker {deps.week_start}", misses="", carried_action_items="")

    async def monthly(deps, **kwargs):
        return agents.MonthlyReviewOutput(narrative=f"monthmarker {deps.month}")

    monkeypatch.setattr(agents, "run_weekly_review", weekly)
    monkeypatch.setattr(agents, "run_monthly_review", monthly)

    def roll_week(day):
        response = client.post("/api/agents/rollup/weekly", params={"week_start": day})
        assert response.status_code == 200, response.text
        return response.json()

    for day in ("2023-12-04", "2024-01-08", "2026-10-05"):
        save(client, day, raw_markdown="privatejournalmarker", mood=4)
    roll_week("2023-12-04")
    assert client.post("/api/agents/rollup/monthly", params={"month": "2023-12"}).status_code == 200
    first = roll_week("2024-01-08")
    first_deps = calls[-1]
    roll_week("2026-10-05")
    assert client.post("/api/agents/rollup/monthly", params={"month": "2026-10"}).status_code == 200
    rerun = roll_week("2024-01-08")
    assert calls[-1] == first_deps
    assert calls[-1].monthly_context == "monthmarker 2023-12"
    assert [row["date"] for row in calls[-1].days] == ["2024-01-08"]
    assert "privatejournalmarker" not in str(calls[-1])
    assert rerun["week_start"] == first["week_start"] == "2024-01-08"
    assert rerun["avg_score"] == first["avg_score"]
    body = insights(client, 14)
    assert sum(row["week_start"] == "2024-01-08" for row in body["weekly"]) == 1
    hits = client.get("/api/search", params={"q": "weekmarker"}).json()
    assert sum(row["doc_id"] == "weekly:2024-01-08" for row in hits) == 1


def test_failed_index_recovery_does_not_erase_local_journal_or_calendar(client, monkeypatch):
    day = NOW.date()

    def unavailable(texts):
        raise RuntimeError("injected embedding outage")

    monkeypatch.setattr(search, "embed_texts", unavailable)
    save(client, day, raw_markdown="originalmarker", mood=3)
    original_execute = search._execute

    async def fail_after_write(session, sql, params=None):
        result = await original_execute(session, sql, params)
        if sql.startswith("INSERT INTO fts_entries"):
            raise RuntimeError("injected index failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(search, "_execute", fail_after_write)
        with pytest.raises(RuntimeError, match="injected index failure"):
            client.post("/api/search/reindex")
        with pytest.raises(RuntimeError, match="injected index failure"):
            client.put(f"/api/journal/{day}", json={"raw_markdown": "replacementmarker", "mood": 5})

    entry = client.get(f"/api/journal/{day}").json()
    assert (entry["raw_markdown"], entry["mood"]) == ("originalmarker", 3)
    calendar = client.get("/api/journal/days", params={"from": str(day), "to": str(day)})
    assert calendar.json() == [{"date": str(day), "mood": 3, "energy": None}]
    assert insights(client, 14)["series"][-1]["mood"] == 3
    assert client.get("/api/search", params={"q": "originalmarker"}).json()
    assert client.get("/api/search", params={"q": "replacementmarker"}).json() == []

    save(client, day, raw_markdown="replacementmarker", mood=5)
    assert client.post("/api/search/reindex").status_code == 200
    assert client.get("/api/search", params={"q": "originalmarker"}).json() == []
    hits = client.get("/api/search", params={"q": "replacementmarker"}).json()
    assert [hit["doc_id"] for hit in hits] == [f"journal:{day}"]
    assert hits[0]["sources"] == ["fts"]
    assert insights(client, 14)["series"][-1]["mood"] == 5

    vector = [1.0] + [0.0] * (search.EMBED_DIM - 1)
    monkeypatch.setattr(search, "embed_texts", lambda texts: [vector for _ in texts])
    assert client.post("/api/search/reindex").status_code == 200
    recovered = client.get("/api/search", params={"q": "replacementmarker"}).json()
    assert [hit["doc_id"] for hit in recovered] == [f"journal:{day}"]
    assert recovered[0]["sources"] == (["fts", "semantic"] if search.vec_available() else ["fts"])
    assert client.get(f"/api/journal/{day}").json()["raw_markdown"] == "replacementmarker"
    assert client.put(f"/api/journal/{day}", json={"raw_markdown": ""}).json() == {"saved": False}
    assert client.get(f"/api/journal/{day}").status_code == 404
    assert client.get("/api/search", params={"q": "replacementmarker"}).json() == []
    assert client.get("/api/journal/days", params={"from": str(day), "to": str(day)}).json() == []
