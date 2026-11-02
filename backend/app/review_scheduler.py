"""Database-local review catch-up; no HTTP or desktop port discovery."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import DailyScore, JournalEntry, MonthlySummary, ReviewJob, WeeklySummary
from app.util import monday_of, utc_now

logger = logging.getLogger(__name__)
ReviewKind = Literal["daily", "weekly", "monthly"]


def month_closes(month: str) -> date:
    first = date.fromisoformat(f"{month}-01")
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return monday_of(next_month - timedelta(days=1)) + timedelta(days=7)


def period_closes(kind: ReviewKind, period: str) -> date:
    if kind == "monthly":
        return month_closes(period)
    start = date.fromisoformat(period)
    return start + timedelta(days=1 if kind == "daily" else 7)


async def run_review(session: AsyncSession, kind: ReviewKind, period: str) -> None:
    from app.routers.agents import rollup_daily, rollup_monthly, rollup_weekly

    if kind == "daily":
        await rollup_daily(session, day=date.fromisoformat(period))
    elif kind == "weekly":
        await rollup_weekly(session, week_start=date.fromisoformat(period))
    else:
        await rollup_monthly(session, month=period)


async def run_due(sessions: async_sessionmaker[AsyncSession], today: date) -> None:
    """Process closed UTC periods; persisted summaries recover interrupted commits."""
    async with sessions() as session:
        days = (await session.exec(select(JournalEntry.date))).all()
        weeks = {monday_of(day) for day in days}
        weeks.update((await session.exec(select(WeeklySummary.week_start))).all())
        candidates: list[tuple[ReviewKind, str]] = [
            ("daily", day.isoformat()) for day in sorted(days) if day < today
        ]
        candidates.extend(
            ("weekly", week.isoformat()) for week in sorted(weeks)
            if week + timedelta(days=7) <= today
        )
        candidates.extend(
            ("monthly", month) for month in sorted({week.strftime("%Y-%m") for week in weeks})
            if month_closes(month) <= today
        )
        jobs = list((await session.exec(select(ReviewJob))).all())
        known = {(job.kind, job.period) for job in jobs}
        for kind, period in candidates:
            if (kind, period) not in known:
                job = ReviewJob(kind=kind, period=period, state="pending")
                session.add(job)
                jobs.append(job)
        await session.commit()
        order = {"daily": 0, "weekly": 1, "monthly": 2}
        keys = sorted(
            (
                (job.kind, job.period) for job in jobs
                if job.state == "pending" and period_closes(job.kind, job.period) <= today
            ),
            key=lambda key: (period_closes(*key), order[key[0]], key[1]),
        )

    for kind, period in keys:
        async with sessions() as session:
            job = await session.get(ReviewJob, (kind, period))
            model = {"daily": DailyScore, "weekly": WeeklySummary, "monthly": MonthlySummary}[kind]
            key = period if kind == "monthly" else date.fromisoformat(period)
            if await session.get(model, key) is None:
                try:
                    await run_review(session, kind, period)
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    await session.rollback()
                    job = await session.get(ReviewJob, (kind, period))
                    job.state = "skipped"
                else:
                    job.state = "completed"
            else:
                job.state = "completed"
            session.add(job)
            await session.commit()


async def serve(sessions: async_sessionmaker[AsyncSession]) -> None:
    while True:
        try:
            await run_due(sessions, utc_now().date())
        except Exception:
            logger.exception("Scheduled review failed; pending work will retry next pass")
        await asyncio.sleep(60)
