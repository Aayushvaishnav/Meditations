"""Shared workflow invariants independent of HTTP dispatch."""

import pytest
from fastapi import HTTPException

from app import agents, ai_orchestration as workflows


@pytest.mark.anyio
@pytest.mark.parametrize("fast", [False, True])
async def test_request_model_uses_effective_settings_and_preserves_resilience(monkeypatch, fast):
    session = object()
    settings = object()
    model = object()

    async def load(actual):
        assert actual is session
        return settings

    def create(actual, **kwargs):
        assert actual is settings
        # Unspecified resilient preserves the factory's retry wrapper
        assert kwargs == {"fast": fast}
        return model

    monkeypatch.setattr(workflows, "load_ai_settings", load)
    monkeypatch.setattr(workflows, "create_agent_model", create)
    assert await workflows._request_model(session, fast=fast) is model


@pytest.mark.parametrize("stream", [False, True])
def test_briefing_transports_share_context_prompt_usage_and_final_shape(client, monkeypatch, stream):
    data = {"overdue_tasks": [{"id": "late", "title": "late"}], "due_today": [{"id": "today", "title": "today"}, {"id": "next", "title": "next"}]}
    model = object()
    recorder = object()
    seen = []
    review = agents.BriefingOutput(top_focus=["a", "b", "c", "d"], reasoning="why")

    async def context(session):
        return data

    async def request_model(session, fast=False):
        assert fast is True
        return model

    async def overrides(session):
        return {"briefing": "custom prompt"}

    def check(actual, kwargs):
        assert actual is data
        assert kwargs == {"model": model, "system_prompt": "custom prompt", "on_usage": recorder}
        seen.append(True)

    async def run(actual, **kwargs):
        check(actual, kwargs)
        return review

    async def chunks(actual, **kwargs):
        check(actual, kwargs)
        yield review

    monkeypatch.setattr(workflows, "_briefing_data", context)
    monkeypatch.setattr(workflows, "_request_model", request_model)
    monkeypatch.setattr(workflows, "load_prompt_overrides", overrides)
    monkeypatch.setattr(workflows, "make_recorder", lambda session: recorder)
    monkeypatch.setattr(agents, "run_briefing", run)
    monkeypatch.setattr(agents, "stream_briefing", chunks)
    response = client.post("/api/agents/briefing" + ("/stream" if stream else ""))
    assert response.status_code == 200
    expected = {
        "top_focus": ["a", "b", "c"],
        "recommendations": [{"text": text, "task_id": None} for text in ["a", "b", "c"]],
        "reasoning": "why",
        "overdue_count": 1,
        "due_today_count": 2,
    }
    if stream:
        import json
        events = response.text.split("\n\n")
        done = next(event for event in events if "event: done" in event)
        assert json.loads(done.split("data: ", 1)[1]) == expected
    else:
        assert response.json() == expected
    assert seen == [True]


@pytest.mark.anyio
async def test_provider_failure_is_described_at_nonstream_boundary(monkeypatch):
    async def fail():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(workflows, "describe_ai_error", lambda exc: "friendly failure")
    with pytest.raises(HTTPException) as error:
        await workflows._llm_call(fail())
    assert error.value.status_code == 502
    assert error.value.detail == "AI request failed: friendly failure"


def test_stream_failure_emits_error_without_done(client, monkeypatch):
    async def context(session):
        return {"overdue_tasks": [], "due_today": []}

    async def model(session, fast=False):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(workflows, "_briefing_data", context)
    monkeypatch.setattr(workflows, "_request_model", model)
    monkeypatch.setattr(workflows, "describe_ai_error", lambda exc: "friendly failure")
    response = client.post("/api/agents/briefing/stream")
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "friendly failure" in response.text
    assert "event: done" not in response.text
