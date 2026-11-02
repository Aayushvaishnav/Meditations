from __future__ import annotations

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


@pytest.fixture()
def client():
    db.init_engine("sqlite+aiosqlite:///:memory:")
    with TestClient(app) as c:
        yield c
