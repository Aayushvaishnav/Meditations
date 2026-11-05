"""Lifetime streaks must not inherit chart or completion-rate windows."""

from datetime import date, datetime, timedelta

import pytest

from app import db
from app.models import Habit, HabitLog, JournalEntry
from app.routers import insights

TODAY = date(2026, 11, 5)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(insights, "utc_now", lambda: datetime(2026, 11, 5, 12))


def seed(client, *rows):
    async def persist():
        async with db.get_sessionmaker()() as session:
            session.add_all(rows)
            await session.commit()

    client.portal.call(persist)


def journal(offset, **kwargs):
    return JournalEntry(date=TODAY - timedelta(days=offset), **{"raw_markdown": "Reflection", **kwargs})


def read_insights(client, days=14):
    response = client.get("/api/insights", params={"days": days})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("days", [14, 30, 90])
@pytest.mark.parametrize("last_offset", [0, 1])
def test_45_day_streaks_ignore_chart_and_rate_windows(client, days, last_offset):
    habit = Habit(name="Read")
    seed(client, habit)
    offsets = range(last_offset, last_offset + 45)
    seed(
        client,
        *(journal(offset) for offset in offsets),
        *(HabitLog(habit_id=habit.id, date=TODAY - timedelta(days=offset)) for offset in offsets),
    )

    body = read_insights(client, days)
    assert body["journaling_streak"] == 45
    assert body["journaling_best"] == 45
    assert body["habits"] == [{
        "id": habit.id, "name": "Read", "current_streak": 45,
        "rate_30": round((30 - last_offset) / 30, 3),
    }]
    assert len(body["series"]) == days
    assert body["series"][0]["date"] == (TODAY - timedelta(days=days - 1)).isoformat()
    assert body["series"][-1]["date"] == TODAY.isoformat()


def test_streaks_have_no_replacement_history_cap(client):
    habit = Habit(name="Read")
    seed(client, habit)
    seed(
        client,
        *(journal(offset) for offset in range(700)),
        *(HabitLog(habit_id=habit.id, date=TODAY - timedelta(days=offset)) for offset in range(700)),
    )
    body = read_insights(client)
    assert body["journaling_streak"] == body["journaling_best"] == 700
    assert body["habits"][0]["current_streak"] == 700
    assert body["habits"][0]["rate_30"] == 1


@pytest.mark.parametrize("days", [14, 30, 90])
def test_old_best_run_survives_chart_changes_and_recent_gap(client, days):
    seed(client, *(journal(offset) for offset in range(800, 860)), journal(0), journal(1), journal(3))
    body = read_insights(client, days)
    assert body["journaling_streak"] == 2
    assert body["journaling_best"] == 60


def test_rating_only_entries_participate_but_empty_rows_and_future_days_do_not(client):
    seed(
        client,
        journal(0, raw_markdown="", mood=3),
        journal(1, raw_markdown=" \n\t", energy=4),
        journal(2),
        journal(3, raw_markdown=" \n\t\r\u00a0"),
        journal(4),
        *(journal(offset) for offset in range(-8, 0)),
    )
    body = read_insights(client)
    assert body["journaling_streak"] == 3
    assert body["journaling_best"] == 3
    assert body["series"][-1]["mood"] == 3
    assert body["series"][-2]["energy"] == 4


def test_habit_rate_is_inclusive_30_day_window_and_excludes_future_and_incomplete_logs(client):
    habit = Habit(name="Read")
    weekly = Habit(name="Weekly", target_frequency="weekly")
    seed(client, habit, weekly)
    seed(
        client,
        *(HabitLog(habit_id=habit.id, date=TODAY - timedelta(days=offset)) for offset in [0, 1, 3, 29, 30, -1, -2]),
        HabitLog(habit_id=habit.id, date=TODAY - timedelta(days=2), completed=False),
        HabitLog(habit_id=weekly.id, date=TODAY),
    )
    body = read_insights(client)
    assert body["habits"] == [{"id": habit.id, "name": "Read", "current_streak": 2, "rate_30": 0.133}]


@pytest.mark.parametrize("offsets, expected_best", [([], 0), ([2, 3], 2), ([-2, -1], 0)])
def test_no_current_streak_without_today_or_yesterday(client, offsets, expected_best):
    habit = Habit(name="Read")
    seed(client, habit)
    seed(
        client,
        *(journal(offset) for offset in offsets),
        *(HabitLog(habit_id=habit.id, date=TODAY - timedelta(days=offset)) for offset in offsets),
    )
    body = read_insights(client)
    assert body["journaling_streak"] == 0
    assert body["journaling_best"] == expected_best
    assert body["habits"][0]["current_streak"] == 0


def test_habit_histories_remain_independent(client):
    first, second = Habit(name="First"), Habit(name="Second")
    seed(client, first, second)
    seed(
        client,
        *(HabitLog(habit_id=first.id, date=TODAY - timedelta(days=offset)) for offset in range(45)),
        *(HabitLog(habit_id=second.id, date=TODAY - timedelta(days=offset)) for offset in [1, 2, 4]),
    )
    habits = {h["id"]: h for h in read_insights(client)["habits"]}
    assert habits[first.id]["current_streak"] == 45
    assert habits[first.id]["rate_30"] == 1
    assert habits[second.id]["current_streak"] == 2
    assert habits[second.id]["rate_30"] == 0.1
