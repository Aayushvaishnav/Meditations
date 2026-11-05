from __future__ import annotations

import asyncio
import threading

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

from app import search
from app.embedding_worker import EmbeddingWorker, shutdown_embedding_worker


def test_embedding_does_not_block_heartbeat(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def embed(texts):
        entered.set()
        assert release.wait(5)
        return [[1.0]]

    monkeypatch.setattr(search, "embed_texts", embed)

    async def run():
        task = asyncio.create_task(search._optional_embeddings(["hello"], search.EmbeddingPass()))
        try:
            for _ in range(1000):
                if entered.is_set():
                    break
                await asyncio.sleep(0.001)
            assert entered.is_set()
            assert not task.done()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/api/health")).status_code == 200
            assert not task.done()
        finally:
            release.set()
        assert await task == [[1.0]]
        await shutdown_embedding_worker()

    asyncio.run(run())


def test_cancellation_keeps_inference_serialized_and_shutdown_drains():
    worker = EmbeddingWorker()
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def first():
        entered.set()
        assert release.wait(5)

    async def run():
        task = asyncio.create_task(worker.run(first))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        second = asyncio.create_task(worker.run(second_entered.set))
        await asyncio.sleep(0.02)
        assert not second_entered.is_set()
        closing = asyncio.create_task(worker.shutdown())
        await asyncio.sleep(0.02)
        assert not closing.done()
        release.set()
        await closing
        try:
            await second
        except asyncio.CancelledError:
            pass
        with pytest.raises(RuntimeError, match="shut down"):
            await worker.run(lambda: None)
        await worker.shutdown()

    try:
        asyncio.run(run())
    finally:
        release.set()


@pytest.mark.parametrize("failure", ["init", "inference"])
@pytest.mark.parametrize("rebuild", [False, True])
def test_recovery_failure_is_once_per_pass_and_later_retries(client, monkeypatch, failure, rebuild):
    from app import db
    from app.models import JournalEntry
    import datetime as dt

    if not search.vec_available():
        pytest.skip("sqlite-vec unavailable")
    calls = []
    monkeypatch.setattr(search, "embed_texts", lambda texts: None)

    async def seed():
        async with db.get_sessionmaker()() as session:
            for day in range(1, 4):
                session.add(JournalEntry(date=dt.date(2026, 9, day), raw_markdown="searchableword"))
            await session.commit()

    client.portal.call(seed)
    # Exercise real embed_texts with a model stub; no model initialization/download

    def unavailable_model():
        calls.append("init")
        if failure == "init":
            return None

        class Model:
            def embed(self, texts):
                raise RuntimeError("inference failed")

        return Model()

    # Use the original function captured independently of the fixture's patch
    monkeypatch.setattr(search, "embed_texts", REAL_EMBED_TEXTS)
    monkeypatch.setattr(search, "_embed_model", unavailable_model)

    async def recover():
        async with db.get_sessionmaker()() as session:
            return await (search.reindex(session) if rebuild else search.backfill_missing(session))

    client.portal.call(recover)
    assert len(calls) == 1
    client.portal.call(recover)
    assert len(calls) == 2
    monkeypatch.setattr(search, "embed_texts", lambda texts: [[1.0] + [0.0] * 383 for _ in texts])
    client.portal.call(recover)
    assert client.get("/api/search", params={"q": "searchableword"}).json()
    client.portal.call(shutdown_embedding_worker)


REAL_EMBED_TEXTS = search.embed_texts


def test_cancelled_shutdown_still_drains_running_thread():
    worker = EmbeddingWorker()
    entered = threading.Event()
    release = threading.Event()

    def embedding():
        entered.set()
        assert release.wait(5)

    async def run():
        inference = asyncio.create_task(worker.run(embedding))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        closing = asyncio.create_task(worker.shutdown())
        await asyncio.sleep(0.01)
        closing.cancel()
        await asyncio.sleep(0.01)
        assert not closing.done()
        closing.cancel()
        await asyncio.sleep(0.01)
        assert not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        await inference
        await worker.shutdown()

    try:
        asyncio.run(run())
    finally:
        release.set()


@pytest.mark.parametrize("state", ["pending", "missing"])
def test_semantic_search_excludes_vectors_without_ready_state(client, monkeypatch, state):
    from app import db
    from sqlalchemy import text

    if not search.vec_available():
        pytest.skip("sqlite-vec unavailable")
    monkeypatch.setattr(search, "embed_texts", lambda texts: [[1.0] + [0.0] * 383 for _ in texts])
    assert client.put("/api/journal/2026-09-01", json={"raw_markdown": "originalword"}).status_code == 200

    async def mark_stale():
        async with db.get_sessionmaker()() as session:
            if state == "pending":
                await session.execute(text("UPDATE search_vector_state SET state = 'pending'"))
            else:
                await session.execute(text("DELETE FROM search_vector_state"))
            await session.commit()

    client.portal.call(mark_stale)
    # Query vector matches the retained stale vector, but no keyword matches
    assert client.get("/api/search", params={"q": "unrelatedword"}).json() == []
    hits = client.get("/api/search", params={"q": "originalword"}).json()
    assert len(hits) == 1
    assert hits[0]["sources"] == ["fts"]
