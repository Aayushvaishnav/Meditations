from __future__ import annotations

import asyncio
from datetime import date
import sqlite3

from app import db
from app.models import (
    DailyScore, FocusSession, Habit, HabitLog, JournalEntry, MonthlySummary,
    Task, TaskList, WeeklySummary,
)
from app.recovery import restore_database


def test_download_restore_preserves_source_records_and_relationships(client, tmp_path):
    day = date(2026, 1, 1)

    async def seed():
        async with db.get_sessionmaker()() as session:
            session.add_all([
                TaskList(id="list", name="Work"),
                Habit(id="habit", name="Walk"),
                JournalEntry(date=day, raw_markdown="# Journal", mood=4, energy=3),
            ])
            await session.commit()
            session.add(Task(id="parent", list_id="list", title="Parent", status="completed"))
            await session.commit()
            session.add_all([
                Task(id="child", parent_id="parent", title="Child"),
                FocusSession(task_id="parent", duration_minutes=25),
                HabitLog(habit_id="habit", date=day),
                DailyScore(date=day, deterministic_score=80, final_score=81,
                           rubric_breakdown_json="{}", feedback="Feedback", insight="Insight"),
                WeeklySummary(week_start=date(2025, 12, 29), avg_score=81,
                              trend="stable", wins="Win", misses="Miss"),
                MonthlySummary(month="2026-01", avg_score=81, trend="stable", narrative="Review"),
            ])
            await session.commit()

    client.portal.call(seed)
    response = client.post("/api/backup")
    assert response.status_code == 200
    backup, target = tmp_path / "download.db", tmp_path / "restored.db"
    backup.write_bytes(response.content)
    asyncio.run(restore_database(backup, target))
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT list_id,status FROM tasks WHERE id='parent'").fetchone() == ("list", "completed")
        assert conn.execute("SELECT parent_id FROM tasks WHERE id='child'").fetchone() == ("parent",)
        assert conn.execute("SELECT raw_markdown,mood,energy FROM journal_entries").fetchone() == ("# Journal", 4, 3)
        assert conn.execute("SELECT final_score FROM daily_scores").fetchone() == (81,)
        assert conn.execute("SELECT wins FROM weekly_summaries").fetchone() == ("Win",)
        assert conn.execute("SELECT narrative FROM monthly_summaries").fetchone() == ("Review",)
        assert conn.execute("SELECT task_id,duration_minutes FROM focus_sessions").fetchone() == ("parent", 25)
        assert conn.execute("SELECT habit_id,completed FROM habit_logs").fetchone() == ("habit", 1)
