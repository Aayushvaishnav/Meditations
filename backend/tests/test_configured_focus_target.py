from __future__ import annotations

import json

import pytest

import app.agents as agents
from app import ai_orchestration as agent_routes
from app.routers import scores as score_routes
from app.scoring import DailyMetrics

DAY = "2026-09-14"


@pytest.fixture()
def scoring_day(client, monkeypatch):
    async def metrics(session, day):
        return DailyMetrics(deep_work_hours=2)

    async def daily(*args, **kwargs):
        return agents.DailyReviewOutput(
            llm_nudge=8, nudge_rationale="Context", feedback="Review",
            key_insight="Insight", suggested_action_for_tomorrow="Rest",
        )

    async def stream(*args, **kwargs):
        yield await daily()

    async def weekly(deps, **kwargs):
        return agents.WeeklyReviewOutput(wins="Win", misses="Miss", carried_action_items="Rest")

    monkeypatch.setattr(agent_routes, "collect_daily_metrics", metrics)
    monkeypatch.setattr(score_routes, "collect_daily_metrics", metrics)
    monkeypatch.setattr(agents, "run_daily_review", daily)
    monkeypatch.setattr(agents, "stream_daily_review", stream)
    monkeypatch.setattr(agents, "run_weekly_review", weekly)
    assert client.put(f"/api/journal/{DAY}", json={"raw_markdown": "A day"}).status_code == 200
    return client


def review(client, streaming):
    response = client.post("/api/agents/rollup/daily" + ("/stream" if streaming else ""), params={"day": DAY})
    assert response.status_code == 200
    if streaming:
        events = response.text.split("\n\n")
        done = next(event for event in events if event.startswith("event: done"))
        return json.loads(next(line[6:] for line in done.splitlines() if line.startswith("data: ")))
    return response.json()


@pytest.mark.parametrize("target,weighted", [(2, 50), (8, 23.75)])
@pytest.mark.parametrize("streaming", [False, True])
def test_configured_target_matches_live_and_review(scoring_day, target, weighted, streaming):
    client = scoring_day
    client.put("/api/settings/app", json={"target_deep_work_hours": target})
    live = client.get(f"/api/scores/daily/{DAY}").json()
    saved = review(client, streaming)
    assert live["weighted_score"] == weighted
    assert saved["weighted_score"] == weighted
    assert saved["target_deep_work_hours"] == target
    assert saved["final_score"] == weighted + 8
    after = client.get(f"/api/scores/daily/{DAY}").json()
    assert after["final_score"] == saved["final_score"]


def test_weekly_fallback_uses_configured_target(scoring_day):
    client = scoring_day
    client.put("/api/settings/app", json={"target_deep_work_hours": 2})
    result = client.post("/api/agents/rollup/weekly", params={"week_start": DAY})
    assert result.status_code == 200
    assert result.json()["avg_score"] == 50


@pytest.mark.parametrize("streaming", [False, True])
def test_target_change_preserves_review_until_rerun(scoring_day, streaming):
    client = scoring_day
    client.put("/api/settings/app", json={"target_deep_work_hours": 2})
    saved = review(client, streaming)
    assert saved["score_basis"] == "review_snapshot"
    assert saved["saved_review_score"] == 58
    client.put("/api/settings/app", json={"target_deep_work_hours": 8})
    live = client.get(f"/api/scores/daily/{DAY}").json()
    assert live["score_basis"] == "live"
    assert live["final_score"] == 31.75
    assert live["saved_review_score"] == 58
    weekly = client.post("/api/agents/rollup/weekly", params={"week_start": DAY}).json()
    assert weekly["avg_score"] == 58
    updated = review(client, streaming)
    assert updated["saved_review_score"] == 31.75
    weekly = client.post("/api/agents/rollup/weekly", params={"week_start": DAY}).json()
    assert weekly["avg_score"] == 31.75


def test_explicit_live_target_does_not_change_preferences(scoring_day):
    client = scoring_day
    client.put("/api/settings/app", json={"target_deep_work_hours": 8})
    live = client.get(f"/api/scores/daily/{DAY}", params={"target_hours": 2}).json()
    assert live["weighted_score"] == 50
    assert client.get("/api/settings/app").json()["target_deep_work_hours"] == 8
    assert review(client, False)["weighted_score"] == 23.75


@pytest.mark.parametrize("stored,expected", [
    (None, 4), ("2", 2), ("16", 16), ("0.001", 0.001),
    ("invalid", 4), ("nan", 4), ("inf", 4), ("-inf", 4),
    ("0", 4), ("-2", 4), ("17", 4),
])
def test_target_resolution_is_shared_by_preferences_and_scoring(scoring_day, stored, expected):
    import asyncio

    from app.db import get_sessionmaker
    from app.models import AppSetting

    async def seed():
        async with get_sessionmaker()() as session:
            session.add(AppSetting(key="target_deep_work_hours", value=stored))
            await session.commit()

    if stored is not None:
        asyncio.run(seed())
    client = scoring_day
    assert client.get("/api/settings/app").json()["target_deep_work_hours"] == expected
    assert client.get(f"/api/scores/daily/{DAY}").json()["target_deep_work_hours"] == expected
    assert review(client, False)["target_deep_work_hours"] == expected


@pytest.mark.parametrize("streaming", [False, True])
def test_saved_rubric_matches_final_review(scoring_day, streaming):
    import asyncio
    from datetime import date

    from app.db import get_sessionmaker
    from app.models import DailyScore

    client = scoring_day
    client.put("/api/settings/app", json={"target_deep_work_hours": 2})
    result = review(client, streaming)

    async def load():
        async with get_sessionmaker()() as session:
            row = await session.get(DailyScore, date.fromisoformat(DAY))
            return json.loads(row.rubric_breakdown_json)

    rubric = asyncio.run(load())
    for field in ("target_deep_work_hours", "metrics", "weighted_score", "llm_nudge", "final_score"):
        assert rubric[field] == result[field]
