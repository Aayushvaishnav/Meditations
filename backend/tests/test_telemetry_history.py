"""Historical planning excludes tasks not yet created in the UTC report day."""

from datetime import date, datetime, timedelta

import pytest

from app import db
from app.models import DailyScore, JournalEntry, Task
from app.scoring import DailyMetrics, compute_daily_score

DAY = date(2026, 11, 4)
START = datetime(2026, 11, 4)
END = datetime(2026, 11, 5)


def seed(client, *rows):
    async def persist():
        async with db.get_sessionmaker()() as session:
            session.add_all(rows)
            await session.commit()

    client.portal.call(persist)


def read_score(client):
    response = client.get(f"/api/scores/daily/{DAY}")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("deadline", [
    {"due_date": START - timedelta(days=1)},
    {"deadline_date": DAY - timedelta(days=1)},
], ids=["timed", "date-only"])
def test_new_task_with_old_deadline_does_not_rewrite_yesterday(client, deadline):
    before = read_score(client)
    seed(client, Task(title="Created today, due yesterday", created_at=END, **deadline))
    assert read_score(client)["metrics"] == before["metrics"]


@pytest.mark.parametrize("created_at, expected", [
    (START - timedelta(days=1), 1),
    (START, 1),
    (END - timedelta(microseconds=1), 1),
    (END, 0),
    (END + timedelta(microseconds=1), 0),
])
@pytest.mark.parametrize("deadline", [
    {"due_date": START},
    {"deadline_date": DAY},
], ids=["timed", "date-only"])
def test_creation_cutoff_is_exclusive_naive_utc(client, created_at, expected, deadline):
    seed(client, Task(title="Boundary", created_at=created_at, **deadline))
    assert read_score(client)["metrics"]["tasks_planned"] == expected


@pytest.mark.parametrize("fields, planned, completed", [
    ({"due_date": START - timedelta(days=3)}, 1, 0),
    ({"deadline_date": DAY - timedelta(days=3)}, 1, 0),
    ({"due_date": END}, 0, 0),
    ({"deadline_date": DAY + timedelta(days=1)}, 0, 0),
    ({"status": "completed", "completed_at": START}, 1, 1),
    ({"status": "completed", "completed_at": END - timedelta(microseconds=1)}, 1, 1),
    ({"status": "completed", "completed_at": END}, 0, 0),
    ({}, 0, 0),
    ({"due_date": START, "status": "completed", "completed_at": START - timedelta(microseconds=1)}, 0, 0),
    ({"due_date": START, "status": "completed", "completed_at": END}, 1, 0),
    ({"due_date": START, "status": "canceled"}, 0, 0),
    ({"deadline_date": DAY, "status": "canceled"}, 0, 0),
])
def test_existing_task_planning_and_completion_semantics(client, fields, planned, completed):
    seed(client, Task(title="Existing task", created_at=START - timedelta(days=4), **fields))
    metrics = read_score(client)["metrics"]
    assert metrics["tasks_planned"] == planned
    assert metrics["tasks_completed"] == completed


def test_live_projection_does_not_rewrite_saved_review(client):
    snapshot = compute_daily_score(DailyMetrics(tasks_planned=2, tasks_completed=1))
    seed(client, JournalEntry(date=DAY, raw_markdown="Reflection", tasks_planned=2, tasks_done=1))
    seed(client, DailyScore(
        date=DAY, deterministic_score=snapshot.weighted_score, final_score=snapshot.final_score,
        rubric_breakdown_json=snapshot.model_dump_json(), feedback="Saved", insight="Snapshot",
    ))
    seed(client, Task(title="Late creation", created_at=END, deadline_date=DAY))

    live = read_score(client)
    assert live["metrics"]["tasks_planned"] == 0
    assert live["saved_review_score"] == snapshot.final_score
    assert live["score_basis"] == "live"

    async def stored_values():
        async with db.get_sessionmaker()() as session:
            review = await session.get(DailyScore, DAY)
            journal = await session.get(JournalEntry, DAY)
            return review.rubric_breakdown_json, journal.tasks_planned, journal.tasks_done

    assert client.portal.call(stored_values) == (snapshot.model_dump_json(), 2, 1)


@pytest.mark.parametrize("saved_review", [False, True])
def test_weekly_review_uses_eligible_metrics_and_preserves_saved_scores(client, monkeypatch, saved_review):
    from app import agents

    seed(client, JournalEntry(date=DAY, raw_markdown="Reflection"))
    seed(
        client,
        Task(title="Done that day", created_at=START, status="completed",
             completed_at=START + timedelta(hours=1)),
        Task(title="Created later", created_at=END, deadline_date=DAY),
    )
    expected_score = compute_daily_score(DailyMetrics(tasks_planned=1, tasks_completed=1)).final_score
    if saved_review:
        expected_score = 77.0
        seed(client, DailyScore(
            date=DAY, deterministic_score=75, llm_nudge=2, final_score=expected_score,
            rubric_breakdown_json="{}", feedback="Saved", insight="Snapshot",
        ))

    async def review(deps, **kwargs):
        assert deps.days == [{
            "date": str(DAY), "score": expected_score, "tasks_done": 1,
            "tasks_planned": 1, "deep_work_hours": 0.0,
        }]
        return agents.WeeklyReviewOutput(wins="Done", misses="None", carried_action_items="None")

    monkeypatch.setattr(agents, "run_weekly_review", review)
    week_start = DAY - timedelta(days=DAY.weekday())
    response = client.post("/api/agents/rollup/weekly", params={"week_start": str(week_start)})
    assert response.status_code == 200
    assert response.json()["avg_score"] == expected_score
