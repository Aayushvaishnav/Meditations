"""Invariant tests for the synthetic data seeder (scripts/seed_demo.py).

Runs the generator against an in-memory engine — no fastembed, no file DB,
no network (generate() never indexes; reindex is a main()-only step).
"""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, time

from sqlmodel import select

from app import db
from app.models import (
    DailyScore,
    FocusSession,
    HabitLog,
    JournalEntry,
    MonthlySummary,
    Task,
    WeeklySummary,
)
from app.telemetry import collect_daily_metrics
from scripts.seed_demo import generate, mood_energy, phase_of, wipe_data


def _run_engine(coro_fn):
    """Boilerplate: in-memory engine -> init_db -> coro_fn(session) -> dispose."""

    async def runner():
        db.init_engine("sqlite+aiosqlite:///:memory:")
        try:
            await db.init_db()
            async with db.get_sessionmaker()() as session:
                return await coro_fn(session)
        finally:
            await db.dispose_engine()

    return asyncio.run(runner())


def test_dip_week_window_invariants():
    start, end = date(2026, 8, 17), date(2026, 8, 23)

    async def check(session):
        await wipe_data(session)
        stats = await generate(session, start, end, seed=7)

        entries = (await session.exec(select(JournalEntry))).all()
        tasks = (await session.exec(select(Task))).all()
        logs = (await session.exec(select(HabitLog))).all()
        focus = (await session.exec(select(FocusSession))).all()

        # one skipped day -> 6 entries, none empty, ratings in range or None
        assert stats["journal_entries"] == 6
        assert date(2026, 8, 20) not in {e.date for e in entries}
        for e in entries:
            assert e.raw_markdown.strip()
            assert e.mood is None or 1 <= e.mood <= 5
            assert e.energy is None or 1 <= e.energy <= 5

        # tasks: unique ids, naive datetimes, completed >= created, parents exist
        assert len({t.id for t in tasks}) == len(tasks)
        id_set = {t.id for t in tasks}
        for t in tasks:
            for dt in (t.due_date, t.completed_at, t.created_at, t.updated_at):
                assert dt is None or dt.tzinfo is None
            if t.completed_at:
                assert t.status == "completed"
                assert t.completed_at >= t.created_at
            if t.parent_id:
                assert t.parent_id in id_set

        # habit logs unique per (habit, day)
        assert len({(log.habit_id, log.date) for log in logs}) == len(logs)

        # focus sessions naive and inside the window
        for f in focus:
            assert f.created_at.tzinfo is None
            assert start <= f.created_at.date() <= end

        # AI rollups are outputs of the agents, never seeded
        assert (await session.exec(select(DailyScore))).all() == []
        assert (await session.exec(select(WeeklySummary))).all() == []
        assert (await session.exec(select(MonthlySummary))).all() == []

    _run_engine(check)


def test_journal_snapshot_matches_telemetry_full_window():
    """Stored snapshots must equal a fresh aggregation; briefing has material."""
    start, end = date(2026, 8, 10), date(2026, 9, 13)

    async def check(session):
        await generate(session, start, end, seed=42)

        entries = (await session.exec(select(JournalEntry))).all()
        assert len(entries) == 34  # 35 days minus the one skipped day
        for e in entries:
            m = await collect_daily_metrics(session, e.date)
            assert (e.hours_deep_work, e.tasks_planned, e.tasks_done) == (
                m.deep_work_hours,
                m.tasks_planned,
                m.tasks_completed,
            ), f"snapshot drift on {e.date}"

        open_tasks = [t for t in (await session.exec(select(Task))).all() if t.status in ("todo", "in_progress")]
        due_last_day = [t for t in open_tasks if t.due_date and t.due_date >= datetime.combine(end, time.min)]
        overdue = [t for t in open_tasks if t.due_date and t.due_date.date() < end]
        assert due_last_day, "expected tasks due on the final day (briefing)"
        assert overdue, "expected overdue tasks (briefing)"

    _run_engine(check)


def test_phase_and_mood_helpers():
    start = date(2026, 8, 10)
    assert phase_of(start, start) == "strong"
    assert phase_of(date(2026, 8, 19), start) == "dip"
    assert phase_of(date(2026, 9, 13), start) == "wind"
    assert phase_of(date(2027, 1, 1), start) == "wind"  # clamps past the arc
    assert mood_energy(random.Random(1), date(2026, 8, 22), "dip") == (5, 3)  # birthday override
    mood, energy = mood_energy(random.Random(1), date(2026, 8, 15), "strong")
    assert mood is None and (energy is None or 1 <= energy <= 5)  # no-mood UI edge day


def test_generate_is_deterministic():
    async def titles_for(seed: int) -> list[str]:
        db.init_engine("sqlite+aiosqlite:///:memory:")
        try:
            await db.init_db()
            async with db.get_sessionmaker()() as session:
                await generate(session, date(2026, 8, 10), date(2026, 8, 16), seed=seed)
                return sorted(t.title for t in (await session.exec(select(Task))).all())
        finally:
            await db.dispose_engine()

    assert asyncio.run(titles_for(42)) == asyncio.run(titles_for(42))


def test_inverted_window_is_safe():
    async def check(session):
        stats = await generate(session, date(2026, 9, 13), date(2026, 8, 10))
        assert stats["journal_entries"] == 0  # no crash, no entries
        assert (await session.exec(select(Task))).all() != []  # authored tasks still land

    _run_engine(check)
