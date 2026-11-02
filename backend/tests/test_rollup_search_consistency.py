from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

import pytest

from app import agents, db, search
from app.models import MonthlySummary, WeeklySummary
from app.routers import agents as agent_routes

DAY = dt.date(2026, 9, 7)
MONTH = "2026-09"


@pytest.fixture(autouse=True)
def hermetic_agents(monkeypatch):
    monkeypatch.setattr(search, "embed_texts", lambda texts: None)
    monkeypatch.setattr(agent_routes, "utc_now", lambda: dt.datetime(2026, 9, 7, 12))

    async def fake_model(session, fast=False):
        return object()

    monkeypatch.setattr(agent_routes, "_request_model", fake_model)


@contextmanager
def failing_index(monkeypatch):
    execute = search._execute

    async def fail_after_insert(session, sql, params=None):
        result = await execute(session, sql, params)
        if sql.startswith("INSERT INTO fts_entries"):
            raise RuntimeError("injected index failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(search, "_execute", fail_after_insert)
        yield


def search_ids(client, word):
    response = client.get("/api/search", params={"q": word})
    assert response.status_code == 200
    return [hit["doc_id"] for hit in response.json()]


def stored_summary(client, kind):
    async def read():
        async with db.get_sessionmaker()() as session:
            row = await session.get(
                WeeklySummary if kind == "weekly" else MonthlySummary,
                DAY if kind == "weekly" else MONTH,
            )
            return row.model_dump() if row is not None else None

    return client.portal.call(read)


@pytest.mark.parametrize("kind", ["weekly", "monthly"])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_rollup_index_failure_rolls_back_source_and_search(client, monkeypatch, kind, operation):
    word = "originalword"

    async def weekly(deps, model=None, **kwargs):
        return agents.WeeklyReviewOutput(
            wins=word, misses="Missed rest", carried_action_items="Protect mornings"
        )

    async def monthly(deps, model=None, **kwargs):
        return agents.MonthlyReviewOutput(narrative=word)

    monkeypatch.setattr(agents, "run_weekly_review", weekly)
    monkeypatch.setattr(agents, "run_monthly_review", monthly)
    assert client.put(f"/api/journal/{DAY}", json={"raw_markdown": "seedjournal"}).status_code == 200
    if kind == "monthly":
        assert client.post("/api/agents/rollup/weekly", params={"week_start": str(DAY)}).status_code == 200

    params = {"week_start": str(DAY)} if kind == "weekly" else {"month": MONTH}
    endpoint = f"/api/agents/rollup/{kind}"
    doc_id = f"{kind}:{DAY if kind == 'weekly' else MONTH}"
    if operation == "update":
        assert client.post(endpoint, params=params).status_code == 200
        assert doc_id in search_ids(client, word)
    before = stored_summary(client, kind)

    word = "replacementword"
    with failing_index(monkeypatch):
        with pytest.raises(RuntimeError, match="injected index failure"):
            client.post(endpoint, params=params)

    assert stored_summary(client, kind) == before
    assert doc_id not in search_ids(client, "replacementword")
    assert (doc_id in search_ids(client, "originalword")) == (operation == "update")


@pytest.fixture
def capture_runner(monkeypatch):
    async def capture(text, today, model=None, **kwargs):
        assert today == DAY
        return agents.CaptureOutput(
            tasks=[agents.CapturedTask(title="Captured task one"), agents.CapturedTask(title="Captured task two")],
            journal_snippet="capturedword",
        )

    monkeypatch.setattr(agents, "run_capture", capture)


@pytest.mark.parametrize("existing", [False, True], ids=["new", "append"])
def test_capture_is_immediately_searchable(client, capture_runner, existing):
    if existing:
        assert client.put(f"/api/journal/{DAY}", json={"raw_markdown": "originalword"}).status_code == 200
    response = client.post("/api/agents/capture", json={"text": "Capture this"})
    assert response.status_code == 200
    assert len(response.json()["tasks"]) == 2
    assert search_ids(client, "capturedword") == [f"journal:{DAY}"]
    entry = client.get(f"/api/journal/{DAY}").json()
    assert "capturedword" in entry["raw_markdown"]
    if existing:
        assert "originalword" in entry["raw_markdown"]
        assert search_ids(client, "originalword") == [f"journal:{DAY}"]


@pytest.mark.parametrize("existing", [False, True], ids=["new", "append"])
def test_capture_index_failure_rolls_back_tasks_and_snippet(client, monkeypatch, capture_runner, existing):
    if existing:
        assert client.put(f"/api/journal/{DAY}", json={"raw_markdown": "originalword"}).status_code == 200
    baseline_task = client.post("/api/tasks", json={"title": "Unrelated task"})
    assert baseline_task.status_code == 201
    tasks_before = client.get("/api/tasks").json()
    entry_before = client.get(f"/api/journal/{DAY}")

    with failing_index(monkeypatch):
        with pytest.raises(RuntimeError, match="injected index failure"):
            client.post("/api/agents/capture", json={"text": "Capture this"})

    assert client.get("/api/tasks").json() == tasks_before
    entry_after = client.get(f"/api/journal/{DAY}")
    assert entry_after.status_code == entry_before.status_code
    assert entry_after.json() == entry_before.json()
    assert search_ids(client, "capturedword") == []
    assert search_ids(client, "originalword") == ([f"journal:{DAY}"] if existing else [])
