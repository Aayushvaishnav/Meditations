from __future__ import annotations

import datetime as dt

import pytest

from app import agents, db, search
from app.models import MonthlySummary, WeeklySummary
from app.routers import agents as agent_routes


@pytest.fixture(autouse=True)
def isolated_monthly_agent(monkeypatch):
    monkeypatch.setattr(search, "embed_texts", lambda texts: None)
    calls = []

    async def fake_model(session, fast=False):
        return object()

    async def fake_review(deps, **kwargs):
        calls.append(deps)
        return agents.MonthlyReviewOutput(narrative="A steady month.")

    monkeypatch.setattr(agent_routes, "_request_model", fake_model)
    monkeypatch.setattr(agents, "run_monthly_review", fake_review)
    return calls


PERIOD_CASES = [
    ("2026-10-15", None, "2026-10"),
    ("2026-10-31", None, "2026-10"),
    ("2026-10-01", None, "2026-09"),
    ("2026-01-01", None, "2025-12"),
    ("2026-01-15", "previous", "2025-12"),
    ("2026-03-01", "previous", "2026-02"),
    ("2024-03-15", "previous", "2024-02"),
    ("2026-10-01", "2026-10", "2026-10"),
    ("2026-10-15", "2025-12", "2025-12"),
]


@pytest.mark.parametrize("today,month,expected", PERIOD_CASES)
@pytest.mark.parametrize("has_weeks", [False, True])
def test_monthly_period_resolution(
    client, monkeypatch, isolated_monthly_agent, today, month, expected, has_weeks
):
    monkeypatch.setattr(
        agent_routes, "utc_now", lambda: dt.datetime.fromisoformat(today + "T12:00:00")
    )
    year, mon = map(int, expected.split("-"))
    start = dt.date(year, mon, 1)
    monday = start + dt.timedelta(days=(-start.weekday()) % 7)
    neighbor = start - dt.timedelta(days=start.weekday() or 7)

    async def seed():
        async with db.get_sessionmaker()() as session:
            for day, score in [(neighbor, 10.0)] + ([(monday, 80.0)] if has_weeks else []):
                session.add(WeeklySummary(
                    week_start=day, avg_score=score, trend="stable", wins="Progress", misses="Rest"
                ))
            await session.commit()

    client.portal.call(seed)
    response = client.post(
        "/api/agents/rollup/monthly", params={} if month is None else {"month": month}
    )
    if not has_weeks:
        assert response.status_code == 404
        assert expected in response.json()["detail"]
        assert not isolated_monthly_agent
        return

    assert response.status_code == 200
    assert response.json()["month"] == expected
    assert response.json()["avg_score"] == 80.0
    deps, = isolated_monthly_agent
    assert deps.month == expected
    assert [week["week_start"] for week in deps.weeks] == [str(monday)]

    async def stored():
        async with db.get_sessionmaker()() as session:
            row = await session.get(MonthlySummary, expected)
            assert row is not None
            assert row.avg_score == 80.0

    client.portal.call(stored)


@pytest.mark.parametrize("month", [
    "", "garbage", "Previous", "2026", "2026-00", "2026-13", "0000-01",
    "2026-10-01", "2026-1", "26-10", "2026-+1", "2026- 1", " 2026-10",
])
def test_invalid_month_returns_422(client, isolated_monthly_agent, month):
    response = client.post("/api/agents/rollup/monthly", params={"month": month})
    assert response.status_code == 422
    assert not isolated_monthly_agent
