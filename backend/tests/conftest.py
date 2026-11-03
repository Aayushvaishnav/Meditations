from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_app_settings
from app.main import app


@pytest.fixture(autouse=True)
def disable_scheduled_reviews(monkeypatch):
    monkeypatch.setenv("JOURNAL_SCHEDULED_REVIEWS", "false")
    get_app_settings.cache_clear()
    yield
    get_app_settings.cache_clear()


@pytest.fixture(autouse=True)
def isolate_calendar_worker(monkeypatch):
    from app.calendar_sync import queue_worker

    async def idle(sessions, manager, *, worker):
        # StaticPool shares one connection; exercise concurrent workers in dedicated tests
        await asyncio.Event().wait()

    monkeypatch.setattr(queue_worker, "serve", idle)


@pytest.fixture()
def client():
    db.init_engine("sqlite+aiosqlite:///:memory:")
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def isolate_webhook_worker(monkeypatch):
    from app.webhooks import service

    async def idle(worker):
        # StaticPool shares one connection; dedicated webhook tests drive delivery explicitly
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "serve", idle)
