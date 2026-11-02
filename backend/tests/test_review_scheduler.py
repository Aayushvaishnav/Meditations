from datetime import date
from pathlib import Path

import pytest

from app import db
from app.models import JournalEntry


@pytest.mark.anyio
async def test_catchup_targets_closed_periods_and_survives_restart(client, monkeypatch):
    from app import review_scheduler as scheduler

    async with db.get_sessionmaker()() as session:
        session.add(JournalEntry(date=date(2026, 1, 31), raw_markdown="January"))
        session.add(JournalEntry(date=date(2026, 2, 2), raw_markdown="Today"))
        await session.commit()
    calls = []

    async def run(session, kind, period):
        calls.append((kind, period))

    monkeypatch.setattr(scheduler, "run_review", run)
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 2))
    assert calls == [("daily", "2026-01-31"), ("weekly", "2026-01-26"), ("monthly", "2026-01")]
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 2))
    assert len(calls) == 3


def test_no_timer_can_post_to_a_development_backend():
    root = Path(__file__).resolve().parents[2]
    for service in (root / "systemd").glob("*.service"):
        assert "127.0.0.1:8000" not in service.read_text()


@pytest.mark.parametrize("month, closes", [
    ("2026-01", date(2026, 2, 2)),
    ("2026-12", date(2027, 1, 4)),
    ("2024-02", date(2024, 3, 4)),
    ("2026-05", date(2026, 6, 1)),
])
def test_month_waits_for_last_assigned_week(month, closes):
    from app.review_scheduler import month_closes

    assert month_closes(month) == closes


@pytest.mark.anyio
async def test_failures_keep_pending_work_and_block_parent_reviews(client, monkeypatch):
    from fastapi import HTTPException
    from sqlmodel import select

    from app import review_scheduler as scheduler
    from app.models import ReviewJob

    async with db.get_sessionmaker()() as session:
        session.add(JournalEntry(date=date(2025, 12, 31), raw_markdown="Year end"))
        await session.commit()
    calls = []

    async def fail(session, kind, period):
        calls.append((kind, period))
        raise HTTPException(502, "Provider unavailable")

    monkeypatch.setattr(scheduler, "run_review", fail)
    with pytest.raises(HTTPException):
        await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 1))
    assert calls == [("daily", "2025-12-31")]
    async with db.get_sessionmaker()() as session:
        assert {job.state for job in (await session.exec(select(ReviewJob))).all()} == {"pending"}

    async def success(session, kind, period):
        calls.append((kind, period))

    monkeypatch.setattr(scheduler, "run_review", success)
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 1))
    assert calls[1:] == [("daily", "2025-12-31"), ("weekly", "2025-12-29"), ("monthly", "2025-12")]


@pytest.mark.anyio
async def test_deleted_source_job_is_explicitly_skipped(client, monkeypatch):
    from app import review_scheduler as scheduler
    from app.models import ReviewJob

    async with db.get_sessionmaker()() as session:
        session.add(ReviewJob(kind="daily", period="2026-01-31", state="pending"))
        await session.commit()
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 2))
    async with db.get_sessionmaker()() as session:
        assert (await session.get(ReviewJob, ("daily", "2026-01-31"))).state == "skipped"
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 2))


@pytest.mark.anyio
async def test_passed_database_is_used_and_concurrent_dev_database_untouched(client, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import select
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app import migrations, review_scheduler as scheduler
    from app.models import ReviewJob

    async with db.get_sessionmaker()() as dev:
        dev.add(JournalEntry(date=date(2026, 1, 31), raw_markdown="Development"))
        await dev.commit()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await migrations.migrate(engine)
        async with sessions() as packaged:
            packaged.add(JournalEntry(date=date(2026, 1, 31), raw_markdown="Packaged"))
            await packaged.commit()
        calls = []

        async def run(session, kind, period):
            assert (await session.get(JournalEntry, date(2026, 1, 31))).raw_markdown == "Packaged"
            calls.append(kind)

        monkeypatch.setattr(scheduler, "run_review", run)
        await scheduler.run_due(sessions, date(2026, 2, 2))
        assert calls == ["daily", "weekly", "monthly"]
        async with db.get_sessionmaker()() as dev:
            assert (await dev.exec(select(ReviewJob))).all() == []
            assert (await dev.get(JournalEntry, date(2026, 1, 31))).raw_markdown == "Development"
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_only_closed_utc_days_and_weeks_run(client, monkeypatch):
    from app import review_scheduler as scheduler

    async with db.get_sessionmaker()() as session:
        session.add(JournalEntry(date=date(2026, 1, 31), raw_markdown="January"))
        await session.commit()
    calls = []

    async def run(session, kind, period):
        calls.append((kind, period))

    monkeypatch.setattr(scheduler, "run_review", run)
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 1, 31))
    assert calls == []
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 1))
    assert calls == [("daily", "2026-01-31")]
    await scheduler.run_due(db.get_sessionmaker(), date(2026, 2, 2))
    assert calls == [("daily", "2026-01-31"), ("weekly", "2026-01-26"), ("monthly", "2026-01")]


def test_retirement_script_removes_installed_units_without_http(tmp_path):
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2]
    unit_dir = tmp_path / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    for kind in ("daily", "weekly", "monthly"):
        for suffix in ("timer", "service"):
            (unit_dir / f"journal-{kind}.{suffix}").write_text("legacy unit")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n')
    systemctl.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}", "COMMAND_LOG": str(log)}
    for _ in range(2):
        subprocess.run(["bash", str(root / "systemd/install.sh")], env=env, check=True, capture_output=True)
    assert list(unit_dir.iterdir()) == []
    commands = log.read_text().splitlines()
    for kind in ("daily", "weekly", "monthly"):
        for suffix in ("timer", "service"):
            assert f"--user disable --now journal-{kind}.{suffix}" in commands
    assert commands.count("--user daemon-reload") == 2


@pytest.mark.parametrize("configured, expected", [("unset", "true"), ("false", "false"), ("true", "true")])
def test_sidecar_enables_scheduling_and_preserves_explicit_override(monkeypatch, configured, expected):
    import os
    from types import SimpleNamespace

    import sidecar_main
    import uvicorn

    monkeypatch.setenv("JOURNAL_SCHEDULED_REVIEWS", configured)
    if configured == "unset":
        monkeypatch.delenv("JOURNAL_SCHEDULED_REVIEWS")
    monkeypatch.setenv("MEDITATIONS_PORT", "49123")
    monkeypatch.setattr(sidecar_main.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    sidecar_main.main()
    assert os.environ["JOURNAL_SCHEDULED_REVIEWS"] == expected
    assert calls[0]["port"] == 49123


def test_standalone_scheduling_defaults_off(monkeypatch):
    from app.config import AppSettings

    monkeypatch.delenv("JOURNAL_SCHEDULED_REVIEWS", raising=False)
    assert AppSettings(_env_file=None).journal_scheduled_reviews is False
