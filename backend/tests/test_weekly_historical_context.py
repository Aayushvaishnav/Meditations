from __future__ import annotations

from datetime import date, timedelta
from functools import partial

import pytest
from sqlmodel import select

from app import agents, db, review_scheduler
from app.models import JournalEntry, MonthlySummary, WeeklySummary
from app import ai_orchestration as routes


@pytest.fixture
def review_calls(monkeypatch):
    calls = []

    async def request_model(session, fast=False):
        return object()

    async def index_document(*args):
        pass

    async def weekly(deps, **kwargs):
        calls.append(deps)
        return agents.WeeklyReviewOutput(wins="Reviewed", misses="", carried_action_items="")

    async def daily(deps, **kwargs):
        return agents.DailyReviewOutput(llm_nudge=0, feedback="Reviewed", key_insight="Insight")

    async def monthly(deps, **kwargs):
        return agents.MonthlyReviewOutput(narrative="Rebuilt month")

    monkeypatch.setattr(routes, "_request_model", request_model)
    monkeypatch.setattr(routes, "index_document", index_document)
    monkeypatch.setattr(agents, "run_weekly_review", weekly)
    monkeypatch.setattr(agents, "run_daily_review", daily)
    monkeypatch.setattr(agents, "run_monthly_review", monthly)
    return calls


async def seed(week_start, months, *, past_weeks=False):
    async with db.get_sessionmaker()() as session:
        session.add(JournalEntry(date=week_start, raw_markdown="Private journal text"))
        for month in months:
            session.add(MonthlySummary(month=month, avg_score=75, trend="stable", narrative=month))
        if past_weeks:
            for offset in range(-1, 7):
                session.add(WeeklySummary(
                    week_start=week_start - timedelta(weeks=offset),
                    avg_score=75, trend="stable", wins=str(offset), misses="", carried_action_items="",
                ))
        await session.commit()


@pytest.mark.parametrize(("week_start", "months", "expected"), [
    (date(2024, 1, 8), ["2023-11", "2023-12", "2024-01", "2026-10"], "2023-12"),
    (date(2024, 1, 29), ["2023-12", "2024-01", "2024-02"], "2023-12"),
    (date(2024, 2, 5), ["2023-12", "2024-01", "2024-02"], "2024-01"),
    (date(2024, 12, 30), ["2024-11", "2024-12", "2025-01"], "2024-11"),
    (date(2025, 9, 1), ["2025-08", "2025-09"], "2025-08"),
    (date(2024, 1, 8), ["2024-01", "2026-10"], None),
    (date(2024, 1, 8), [], None),
])
def test_manual_historical_reruns_use_only_prior_months(client, review_calls, week_start, months, expected):
    client.portal.call(seed, week_start, months)
    for _ in range(2):
        response = client.post("/api/agents/rollup/weekly", params={"week_start": str(week_start)})
        assert response.status_code == 200, response.text
        assert review_calls[-1].monthly_context == expected
        assert review_calls[-1].week_start == week_start

    async def persisted():
        async with db.get_sessionmaker()() as session:
            return (await session.exec(select(WeeklySummary))).all()

    assert len(client.portal.call(persisted)) == 1


def test_context_keeps_four_prior_weeks_without_raw_journals(client, review_calls):
    week_start = date(2024, 1, 8)
    client.portal.call(partial(seed, week_start, ["2023-12", "2026-10"], past_weeks=True))
    response = client.post("/api/agents/rollup/weekly", params={"week_start": str(week_start)})
    assert response.status_code == 200, response.text
    deps = review_calls[0]
    assert deps.monthly_context == "2023-12"
    assert [week["week_start"] for week in deps.past_weeks] == [
        str(week_start - timedelta(weeks=offset)) for offset in (4, 3, 2, 1)
    ]
    assert len(deps.days) == 1
    assert "Private journal text" not in str(deps)


@pytest.mark.parametrize("prior_month", [True, False])
def test_scheduler_catchup_ignores_newer_months(client, review_calls, prior_month):
    async def scenario():
        months = ["2024-01", "2026-10"]
        if prior_month:
            months.append("2023-12")
        await seed(date(2024, 1, 8), months)
        await review_scheduler.run_due(db.get_sessionmaker(), date(2026, 11, 2))
        historical = [deps for deps in review_calls if deps.week_start == date(2024, 1, 8)]
        assert len(historical) == 1
        assert historical[0].monthly_context == ("2023-12" if prior_month else None)
        await review_scheduler.run_due(db.get_sessionmaker(), date(2026, 11, 2))
        assert len(review_calls) == 1

    client.portal.call(scenario)
