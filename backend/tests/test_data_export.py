from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from app import db
from app import models as m
from app.data_export import TABLES, create_export
from app.routers import data_export as router


@pytest.fixture
def anyio_backend():
    return "asyncio"


def unpack(content):
    with ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.anyio
async def test_all_records(client, tmp_path):
    stamp = datetime.fromisoformat("2026-10-30T12:34:56.123456")
    day = date(2026, 10, 30)
    text = "---\ntitle: café 📝\n---\n# Hi!\n**punctuation** `x`\r\n"
    records = [
        m.TaskList(id="list", name="生活", created_at=stamp),
        m.Task(
            id="parent",
            list_id="list",
            title="parent",
            created_at=stamp,
            updated_at=stamp,
        ),
        m.Habit(id="habit", name="walk", created_at=stamp),
        m.JournalEntry(
            date=day,
            raw_markdown=text,
            mood=4,
            energy=2,
            hours_deep_work=2.5,
            tasks_planned=3,
            tasks_done=2,
            created_at=stamp,
            updated_at=stamp,
        ),
        m.JournalEntry(date=date(2026, 10, 29), raw_markdown="", mood=3),
        m.WeeklySummary(
            week_start=date(2026, 10, 26),
            avg_score=70,
            trend="stable",
            wins="yes",
            misses="no",
            carried_action_items="next",
        ),
        m.MonthlySummary(
            month="2026-10", avg_score=70, trend="stable", narrative="故事"
        ),
        m.AppSetting(key="api_key", value="CREDENTIAL_CANARY"),
        m.AiUsage(id="usage", agent="CREDENTIAL_CANARY", model="secret"),
        m.ReviewJob(kind="daily", period="CREDENTIAL_CANARY", state="pending"),
        m.SearchVectorState(doc_id="CREDENTIAL_CANARY", state="pending"),
    ]
    async with db.get_sessionmaker()() as session:
        for record in records:
            session.add(record)
            await session.commit()
        task = m.Task(
            id="child",
            parent_id="parent",
            list_id="list",
            title="CREDENTIAL_IN_USER_TEXT",
            description="desc",
            priority=3,
            status="completed",
            due_date=stamp,
            estimated_minutes=45,
            actual_minutes=50,
            recurrence_rule="FREQ=DAILY",
            recurrence_series_id="opaque-series",
            recurrence_occurrence=7,
            tags=["é", "work"],
            order_index=1.25,
            completed_at=stamp,
            created_at=stamp,
            updated_at=stamp,
        )
        session.add(task)
        await session.commit()
        session.add_all(
            [
                m.TimeBlock(id="block", task_id="child", kind="timed",
                            timezone="Asia/Kolkata", start_at=stamp,
                            end_at=datetime(2026, 10, 31, 0, 15, 1, 654321),
                            created_at=stamp, updated_at=stamp),
                m.TimeBlock(id="all-day", task_id="child", kind="all_day",
                            timezone=None, start_date=date(2026, 10, 30),
                            end_date=date(2026, 11, 2),
                            created_at=stamp, updated_at=stamp),
                m.FocusSession(
                    id="focus",
                    task_id="child",
                    duration_minutes=50,
                    session_type="stopwatch",
                    notes="note",
                    created_at=stamp,
                ),
                m.HabitLog(id="log", habit_id="habit", date=day, completed=False),
                m.DailyScore(
                    date=day,
                    deterministic_score=70,
                    llm_nudge=2,
                    final_score=72,
                    rubric_breakdown_json='{"task": 70}',
                    feedback="feedback",
                    insight="insight",
                    created_at=stamp,
                ),
            ]
        )
        await session.commit()
    path = tmp_path / "export.zip"
    await create_export(db.get_engine(), path)
    files = unpack(path.read_bytes())
    assert set(files) == {
        "README.md",
        "manifest.json",
        "data.json",
        "journals/2026-10-29.md",
        "journals/2026-10-30.md",
    }
    assert files["journals/2026-10-30.md"] == text.encode()
    assert files["journals/2026-10-29.md"] == b""
    assert b"CREDENTIAL_CANARY" not in b"".join(files.values())
    assert b"CREDENTIAL_IN_USER_TEXT" in files["data.json"]
    data = json.loads(files["data.json"])
    manifest = json.loads(files["manifest.json"])
    assert manifest["version"] == 1 and manifest["exported_at"].endswith("Z")
    assert manifest["counts"] == {key: len(value) for key, value in data.items()}
    for model, fields in TABLES:
        expected = set(fields.split())
        if model is m.JournalEntry:
            expected = expected - {"raw_markdown"} | {"markdown_file"}
        assert all(set(row) == expected for row in data[model.__tablename__])
    assert data["time_blocks"] == [{
        "id": "all-day", "task_id": "child", "kind": "all_day", "timezone": None,
        "start_at": None, "end_at": None,
        "start_date": "2026-10-30", "end_date": "2026-11-02",
        "created_at": "2026-10-30T12:34:56.123456Z",
        "updated_at": "2026-10-30T12:34:56.123456Z",
    }, {
        "id": "block", "task_id": "child", "kind": "timed",
        "timezone": "Asia/Kolkata", "start_date": None, "end_date": None,
        "start_at": "2026-10-30T12:34:56.123456Z",
        "end_at": "2026-10-31T00:15:01.654321Z",
        "created_at": "2026-10-30T12:34:56.123456Z",
        "updated_at": "2026-10-30T12:34:56.123456Z",
    }]
    child = data["tasks"][0]
    assert child["id"] == "child" and child["parent_id"] == "parent"
    assert child["due_date"] == "2026-10-30T12:34:56.123456Z"
    assert (
        child["completed_at"]
        == child["created_at"]
        == child["updated_at"]
        == child["due_date"]
    )
    assert child["status"] == "completed" and child["list_id"] == "list"
    assert child["description"] == "desc" and child["priority"] == 3
    assert child["estimated_minutes"] == 45 and child["actual_minutes"] == 50
    assert child["order_index"] == 1.25
    assert (
        child["recurrence_rule"] == "FREQ=DAILY"
        and child["recurrence_series_id"] == "opaque-series"
    )
    assert child["tags"] == ["é", "work"] and child["recurrence_occurrence"] == 7
    assert data["tasks"][1]["due_date"] is None
    assert data["habit_logs"][0]["completed"] is False
    assert data["weekly_summaries"][0]["week_start"] == "2026-10-26"
    assert data["monthly_summaries"][0]["month"] == "2026-10"
    assert data["daily_scores"][0]["final_score"] == 72
    assert data["daily_scores"][0]["rubric_breakdown_json"] == '{"task": 70}'
    assert data["focus_sessions"][0]["task_id"] == "child"
    assert data["focus_sessions"][0]["notes"] == "note"
    assert data["focus_sessions"][0]["duration_minutes"] == 50
    assert data["habits"][0]["id"] == data["habit_logs"][0]["habit_id"] == "habit"
    assert (
        data["journal_entries"][1]["mood"] == 4
        and data["journal_entries"][1]["energy"] == 2
    )
    assert set(data) == {
        "lists",
        "tasks",
        "focus_sessions",
        "time_blocks",
        "habits",
        "habit_logs",
        "journal_entries",
        "daily_scores",
        "weekly_summaries",
        "monthly_summaries",
    }
    assert [task["id"] for task in data["tasks"]] == ["child", "parent"]
    await create_export(db.get_engine(), path)
    assert json.loads(unpack(path.read_bytes())["data.json"]) == data


