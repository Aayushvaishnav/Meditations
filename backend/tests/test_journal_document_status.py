from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import text

from app import db, search

DAY = "2026-09-07"
URL = f"/api/journal/{DAY}"
DOC = f"journal:{DAY}"


@pytest.fixture(autouse=True)
def embeddings(monkeypatch):
    monkeypatch.setattr(search, "embed_texts", lambda texts: [[1.0] + [0.0] * 383 for _ in texts])


def execute(client, sql, **params):
    async def run():
        async with db.get_sessionmaker()() as session:
            result = await session.execute(text(sql), params)
            rows = result.all() if result.returns_rows else []
            await session.commit()
            return rows

    return client.portal.call(run)


def status(client):
    response = client.get(f"{URL}/status")
    assert response.status_code == 200
    return response.json()


def save(client, content="current text", **ratings):
    response = client.put(URL, json={"raw_markdown": content, **ratings})
    assert response.status_code == 200
    return response.json()


def test_absent_status_is_read_only(client):
    assert status(client) == {
        "date": DAY, "entry_exists": False, "updated_at": None,
        "keyword": "not_applicable", "semantic": "not_applicable",
    }
    assert client.get(URL).status_code == 404


def test_rating_only_is_an_entry_without_searchable_text(client):
    saved = save(client, " \n", mood=4)
    result = status(client)
    assert result["entry_exists"] is True
    assert result["updated_at"] == saved["updated_at"]
    assert result["keyword"] == result["semantic"] == "not_applicable"


def test_text_is_ready_without_embedding_on_status_read(client, monkeypatch):
    saved = save(client)

    def unexpected(texts):
        pytest.fail("status must not perform inference")

    monkeypatch.setattr(search, "embed_texts", unexpected)
    result = status(client)
    assert result["updated_at"] == saved["updated_at"]
    assert result["keyword"] == result["semantic"] == "ready"


@pytest.mark.parametrize("damage,keyword", [
    ("UPDATE fts_entries SET content = 'stale' WHERE doc_id = :doc", "missing"),
    ("UPDATE fts_entries SET kind = 'weekly' WHERE doc_id = :doc", "missing"),
    ("DELETE FROM fts_entries WHERE doc_id = :doc", "missing"),
    ("INSERT INTO fts_entries SELECT * FROM fts_entries WHERE doc_id = :doc", "missing"),
    ("UPDATE search_vector_state SET state = 'pending' WHERE doc_id = :doc", "ready"),
    ("DELETE FROM search_vector_state WHERE doc_id = :doc", "ready"),
    ("DELETE FROM vec_entries WHERE doc_id = :doc", "ready"),
])
def test_damage_is_detected_and_reindex_repairs_without_changing_source(client, damage, keyword):
    save(client)
    before = client.get(URL).json()
    execute(client, damage, doc=DOC)
    result = status(client)
    assert result["keyword"] == keyword
    assert result["semantic"] == "missing"
    repaired = client.post(f"{URL}/reindex")
    assert repaired.status_code == 200
    assert repaired.json()["keyword"] == repaired.json()["semantic"] == "ready"
    assert client.get(URL).json() == before


def test_unavailable_vector_extension(client, monkeypatch):
    save(client)
    monkeypatch.setattr(search, "_vec_ready", False)
    assert status(client)["semantic"] == "unavailable"
    assert status(client)["keyword"] == "ready"
    assert client.post(f"{URL}/reindex").json()["semantic"] == "unavailable"


def test_embedding_failure_retains_keyword_and_pending_receipt(client, monkeypatch):
    save(client)
    monkeypatch.setattr(search, "embed_texts", lambda texts: None)
    result = client.post(f"{URL}/reindex").json()
    assert result["keyword"] == "ready"
    assert result["semantic"] == "missing"
    assert execute(client, "SELECT state FROM search_vector_state WHERE doc_id = :doc", doc=DOC) == [("pending",)]


@pytest.mark.parametrize("rating_only", [False, True])
def test_reindex_cleans_orphans_for_absent_or_rating_only_document(client, rating_only):
    save(client)
    assert client.delete(URL).status_code == 204
    if rating_only:
        save(client, "", energy=3)
    execute(client, "INSERT INTO fts_entries(content, kind, doc_id) VALUES ('orphan', 'journal', :doc)", doc=DOC)
    result = client.post(f"{URL}/reindex").json()
    assert result["entry_exists"] is rating_only
    assert result["keyword"] == result["semantic"] == "not_applicable"
    assert execute(client, "SELECT doc_id FROM fts_entries WHERE doc_id = :doc", doc=DOC) == []
    assert execute(client, "SELECT doc_id FROM search_vector_state WHERE doc_id = :doc", doc=DOC) == []
    assert execute(client, "SELECT doc_id FROM vec_entries WHERE doc_id = :doc", doc=DOC) == []


def test_reindex_failure_rolls_back_all_index_changes(client, monkeypatch):
    save(client)
    original = search._execute

    async def fail(session, sql, params=None):
        result = await original(session, sql, params)
        if sql.startswith("INSERT INTO fts_entries"):
            raise RuntimeError("injected failure")
        return result

    monkeypatch.setattr(search, "_execute", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        client.post(f"{URL}/reindex")
    assert status(client)["semantic"] == "ready"
    assert client.get(URL).json()["raw_markdown"] == "current text"


def test_zero_match_fts_delete_takes_writer_lock(tmp_path):
    path = tmp_path / "writer-lock.db"
    with sqlite3.connect(path) as first, sqlite3.connect(path, timeout=0) as second:
        first.execute("PRAGMA journal_mode=WAL")
        first.execute(search.FTS_DDL)
        first.commit()
        first.execute("DELETE FROM fts_entries WHERE 0")
        assert first.in_transaction
        assert second.execute("SELECT count(*) FROM fts_entries").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            second.execute("INSERT INTO fts_entries(content) VALUES ('concurrent')")
        first.commit()
        second.execute("INSERT INTO fts_entries(content) VALUES ('after commit')")
