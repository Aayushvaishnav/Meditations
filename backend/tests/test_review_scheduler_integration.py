from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import select

from app import agents, db, main, review_scheduler
from app.models import DailyScore, JournalEntry, MonthlySummary, ReviewJob, WeeklySummary
from app import ai_orchestration as routes


DAY = date(2026, 1, 12)
TODAY = date(2026, 2, 2)


@pytest.fixture(autouse=True)
def isolated_scheduler(monkeypatch):
    monkeypatch.setattr(
        main, "get_app_settings", lambda: SimpleNamespace(journal_scheduled_reviews=False)
    )


@pytest.fixture
def runners(monkeypatch):
    calls = []
    indexed = []
    model = object()

    async def request_model(session, fast=False):
        return model

    async def daily(deps, **kwargs):
        assert kwargs["model"] is model
        calls.append(("daily", deps))
        return agents.DailyReviewOutput(llm_nudge=3, feedback="Daily feedback", key_insight="Daily insight")

    async def weekly(deps, **kwargs):
        assert kwargs["model"] is model
        calls.append(("weekly", deps))
        return agents.WeeklyReviewOutput(wins="Weekly wins", misses="Weekly misses", carried_action_items="Next steps")

    async def monthly(deps, **kwargs):
        assert kwargs["model"] is model
        calls.append(("monthly", deps))
        return agents.MonthlyReviewOutput(narrative="Monthly narrative")

    async def index_document(session, document_id, kind, content):
        indexed.append((document_id, kind, content))

    monkeypatch.setattr(routes, "_request_model", request_model)
    monkeypatch.setattr(routes, "index_document", index_document)
    monkeypatch.setattr(agents, "run_daily_review", daily)
    monkeypatch.setattr(agents, "run_weekly_review", weekly)
    monkeypatch.setattr(agents, "run_monthly_review", monthly)
    return calls, indexed


async def seed():
    async with db.get_sessionmaker()() as session:
        session.add(JournalEntry(date=DAY, raw_markdown="Worked on the project"))
        await session.commit()


async def jobs():
    async with db.get_sessionmaker()() as session:
        return {(row.kind, row.period): row.state for row in (await session.exec(select(ReviewJob))).all()}


def test_real_rollups_persist_all_tiers_in_dependency_order(client, runners):
    calls, indexed = runners

    async def scenario():
        await seed()
        await review_scheduler.run_due(db.get_sessionmaker(), TODAY)
        assert [kind for kind, _ in calls] == ["daily", "weekly", "monthly"]
        daily_deps, weekly_deps, monthly_deps = [deps for _, deps in calls]
        assert daily_deps.day == DAY
        assert daily_deps.today_raw == "Worked on the project"
        assert weekly_deps.week_start == DAY
        assert monthly_deps.month == "2026-01"
        async with db.get_sessionmaker()() as session:
            daily = await session.get(DailyScore, DAY)
            weekly = await session.get(WeeklySummary, DAY)
            monthly = await session.get(MonthlySummary, "2026-01")
            assert daily.feedback == "Daily feedback"
            assert daily.insight == "Daily insight"
            assert daily.llm_nudge == 3
            assert weekly.wins == "Weekly wins"
            assert weekly.carried_action_items == "Next steps"
            assert monthly.narrative == "Monthly narrative"
            assert weekly.avg_score == pytest.approx(daily.final_score)
            assert monthly.avg_score == pytest.approx(weekly.avg_score)
            assert weekly_deps.days[0]["score"] == daily.final_score
            assert monthly_deps.weeks[0]["wins"] == weekly.wins
        assert await jobs() == {
            ("daily", "2026-01-12"): "completed",
            ("weekly", "2026-01-12"): "completed",
            ("monthly", "2026-01"): "completed",
        }
        assert [item[0] for item in indexed] == ["weekly:2026-01-12", "monthly:2026-01"]
        await review_scheduler.run_due(db.get_sessionmaker(), TODAY)
        assert len(calls) == 3
        assert len(indexed) == 2

    client.portal.call(scenario)


