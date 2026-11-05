"""Embedding ownership follows application lifespan, including failed startup."""

import asyncio
from argparse import Namespace

import pytest
from fastapi.testclient import TestClient

from app import db, main, search


@pytest.mark.parametrize("startup_failure", [False, True])
def test_embeddings_drain_before_database_disposal(monkeypatch, startup_failure):
    events = []
    original_dispose = db.dispose_engine

    async def shutdown():
        assert db.engine_initialized()
        events.append("embeddings-drained")

    async def dispose():
        assert events == ["embeddings-drained"]
        events.append("database-disposed")
        await original_dispose()

    async def failed_backfill(session):
        raise RuntimeError("injected recovery failure")

    monkeypatch.setattr(search, "shutdown_embeddings", shutdown)
    monkeypatch.setattr(db, "dispose_engine", dispose)
    if startup_failure:
        monkeypatch.setattr(search, "backfill_missing", failed_backfill)
    db.init_engine("sqlite+aiosqlite:///:memory:")
    if startup_failure:
        with pytest.raises(RuntimeError, match="injected recovery failure"):
            with TestClient(main.app):
                pytest.fail("Startup must fail before serving requests")
    else:
        with TestClient(main.app) as client:
            assert client.get("/api/health").status_code == 200
    assert events == ["embeddings-drained", "database-disposed"]
    assert not db.engine_initialized()


def test_seeder_startup_failure_closes_embeddings_and_database(monkeypatch):
    from scripts import seed_demo

    events = []
    original_dispose = db.dispose_engine

    async def fail_init():
        raise RuntimeError("injected schema failure")

    async def shutdown():
        assert db.engine_initialized()
        events.append("embeddings-drained")

    async def dispose():
        assert events == ["embeddings-drained"]
        events.append("database-disposed")
        await original_dispose()

    monkeypatch.setattr(seed_demo, "parse_args", lambda: Namespace(
        db=":memory:", start="2026-01-01", end="2026-01-02",
    ))
    monkeypatch.setattr(db, "init_db", fail_init)
    monkeypatch.setattr(search, "shutdown_embeddings", shutdown)
    monkeypatch.setattr(db, "dispose_engine", dispose)
    with pytest.raises(RuntimeError, match="injected schema failure"):
        asyncio.run(seed_demo.main())
    assert events == ["embeddings-drained", "database-disposed"]
    assert not db.engine_initialized()