@pytest.mark.anyio
async def test_empty(client, tmp_path):
    path = tmp_path / "empty.zip"
    await create_export(db.get_engine(), path)
    files = unpack(path.read_bytes())
    assert set(files) == {"README.md", "manifest.json", "data.json"}
    data = json.loads(files["data.json"])
    assert data["time_blocks"] == []
    assert json.loads(files["manifest.json"])["counts"]["time_blocks"] == 0
    assert all(value == [] for value in data.values())


@pytest.mark.anyio
async def test_wal_snapshot(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'isolated.db'}")
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.run_sync(SQLModel.metadata.create_all)
        await connection.execute(
            m.TaskList.__table__.insert().values(id="list", name="before")
        )
        await connection.execute(
            m.Task.__table__.insert().values(
                id="task", list_id="list", title="before", tags=[]
            )
        )
    read_started = asyncio.Event()
    writer_done = asyncio.Event()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def pause(connection, cursor, statement, parameters, context, many):
        if statement.startswith("SELECT lists."):
            read_started.set()
            connection.connection.await_(writer_done.wait())

    async def write():
        await read_started.wait()
        async with engine.begin() as connection:
            await connection.execute(m.TaskList.__table__.update().values(name="after"))
            await connection.execute(m.Task.__table__.update().values(title="after"))
        writer_done.set()

    try:
        await asyncio.gather(create_export(engine, tmp_path / "snapshot.zip"), write())
        data = json.loads(unpack((tmp_path / "snapshot.zip").read_bytes())["data.json"])
        assert data["lists"][0]["name"] == data["tasks"][0]["title"] == "before"
        async with engine.connect() as connection:
            assert (
                await connection.execute(m.Task.__table__.select())
            ).mappings().one()["title"] == "after"
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_creation_failure_cleanup(client, monkeypatch, tmp_path, error):
    directories = []

    def temporary(**kwargs):
        directory = TemporaryDirectory(dir=tmp_path, **kwargs)
        directories.append(Path(directory.name))
        return directory

    async def fail(engine, path):
        path.write_bytes(b"partial")
        raise error()

    monkeypatch.setattr(router, "TemporaryDirectory", temporary)
    monkeypatch.setattr(router, "create_export", fail)
    with pytest.raises(error):
        await router.download_export()
    assert directories and not directories[0].exists()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_send_failure_cleanup(client, error):
    response = await router.download_export()
    directory = Path(response.directory.name)

    async def send(message):
        raise error()

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(error):
        await response(
            {"type": "http", "method": "GET", "headers": [], "extensions": {}},
            receive,
            send,
        )
    assert not directory.exists()


def test_endpoint(client, monkeypatch, tmp_path):
    directories = []

    def temporary(**kwargs):
        directory = TemporaryDirectory(dir=tmp_path, **kwargs)
        directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(router, "TemporaryDirectory", temporary)
    response = client.post("/api/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert ".zip" in response.headers["content-disposition"]
    assert "data.json" in unpack(response.content)
    assert directories and all(not directory.exists() for directory in directories)


@pytest.mark.anyio
async def test_serializer_failure_cleanup(client, monkeypatch, tmp_path):
    from app import data_export

    directories = []

    def temporary(**kwargs):
        directory = TemporaryDirectory(dir=tmp_path, **kwargs)
        directories.append(Path(directory.name))
        return directory

    def fail(value):
        raise ValueError("serialization failed")

    monkeypatch.setattr(router, "TemporaryDirectory", temporary)
    monkeypatch.setattr(data_export, "_json_bytes", fail)
    with pytest.raises(ValueError, match="serialization failed"):
        await router.download_export()
    assert directories and not directories[0].exists()
