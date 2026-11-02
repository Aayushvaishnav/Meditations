from __future__ import annotations

import asyncio
from datetime import date, datetime
import sqlite3


from app import db
from app.models import (
    DailyScore, FocusSession, Habit, HabitLog, JournalEntry, MonthlySummary,
    Task, TaskList, TimeBlock, WeeklySummary,
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
                TimeBlock(id="block", task_id="parent",
                          kind="timed", timezone="America/New_York",
                          start_at=datetime(2026, 1, 1, 23, 30, 0, 123456),
                          end_at=datetime(2026, 1, 2, 0, 30, 0, 654321),
                          created_at=datetime(2025, 12, 31, 12, 0, 0, 123456),
                          updated_at=datetime(2026, 1, 1, 12, 0, 0, 654321)),
                TimeBlock(id="all-day", task_id="parent", kind="all_day", timezone=None,
                          start_date=date(2025, 12, 31), end_date=date(2026, 1, 3),
                          created_at=datetime(2025, 12, 31, 12, 0, 0, 123456),
                          updated_at=datetime(2026, 1, 1, 12, 0, 0, 654321)),
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

        assert conn.execute(
            "SELECT id,task_id,kind,timezone,start_at,end_at,start_date,end_date,created_at,updated_at FROM time_blocks ORDER BY id"
        ).fetchall() == [(
            "all-day", "parent", "all_day", None, None, None,
            "2025-12-31", "2026-01-03", "2025-12-31 12:00:00.123456",
            "2026-01-01 12:00:00.654321",
        ), (
            "block", "parent", "timed", "America/New_York", "2026-01-01 23:30:00.123456",
            "2026-01-02 00:30:00.654321", None, None, "2025-12-31 12:00:00.123456",
            "2026-01-01 12:00:00.654321",
        )]


def test_restore_v5_migrates_without_inventing_time_blocks(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import migrations

    source, target = tmp_path / "v5.db", tmp_path / "restored.db"

    async def seed():
        engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
        try:
            async with engine.begin() as conn:
                for migration in migrations.MIGRATIONS[:5]:
                    await migration(conn)
                await conn.exec_driver_sql('PRAGMA user_version = 5')
                await conn.exec_driver_sql(
                    "INSERT INTO tasks (id,title,priority,status,actual_minutes,tags,order_index,"
                    "created_at,updated_at,deadline_date) VALUES "
                    "('legacy','Preserved',0,'todo',0,'[]',0,'2026-01-01','2026-01-01','2026-11-02')"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO focus_sessions VALUES "
                    "('focus','legacy',25,'pomodoro',NULL,'2026-01-01')"
                )
        finally:
            await engine.dispose()

    asyncio.run(seed())
    asyncio.run(restore_database(source, target))
    with sqlite3.connect(target) as conn:
        assert conn.execute('PRAGMA user_version').fetchone() == (migrations.LATEST_VERSION,)
        assert conn.execute('SELECT id,deadline_date FROM tasks').fetchall() == [('legacy', '2026-11-02')]
        assert conn.execute('SELECT task_id,duration_minutes FROM focus_sessions').fetchall() == [('legacy', 25)]
        assert conn.execute('SELECT * FROM time_blocks').fetchall() == []
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    with sqlite3.connect(source) as conn:
        assert conn.execute('PRAGMA user_version').fetchone() == (5,)


def test_restore_v6_preserves_timed_instants(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import migrations

    source, target = tmp_path / "v6.db", tmp_path / "restored.db"

    async def seed():
        engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
        try:
            async with engine.begin() as conn:
                for migration in migrations.MIGRATIONS[:6]:
                    await migration(conn)
                await conn.exec_driver_sql('PRAGMA user_version = 6')
                await conn.exec_driver_sql(
                    "INSERT INTO tasks (id,title,priority,status,actual_minutes,tags,order_index,"
                    "created_at,updated_at,deadline_date) VALUES "
                    "('legacy','Preserved',0,'todo',0,'[]',0,'2026-01-01','2026-01-01','2026-11-02')"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO focus_sessions VALUES "
                    "('focus','legacy',25,'pomodoro',NULL,'2026-01-01')"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO time_blocks VALUES ('block','legacy',"
                    "'2026-01-01 23:30:00.123456','2026-01-02 00:30:00.654321',"
                    "'2025-12-31 12:00:00.123456','2026-01-01 12:00:00.654321')"
                )
        finally:
            await engine.dispose()

    asyncio.run(seed())
    asyncio.run(restore_database(source, target))
    with sqlite3.connect(target) as conn:
        assert conn.execute('PRAGMA user_version').fetchone() == (migrations.LATEST_VERSION,)
        assert conn.execute('SELECT id,deadline_date FROM tasks').fetchall() == [('legacy', '2026-11-02')]
        assert conn.execute('SELECT task_id,duration_minutes FROM focus_sessions').fetchall() == [('legacy', 25)]
        assert conn.execute(
            "SELECT id,task_id,kind,timezone,start_at,end_at,start_date,end_date,"
            "created_at,updated_at FROM time_blocks"
        ).fetchall() == [(
            "block", "legacy", "timed", "UTC", "2026-01-01 23:30:00.123456",
            "2026-01-02 00:30:00.654321", None, None,
            "2025-12-31 12:00:00.123456", "2026-01-01 12:00:00.654321",
        )]
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    with sqlite3.connect(source) as conn:
        assert conn.execute('PRAGMA user_version').fetchone() == (6,)
