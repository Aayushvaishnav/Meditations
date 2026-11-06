"""Q&A request bounds are enforced before retrieval and model execution."""

from __future__ import annotations

import pytest

from app import agents
from app import ai_orchestration as routes


@pytest.fixture
def ask_calls(monkeypatch):
    calls = {"search": [], "model": [], "runner": []}

    async def search(session, query, *, limit):
        calls["search"].append(query)
        return []

    async def model(session, fast=False):
        calls["model"].append(fast)
        return object()

    async def stream(deps, **kwargs):
        calls["runner"].append(deps.question)
        yield "answer"

    monkeypatch.setattr(routes, "hybrid_search", search)
    monkeypatch.setattr(routes, "_request_model", model)
    monkeypatch.setattr(agents, "stream_ask", stream)
    return calls


@pytest.mark.parametrize(
    "question",
    ["a" * 4000, "界" * 4000, "🙂" * 4000, "e\u0301" * 2000],
    ids=["ascii", "cjk", "emoji", "combining"],
)
def test_exact_question_limit_reaches_retrieval_and_model_unchanged(client, ask_calls, question):
    response = client.post("/api/agents/ask/stream", json={"question": question})

    assert response.status_code == 200
    assert "event: done" in response.text
    assert ask_calls == {"search": [question], "model": [True], "runner": [question]}


@pytest.mark.parametrize(
    "question",
    [
        "a" * 4001,
        "界" * 4001,
        "🙂" * 4001,
        "e\u0301" * 2000 + "e",
        " " + "a" * 4000,
        "a" * 100_000,
    ],
    ids=["ascii", "cjk", "emoji", "combining", "whitespace", "large"],
)
def test_oversized_question_is_rejected_before_retrieval_or_model(client, ask_calls, question):
    response = client.post("/api/agents/ask/stream", json={"question": question})

    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "question"]
    assert error["type"] == "string_too_long"
    assert error["ctx"]["max_length"] == 4000
    assert "4000" in error["msg"]
    assert ask_calls == {"search": [], "model": [], "runner": []}


def test_question_whitespace_normalization_is_preserved(client, ask_calls):
    response = client.post("/api/agents/ask/stream", json={"question": "  Why?\n"})

    assert response.status_code == 200
    assert ask_calls == {"search": ["Why?"], "model": [True], "runner": ["Why?"]}


def test_blank_question_is_rejected_before_retrieval_or_model(client, ask_calls):
    response = client.post("/api/agents/ask/stream", json={"question": " \n\t"})

    assert response.status_code == 422
    assert ask_calls == {"search": [], "model": [], "runner": []}