def test_failed_review_remains_pending_and_retries(client, runners, monkeypatch):
    calls, _ = runners
    original = agents.run_daily_review
    attempts = 0

    async def fail_once(deps, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("provider unavailable")
        return await original(deps, **kwargs)

    monkeypatch.setattr(agents, "run_daily_review", fail_once)

    async def scenario():
        await seed()
        with pytest.raises(HTTPException) as error:
            await review_scheduler.run_due(db.get_sessionmaker(), TODAY)
        assert error.value.status_code == 502
        assert set((await jobs()).values()) == {"pending"}
        async with db.get_sessionmaker()() as session:
            assert await session.get(DailyScore, DAY) is None
        await review_scheduler.run_due(db.get_sessionmaker(), TODAY)
        assert attempts == 2
        assert [kind for kind, _ in calls] == ["daily", "weekly", "monthly"]
        assert set((await jobs()).values()) == {"completed"}

    client.portal.call(scenario)


@pytest.mark.parametrize("interrupted_kind", ["daily", "weekly", "monthly"])
def test_restart_after_result_commit_does_not_repeat_llm(client, runners, monkeypatch, interrupted_kind):
    calls, _ = runners
    original = review_scheduler.run_review

    async def interrupt_after_persist(session, kind, period):
        await original(session, kind, period)
        if kind == interrupted_kind:
            raise asyncio.CancelledError

    monkeypatch.setattr(review_scheduler, "run_review", interrupt_after_persist)

    async def scenario():
        await seed()
        with pytest.raises(asyncio.CancelledError):
            await review_scheduler.run_due(db.get_sessionmaker(), TODAY)
        period = {"daily": "2026-01-12", "weekly": "2026-01-12", "monthly": "2026-01"}[interrupted_kind]
        assert (await jobs())[(interrupted_kind, period)] == "pending"
        model, key = {
            "daily": (DailyScore, DAY),
            "weekly": (WeeklySummary, DAY),
            "monthly": (MonthlySummary, "2026-01"),
        }[interrupted_kind]
        async with db.get_sessionmaker()() as session:
            assert await session.get(model, key) is not None
        monkeypatch.setattr(review_scheduler, "run_review", original)
        await review_scheduler.run_due(db.get_sessionmaker(), TODAY)
        assert [kind for kind, _ in calls] == ["daily", "weekly", "monthly"]
        assert set((await jobs()).values()) == {"completed"}

    client.portal.call(scenario)


@pytest.mark.parametrize("enabled", [False, True])
def test_lifespan_starts_only_enabled_worker_and_cancels_on_exit(monkeypatch, enabled):
    events = []

    async def worker(sessions):
        assert sessions is db.get_sessionmaker()
        events.append("started")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("cancelled")

    monkeypatch.setattr(main, "get_app_settings", lambda: SimpleNamespace(journal_scheduled_reviews=enabled))
    monkeypatch.setattr(review_scheduler, "serve", worker)
    db.init_engine("sqlite+aiosqlite:///:memory:")
    with TestClient(main.app) as local_client:
        assert local_client.get("/api/health").status_code == 200
        assert events == (["started"] if enabled else [])
    assert events == (["started", "cancelled"] if enabled else [])
    assert not db.engine_initialized()


def test_multimonth_catchup_builds_context_before_later_reviews(client, runners):
    calls, _ = runners

    async def scenario():
        await seed()
        async with db.get_sessionmaker()() as session:
            session.add(JournalEntry(date=date(2026, 2, 9), raw_markdown="February work"))
            await session.commit()
        await review_scheduler.run_due(db.get_sessionmaker(), date(2026, 3, 2))
        feb_daily = next(deps for kind, deps in calls if kind == "daily" and deps.day.month == 2)
        feb_weekly = next(deps for kind, deps in calls if kind == "weekly" and deps.week_start.month == 2)
        assert feb_daily.weekly_context is not None
        assert feb_daily.monthly_context == "Monthly narrative"
        assert feb_weekly.monthly_context == "Monthly narrative"
        assert [kind for kind, _ in calls] == ["daily", "weekly", "monthly", "daily", "weekly", "monthly"]

    client.portal.call(scenario)
