"""HTTP adapters for AI workflows; orchestration is shared with the scheduler."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from app import ai_orchestration as workflows
from app.routers.deps import SessionDep
from app.schemas import DailyScoreResponse

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("/rollup/daily", response_model=DailyScoreResponse)
async def rollup_daily(session: SessionDep, day: dt.date | None = None):
    """Run the daily review agent for one journal day and persist its score."""
    return await workflows.rollup_daily(session=session, day=day)


@router.post("/rollup/daily/stream")
async def rollup_daily_stream(session: SessionDep, day: dt.date | None = None):
    """Same agent as /rollup/daily, but streams partial reviews via SSE and
    persists the completed one. Events: partial (object) → done (score JSON) /
    error."""
    return await workflows.rollup_daily_stream(session=session, day=day)


@router.post("/rollup/weekly")
async def rollup_weekly(session: SessionDep, week_start: dt.date | None = None):
    """Roll up one ISO week (Mon-based); defaults to the current UTC week."""
    return await workflows.rollup_weekly(session=session, week_start=week_start)


@router.post("/rollup/monthly")
async def rollup_monthly(session: SessionDep, month: str | None = Query(default=None, pattern=r"^(previous|[0-9]{4}-[0-9]{2})$")):
    """Roll up one month ('YYYY-MM', or 'previous'/None). Defaults to the
    current month, or the previous one on the 1st."""
    return await workflows.rollup_monthly(session=session, month=month)


@router.post("/decompose")
async def decompose_task(session: SessionDep, body: workflows.DecomposeRequest):
    """Break a task into AI-planned subtasks and persist them under it."""
    return await workflows.decompose_task(session=session, body=body)


@router.post("/capture")
async def capture(session: SessionDep, body: workflows.CaptureRequest):
    """Conversational capture: extract tasks from free text, register them and
    append the snippet to today's journal (plan §6.3.4)."""
    return await workflows.capture(session=session, body=body)


@router.post("/briefing")
async def morning_briefing(session: SessionDep):
    """Conversational daily planning: recommends the Top 3 focus (plan §6.3.3)."""
    return await workflows.morning_briefing(session=session)


@router.post("/briefing/stream")
async def morning_briefing_stream(session: SessionDep):
    """Streams partial BriefingOutput objects. Events: partial (object) → done / error."""
    return await workflows.morning_briefing_stream(session=session)


@router.post("/ask/stream")
async def ask_second_brain(session: SessionDep, body: workflows.AskRequest):
    """Answer a question over journals/rollups: hybrid search → streamed answer
    with [n] citations. Events: sources → partial (cumulative text) → done / error."""
    return await workflows.ask_second_brain(session=session, body=body)


@router.post("/assist/stream")
async def editor_assist(session: SessionDep, body: workflows.AssistRequest):
    """Streamed journal-text assist (improve/continue/summarize). Events:
    partial (cumulative markdown) → done / error."""
    return await workflows.editor_assist(session=session, body=body)
