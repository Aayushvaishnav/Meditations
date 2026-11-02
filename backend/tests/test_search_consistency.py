from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from app import db, search
from app.models import JournalEntry

DAY = "2026-09-07"


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    monkeypatch.setattr(search, "embed_texts", lambda texts: None)


def run_db(client, operation):
    async def run():
        async with db.get_sessionmaker()() as session:
            return await operation(session)

    return client.portal.call(run)


@pytest.mark.parametrize("operation", ["create", "update", "delete", "empty"])
def test_journal_index_failure_rolls_back_source_and_index(client, monkeypatch, operation):
    if operation != "create":
        assert client.put(f"/api/journal/{DAY}", json={"raw_markdown": "originalword"}).status_code == 200

    execute = search._execute

    async def fail_after_write(session, sql, params=None):
        result = await execute(session, sql, params)
        if sql.startswith("INSERT INTO fts_entries") or (
            operation in {"delete", "empty"} and sql.startswith("DELETE FROM fts_entries")
        ):
            raise RuntimeError("injected index failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(search, "_execute", fail_after_write)
        with pytest.raises(RuntimeError, match="injected index failure"):
            if operation == "delete":
                client.delete(f"/api/journal/{DAY}")
            else:
                client.put(f"/api/journal/{DAY}", json={"raw_markdown": "" if operation == "empty" else "replacementword"})

    response = client.get(f"/api/journal/{DAY}")
    if operation == "create":
        assert response.status_code == 404
        assert client.get("/api/search", params={"q": "replacementword"}).json() == []
    else:
        assert response.json()["raw_markdown"] == "originalword"
        assert client.get("/api/search", params={"q": "originalword"}).json()
        assert client.get("/api/search", params={"q": "replacementword"}).json() == []


@pytest.mark.parametrize("rebuild", [False, True])
def test_recovery_replaces_stale_content_and_removes_orphans(client, rebuild):
    async def corrupt(session):
        session.add(JournalEntry(date=dt.date.fromisoformat(DAY), raw_markdown="currentword"))
        await search.index_document(session, f"journal:{DAY}", "journal", "staleword")
        await search.index_document(session, "journal:2026-09-01", "journal", "ghostword")
        await session.commit()

    run_db(client, corrupt)
    if rebuild:
        assert client.post("/api/search/reindex").status_code == 200
    else:
        assert run_db(client, search.backfill_missing) >= 1
    assert client.get("/api/search", params={"q": "currentword"}).json()
    for word in ["staleword", "ghostword"]:
        assert client.get("/api/search", params={"q": word}).json() == []


def test_embedding_failure_keeps_fts_available(client, monkeypatch):
    def unavailable(texts):
        raise RuntimeError("embedding inference unavailable")

    monkeypatch.setattr(search, "embed_texts", unavailable)
    assert client.put(f"/api/journal/{DAY}", json={"raw_markdown": "searchableword"}).status_code == 200
    assert client.get("/api/search", params={"q": "searchableword"}).json()


def unit_vector(axis):
    vector = [0.0] * search.EMBED_DIM
    vector[axis] = 1.0
    return vector


def vector_ids(client):
    async def read(session):
        return set((await session.execute(text("SELECT doc_id FROM vec_entries"))).scalars())

    return run_db(client, read)


@pytest.mark.parametrize("unavailable", ["none", "exception"])
def test_unavailable_embeddings_remove_stale_vectors_and_recover(client, monkeypatch, unavailable):
    if not search.vec_available():
        pytest.skip("sqlite-vec unavailable")
    monkeypatch.setattr(search, "embed_texts", lambda texts: [unit_vector(0) for _ in texts])
    client.put(f"/api/journal/{DAY}", json={"raw_markdown": "oldword"})
    assert f"journal:{DAY}" in vector_ids(client)

    def offline(texts):
        if unavailable == "exception":
            raise RuntimeError("offline")
        return None

    monkeypatch.setattr(search, "embed_texts", offline)
    client.put(f"/api/journal/{DAY}", json={"raw_markdown": "currentword"})
    assert f"journal:{DAY}" not in vector_ids(client)
    assert client.get("/api/search", params={"q": "currentword"}).json()

    monkeypatch.setattr(search, "embed_texts", lambda texts: [unit_vector(1) for _ in texts])
    assert run_db(client, search.backfill_missing) == 1
    assert f"journal:{DAY}" in vector_ids(client)
    assert run_db(client, search.backfill_missing) == 0
    assert client.get("/api/search", params={"q": "currentword"}).json()[0]["sources"] == ["fts", "semantic"]


@pytest.mark.parametrize("rebuild", [False, True])
def test_recovery_removes_vector_only_orphans(client, monkeypatch, rebuild):
    if not search.vec_available():
        pytest.skip("sqlite-vec unavailable")
    monkeypatch.setattr(search, "embed_texts", lambda texts: [unit_vector(0) for _ in texts])

    async def corrupt(session):
        await search.index_document(session, "journal:2026-01-01", "journal", "ghostword")
        await session.execute(text("DELETE FROM fts_entries"))
        await session.commit()

    run_db(client, corrupt)
    if rebuild:
        client.post("/api/search/reindex")
    else:
        run_db(client, search.backfill_missing)
    assert vector_ids(client) == set()
    assert client.get("/api/search", params={"q": "ghostword"}).json() == []


@pytest.mark.parametrize("rebuild", [False, True])
def test_failed_recovery_rolls_back_all_index_changes(client, monkeypatch, rebuild):
    client.put(f"/api/journal/{DAY}", json={"raw_markdown": "originalword"})

    async def change_source(session):
        entry = await session.get(JournalEntry, dt.date.fromisoformat(DAY))
        entry.raw_markdown = "currentword"
        session.add(entry)
        await session.commit()

    run_db(client, change_source)
    execute = search._execute

    async def fail_after_insert(session, sql, params=None):
        result = await execute(session, sql, params)
        if sql.startswith("INSERT INTO fts_entries"):
            raise RuntimeError("injected rebuild failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(search, "_execute", fail_after_insert)
        with pytest.raises(RuntimeError, match="injected rebuild failure"):
            run_db(client, search.reindex if rebuild else search.backfill_missing)
    assert client.get("/api/search", params={"q": "originalword"}).json()
    assert client.get("/api/search", params={"q": "currentword"}).json() == []
    run_db(client, search.reindex if rebuild else search.backfill_missing)
    assert client.get("/api/search", params={"q": "currentword"}).json()


def test_vector_storage_failure_rolls_back_fts_and_source(client, monkeypatch):
    if not search.vec_available():
        pytest.skip("sqlite-vec unavailable")
    monkeypatch.setattr(search, "embed_texts", lambda texts: [unit_vector(0) for _ in texts])
    client.put(f"/api/journal/{DAY}", json={"raw_markdown": "originalword"})
    execute = search._execute

    async def fail_vector_write(session, sql, params=None):
        result = await execute(session, sql, params)
        if sql.startswith("INSERT INTO vec_entries"):
            raise RuntimeError("injected vector write failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(search, "_execute", fail_vector_write)
        with pytest.raises(RuntimeError, match="injected vector write failure"):
            client.put(f"/api/journal/{DAY}", json={"raw_markdown": "replacementword"})
    assert client.get(f"/api/journal/{DAY}").json()["raw_markdown"] == "originalword"
    assert client.get("/api/search", params={"q": "originalword"}).json()
    assert vector_ids(client) == {f"journal:{DAY}"}
    assert client.get("/api/search", params={"q": "originalword"}).json()[0]["sources"] == ["fts", "semantic"]


@pytest.mark.parametrize("restored_inference", ["ready", "none", "exception"])
def test_extension_outage_marks_existing_vectors_stale(client, monkeypatch, restored_inference):
    if not search.vec_available():
        pytest.skip("sqlite-vec unavailable")
    monkeypatch.setattr(search, "embed_texts", lambda texts: [unit_vector(0) for _ in texts])
    client.put(f"/api/journal/{DAY}", json={"raw_markdown": "oldword"})
    with monkeypatch.context() as patch:
        patch.setattr(search, "_vec_ready", False)
        client.put(f"/api/journal/{DAY}", json={"raw_markdown": "currentword"})
    assert f"journal:{DAY}" in vector_ids(client)

    def restored(texts):
        if restored_inference == "exception":
            raise RuntimeError("inference unavailable")
        if restored_inference == "none":
            return None
        return [unit_vector(1) for _ in texts]

    monkeypatch.setattr(search, "embed_texts", restored)
    assert run_db(client, search.backfill_missing) == 1
    if restored_inference != "ready":
        assert vector_ids(client) == set()
        assert client.get("/api/search", params={"q": "currentword"}).json()
        monkeypatch.setattr(search, "embed_texts", lambda texts: [unit_vector(1) for _ in texts])
        assert run_db(client, search.backfill_missing) == 1

    async def read_embedding(session):
        import struct

        blob = (await session.execute(text("SELECT embedding FROM vec_entries WHERE doc_id = :d"), {"d": f"journal:{DAY}"})).scalar_one()
        return list(struct.unpack(f"{search.EMBED_DIM}f", blob))

    assert run_db(client, read_embedding) == unit_vector(1)
    assert run_db(client, search.backfill_missing) == 0


@pytest.mark.parametrize("kind", ["journal", "weekly", "monthly"])
@pytest.mark.parametrize("damage", ["missing", "stale", "duplicate"])
def test_startup_reconciles_all_source_kinds(client, kind, damage):
    from app.models import MonthlySummary, WeeklySummary

    doc_id = f"{kind}:2026-09" if kind == "monthly" else f"{kind}:{DAY}"

    async def seed(session):
        if kind == "journal":
            source = JournalEntry(date=dt.date.fromisoformat(DAY), raw_markdown="currentword")
        elif kind == "weekly":
            source = WeeklySummary(week_start=dt.date.fromisoformat(DAY), avg_score=50, trend="stable", wins="currentword", misses="", carried_action_items="")
        else:
            source = MonthlySummary(month="2026-09", avg_score=50, trend="stable", narrative="currentword")
        session.add(source)
        if damage != "missing":
            await search.index_document(session, doc_id, kind, "staleword")
        if damage == "duplicate":
            await session.execute(text("INSERT INTO fts_entries(doc_id, kind, content) VALUES (:d, :k, 'duplicateword')"), {"d": doc_id, "k": kind})
        await session.commit()

    run_db(client, seed)
    assert run_db(client, search.backfill_missing) == 1
    assert client.get("/api/search", params={"q": "currentword"}).json()[0]["doc_id"] == doc_id
    assert client.get("/api/search", params={"q": "staleword duplicateword"}).json() == []


@pytest.mark.parametrize("damage", ["missing_metadata", "missing_vector", "metadata_orphan"])
def test_recovery_repairs_vector_metadata_damage(client, monkeypatch, damage):
    if not search.vec_available():
        pytest.skip("sqlite-vec unavailable")
    monkeypatch.setattr(search, "embed_texts", lambda texts: [unit_vector(0) for _ in texts])
    client.put(f"/api/journal/{DAY}", json={"raw_markdown": "currentword"})

    async def corrupt(session):
        if damage == "missing_metadata":
            await session.execute(text("DELETE FROM search_vector_state"))
        elif damage == "missing_vector":
            await session.execute(text("DELETE FROM vec_entries"))
        else:
            await session.execute(text("INSERT INTO search_vector_state VALUES ('journal:2026-01-01', 'pending')"))
        await session.commit()

    run_db(client, corrupt)
    assert run_db(client, search.backfill_missing) == 1
    assert run_db(client, search.backfill_missing) == 0
    assert vector_ids(client) == {f"journal:{DAY}"}
    assert client.get("/api/search", params={"q": "currentword"}).json()[0]["sources"] == ["fts", "semantic"]
