"""Public documentation remains on the HTTP adapters after workflow extraction."""

import pytest
from fastapi import FastAPI

from app.routers.agents import router


@pytest.fixture(scope="module")
def operations():
    app = FastAPI()
    app.include_router(router)
    return app.openapi()["paths"]


@pytest.mark.parametrize("path", [
    "/rollup/daily", "/rollup/daily/stream", "/rollup/weekly", "/rollup/monthly",
    "/decompose", "/capture", "/briefing", "/briefing/stream", "/ask/stream",
    "/assist/stream",
])
def test_ai_operations_publish_workflow_descriptions(operations, path):
    assert operations[f"/api/agents{path}"]["post"]["description"].strip()


@pytest.mark.parametrize("path", [
    "/rollup/daily/stream", "/briefing/stream", "/ask/stream", "/assist/stream",
])
def test_ai_stream_descriptions_explain_event_contract(operations, path):
    description = operations[f"/api/agents{path}"]["post"]["description"]
    assert all(event in description for event in ("partial", "done", "error"))
