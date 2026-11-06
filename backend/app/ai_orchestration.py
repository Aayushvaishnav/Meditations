from __future__ import annotations

import datetime as dt
import json

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

import app.agents as agents
from app.ai_factory import create_agent_model, describe_ai_error, load_ai_settings, load_prompt_overrides
from app.ai_usage import make_recorder
from app.schemas import TaskResponse
from sqlalchemy import or_, and_, func
from app.models import DailyScore, JournalEntry, MonthlySummary, Task, WeeklySummary
from sqlmodel.ext.asyncio.session import AsyncSession
from app.schemas import DailyScoreResponse, saved_review_action
from app.scoring import ScoreBreakdown, compute_daily_score
from app.score_service import score_daily_metrics
from app.search import content_for, index_document
from app.search import search as hybrid_search
from app.sse import sse, stream_response
from app.telemetry import collect_daily_metrics
from app.util import monday_of, new_id, utc_now

# Bounded Q&A context (plan §3.3 discipline: token cost stays O(1))
ASK_MAX_SOURCES = 6
ASK_SOURCE_CHARS = 1200
ASK_MAX_HISTORY = 12  # render keeps the last 6 turns
ASK_MAX_QUESTION = 4000
ASSIST_SOURCE_CHARS = 6000


async def _request_model(session: AsyncSession, fast: bool = False):
    """Model built from the effective DB/env settings — env defaults alone
    would silently ignore the provider the user configured in Settings."""
    return create_agent_model(await load_ai_settings(session), fast=fast)


def trend_of(scores: list[float]) -> str:
    if len(scores) < 3:
        return "stable"
    mid = len(scores) // 2
    diff = sum(scores[mid:]) / len(scores[mid:]) - sum(scores[:mid]) / len(scores[:mid])
    if diff > 5:
        return "rising"
    if diff < -5:
        return "declining"
    return "stable"


async def _llm_call(awaitable_factory) -> object:
    try:
        return await awaitable_factory
    except Exception as exc:  # noqa: BLE001 — surface provider errors to the user
        raise HTTPException(status_code=502, detail=f"AI request failed: {describe_ai_error(exc)}") from exc


def _score_response(day: dt.date, breakdown: ScoreBreakdown, row: DailyScore) -> DailyScoreResponse:
    return DailyScoreResponse(
        date=day,
        task_score=breakdown.task_score,
        focus_score=breakdown.focus_score,
        habit_score=breakdown.habit_score,
        weighted_score=breakdown.weighted_score,
        llm_nudge=row.llm_nudge,
        final_score=row.final_score,
        target_deep_work_hours=breakdown.target_deep_work_hours,
        metrics=breakdown.metrics,
        persisted=True,
        score_basis="review_snapshot",
        saved_review_score=row.final_score,
        feedback=row.feedback,
        insight=row.insight,
        suggested_action_for_tomorrow=saved_review_action(row.rubric_breakdown_json),
    )


async def _daily_deps(session: AsyncSession, day: dt.date, metrics, entry: JournalEntry) -> agents.DailyDeps:
    """Bounded context for the daily agent (today + 6 past days + latest rollups)."""
    past_days: list[dict] = []
    for offset in range(1, 7):
        d = day - dt.timedelta(days=offset)
        past_entry = await session.get(JournalEntry, d)
        if past_entry is None:
            continue
        past_score = await session.get(DailyScore, d)
        past_days.append({"date": str(d), "score": past_score.final_score if past_score else None, "raw": past_entry.raw_markdown})

    current_week_start = monday_of(day)
    latest_weekly = (
        await session.exec(
            select(WeeklySummary).where(WeeklySummary.week_start < current_week_start).order_by(WeeklySummary.week_start.desc())
        )
    ).first()
    latest_monthly = (
        await session.exec(
            select(MonthlySummary).where(MonthlySummary.month < day.strftime("%Y-%m")).order_by(MonthlySummary.month.desc())
        )
    ).first()

    return agents.DailyDeps(
        day=day,
        today_raw=entry.raw_markdown,
        past_days=past_days,
        weekly_context=(latest_weekly.wins + "\n" + (latest_weekly.misses or "")) if latest_weekly else None,
        monthly_context=latest_monthly.narrative if latest_monthly else None,
        metrics=metrics.model_dump(),
    )


async def _persist_daily(session: AsyncSession, day: dt.date, breakdown: ScoreBreakdown, review: agents.DailyReviewOutput) -> DailyScore:
    # Upsert: re-running a review must replace the stored row, not collide on the PK.
    row = await session.get(DailyScore, day)
    if row is None:
        row = DailyScore(date=day)
    breakdown = compute_daily_score(
        breakdown.metrics, target_hours=breakdown.target_deep_work_hours, llm_nudge=review.llm_nudge
    )
    row.deterministic_score = breakdown.weighted_score
    row.llm_nudge = breakdown.llm_nudge
    row.final_score = breakdown.final_score
    row.rubric_breakdown_json = json.dumps(
        {
            **breakdown.model_dump(),
            "nudge_rationale": review.nudge_rationale,
            "suggested_action_for_tomorrow": review.suggested_action_for_tomorrow,
        },
        default=str,
    )
    row.feedback = review.feedback
    row.insight = review.key_insight
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _prepare_daily(session: AsyncSession, day: dt.date | None):
    """Freeze the metrics and bounded context before running either transport."""
    day = day or utc_now().date()
    entry = await session.get(JournalEntry, day)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No journal entry for {day}; write one first.")

    metrics = await collect_daily_metrics(session, day)
    breakdown = await score_daily_metrics(session, metrics)
    deps = await _daily_deps(session, day, metrics, entry)

    return day, breakdown, deps


async def rollup_daily(session: AsyncSession, day: dt.date | None = None):
    """Run the daily review agent for one journal day and persist its score."""
    day, breakdown, deps = await _prepare_daily(session, day)
    overrides = await load_prompt_overrides(session)
    review: agents.DailyReviewOutput = await _llm_call(
        agents.run_daily_review(
            deps,
            model=await _request_model(session),
            system_prompt=overrides.get("daily"),
            on_usage=make_recorder(session),
        )
    )

    row = await _persist_daily(session, day, breakdown, review)
    return _score_response(day, breakdown, row)


async def rollup_daily_stream(session: AsyncSession, day: dt.date | None = None):
    """Same agent as /rollup/daily, but streams partial reviews via SSE and
    persists the completed one. Events: partial (object) → done (score JSON) /
    error."""
    day, breakdown, deps = await _prepare_daily(session, day)
    overrides = await load_prompt_overrides(session)

    async def gen():
        review: agents.DailyReviewOutput | None = None
        try:
            async for partial in agents.stream_daily_review(
                deps,
                model=await _request_model(session),
                system_prompt=overrides.get("daily"),
                on_usage=make_recorder(session),
            ):
                review = partial
                yield sse("partial", partial.model_dump())
            if review is None:
                raise RuntimeError("agent returned no output")
            row = await _persist_daily(session, day, breakdown, review)
            yield sse("done", _score_response(day, breakdown, row).model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 — SSE can't change the HTTP status mid-stream
            yield sse("error", {"message": f"AI request failed: {describe_ai_error(exc)}"})

    return stream_response(gen())


async def rollup_weekly(session: AsyncSession, week_start: dt.date | None = None):
    """Roll up one ISO week (Mon-based); defaults to the current UTC week."""
    week_start = week_start or monday_of(utc_now().date())
    week_end = week_start + dt.timedelta(days=7)

    entries = (
        await session.exec(
            select(JournalEntry).where(JournalEntry.date >= week_start, JournalEntry.date < week_end).order_by(JournalEntry.date)
        )
    ).all()
    if not entries:
        raise HTTPException(status_code=404, detail=f"No journal entries in week {week_start}.")

    days: list[dict] = []
    scores: list[float] = []
    for entry in entries:
        stored = await session.get(DailyScore, entry.date)
        metrics = await collect_daily_metrics(session, entry.date)
        score = stored.final_score if stored else (await score_daily_metrics(session, metrics)).final_score
        scores.append(score)
        days.append(
            {
                "date": str(entry.date),
                "score": score,
                "tasks_done": metrics.tasks_completed,
                "tasks_planned": metrics.tasks_planned,
                "deep_work_hours": metrics.deep_work_hours,
            }
        )

    past_weeks = [
        {
            "week_start": str(w.week_start),
            "avg_score": w.avg_score,
            "wins": w.wins,
            "misses": w.misses,
            "carried": w.carried_action_items,
        }
        for w in (
            await session.exec(
                select(WeeklySummary).where(WeeklySummary.week_start < week_start).order_by(WeeklySummary.week_start.desc()).limit(4)
            )
        ).all()
    ][::-1]
    latest_monthly = (
        await session.exec(
            select(MonthlySummary)
            .where(MonthlySummary.month < week_start.strftime("%Y-%m"))
            .order_by(MonthlySummary.month.desc())
            .limit(1)
        )
    ).first()

    trend = trend_of(scores)
    overrides = await load_prompt_overrides(session)
    review: agents.WeeklyReviewOutput = await _llm_call(
        agents.run_weekly_review(
            agents.WeeklyDeps(
                week_start=week_start,
                days=days,
                past_weeks=past_weeks,
                monthly_context=latest_monthly.narrative if latest_monthly else None,
                trend=trend,
            ),
            model=await _request_model(session),
            system_prompt=overrides.get("weekly"),
            on_usage=make_recorder(session),
        )
    )

    week = await session.get(WeeklySummary, week_start)
    if week is None:
        week = WeeklySummary(week_start=week_start, avg_score=sum(scores) / len(scores), trend=trend)
    week.avg_score = sum(scores) / len(scores)
    week.trend = trend
    week.wins = review.wins
    week.misses = review.misses
    week.carried_action_items = review.carried_action_items
    session.add(week)
    await index_document(
        session,
        f"weekly:{week.week_start.isoformat()}",
        "weekly",
        "\n".join(filter(None, [week.wins, week.misses, week.carried_action_items])),
    )
    await session.commit()
    await session.refresh(week)
    return week


async def rollup_monthly(
    session: AsyncSession,
    month: str | None = None,
):
    """Roll up one month ('YYYY-MM', or 'previous'/None). Defaults to the
    current month, or the previous one on the 1st."""
    today = utc_now().date()
    if month == "previous" or (month is None and today.day == 1):
        first_of_this = today.replace(day=1)
        last_of_prev = first_of_this - dt.timedelta(days=1)
        month = last_of_prev.strftime("%Y-%m")
    elif month is None:
        month = today.strftime("%Y-%m")
    try:
        year, mon = (int(p) for p in month.split("-"))
        dt.date(year, mon, 1)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="month must be 'YYYY-MM' or 'previous'") from exc

    weeks = [
        w
        for w in (
            await session.exec(select(WeeklySummary).order_by(WeeklySummary.week_start))
        ).all()
        if w.week_start.year == year and w.week_start.month == mon
    ]
    if not weeks:
        raise HTTPException(status_code=404, detail=f"No weekly rollups found for {month}; run weekly rollups first.")

    avg = sum(w.avg_score for w in weeks) / len(weeks)
    trend = trend_of([w.avg_score for w in weeks])
    past_months = [
        {"month": m.month, "avg_score": m.avg_score, "trend": m.trend, "narrative": m.narrative}
        for m in (
            await session.exec(select(MonthlySummary).where(MonthlySummary.month < month).order_by(MonthlySummary.month.desc()).limit(3))
        ).all()
    ][::-1]

    review: agents.MonthlyReviewOutput = await _llm_call(
        agents.run_monthly_review(
            agents.MonthlyDeps(
                month=month,
                weeks=[
                    {"week_start": str(w.week_start), "avg_score": w.avg_score, "trend": w.trend, "wins": w.wins, "misses": w.misses, "carried": w.carried_action_items}
                    for w in weeks
                ],
                past_months=past_months,
                trend=trend,
            ),
            model=await _request_model(session),
            system_prompt=(await load_prompt_overrides(session)).get("monthly"),
            on_usage=make_recorder(session),
        )
    )

    row = await session.get(MonthlySummary, month)
    if row is None:
        row = MonthlySummary(month=month, avg_score=avg, trend=trend)
    row.avg_score = avg
    row.trend = trend
    row.narrative = review.narrative
    session.add(row)
    await index_document(session, f"monthly:{row.month}", "monthly", row.narrative)
    await session.commit()
    await session.refresh(row)
    return row


class DecomposeRequest(BaseModel):
    task_id: str


async def decompose_task(body: DecomposeRequest, session: AsyncSession):
    """Break a task into AI-planned subtasks and persist them under it."""
    task = await session.get(Task, body.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    review: agents.DecompositionOutput = await _llm_call(
        agents.run_task_decomposition(
            task.title,
            task.description,
            utc_now().date(),
            model=await _request_model(session),
            system_prompt=(await load_prompt_overrides(session)).get("decompose"),
            on_usage=make_recorder(session),
        )
    )

    created = []
    for i, sub in enumerate(review.subtasks):
        subtask = Task(
            id=new_id(),
            title=sub.title,
            parent_id=task.id,
            list_id=task.list_id,
            priority=sub.priority,
            estimated_minutes=sub.estimated_minutes,
            order_index=float(i) * 1000.0,
        )
        session.add(subtask)
        created.append(subtask)
    await session.commit()
    for sub in created:
        await session.refresh(sub)
    return {"subtasks": [TaskResponse.model_validate(sub) for sub in created], "advice": review.advice}


class CaptureRequest(BaseModel):
    text: str


async def capture(body: CaptureRequest, session: AsyncSession):
    """Conversational capture: extract tasks from free text, register them and
    append the snippet to today's journal (plan §6.3.4)."""
    review: agents.CaptureOutput = await _llm_call(
        agents.run_capture(
            body.text,
            utc_now().date(),
            model=await _request_model(session, fast=True),
            system_prompt=(await load_prompt_overrides(session)).get("capture"),
            on_usage=make_recorder(session),
        )
    )

    created = []
    for item in review.tasks:
        due_utc: dt.datetime | None = None
        deadline_date = None
        if item.due_time and not item.due_date:
            raise HTTPException(status_code=502, detail="AI returned a time without a date")
        if item.due_date:
            try:
                # local-first assumption: the server runs on the user's machine,
                # so naive AI-returned times are interpreted as system-local and
                # normalized to naive UTC (the storage convention).
                if item.due_time:
                    naive = dt.datetime.fromisoformat(f"{item.due_date}T{item.due_time}")
                    due_utc = naive.astimezone(dt.timezone.utc).replace(tzinfo=None)
                else:
                    deadline_date = dt.date.fromisoformat(item.due_date)
            except ValueError as exc:
                raise HTTPException(status_code=502, detail=f"AI returned an invalid date: {item.due_date}") from exc
        task = Task(id=new_id(), title=item.title, due_date=due_utc, deadline_date=deadline_date, priority=item.priority, tags=item.tags)
        session.add(task)
        created.append(task)

    snippet = review.journal_snippet.strip()
    if snippet:
        today = utc_now().date()
        entry = await session.get(JournalEntry, today)
        block = f"\n\n### Captured\n{snippet}\n"
        if entry is None:
            entry = JournalEntry(date=today, raw_markdown=f"### Captured\n{snippet}\n")
        else:
            entry.raw_markdown += block
            entry.updated_at = utc_now()
        session.add(entry)
        await index_document(session, f"journal:{today.isoformat()}", "journal", entry.raw_markdown)

    await session.commit()
    for task in created:
        await session.refresh(task)
    return {"tasks": [TaskResponse.model_validate(t).model_dump() for t in created], "journal_snippet": snippet}


async def _briefing_data(session: AsyncSession) -> dict:
    """Overdue/due-today work + yesterday's reflection for the briefing agent."""
    now = utc_now()
    today = now.date()

    overdue = (
        await session.exec(
            select(Task)
            .where(or_(Task.due_date < now, Task.deadline_date < today), Task.status.in_(["todo", "in_progress"]))
            .order_by(Task.due_date)
            .limit(20)
        )
    ).all()
    day_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    due_today = (
        await session.exec(
            select(Task)
            .where(or_(and_(Task.due_date >= now.replace(hour=0, minute=0, second=0), Task.due_date <= day_end), Task.deadline_date == today), Task.status.in_(["todo", "in_progress"]))
            .limit(30)
        )
    ).all()

    yesterday = today - dt.timedelta(days=1)
    y_entry = await session.get(JournalEntry, yesterday)
    y_score = await session.get(DailyScore, yesterday)

    def candidate(task: Task) -> dict:
        return {
            "id": task.id,
            "title": task.title,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "deadline_date": task.deadline_date.isoformat() if task.deadline_date else None,
            "status": task.status,
        }

    return {
        "overdue_tasks": [candidate(t) for t in overdue],
        "due_today": [candidate(t) for t in due_today],
        "yesterday_feedback": y_score.feedback if y_score else None,
        "yesterday_journal_excerpt": (y_entry.raw_markdown[-1500:] if y_entry else None),
        "open_tasks_total": (
            await session.exec(select(func.count()).select_from(Task).where(Task.status.in_(["todo", "in_progress"])))
        ).one(),
    }


def _briefing_recommendations(review: agents.BriefingOutput, data: dict) -> list[dict]:
    allowed_ids = {task["id"] for key in ("overdue_tasks", "due_today") for task in data[key]}
    recommendations = []
    for index, text in enumerate(review.top_focus[:3]):
        recommendation = review.recommendations[index] if index < len(review.recommendations) else None
        # Only aligned recommendation text can attach an ID; never match task titles.
        task_id = (
            recommendation.task_id
            if recommendation is not None and recommendation.text == text and recommendation.task_id in allowed_ids
            else None
        )
        recommendations.append({"text": text, "task_id": task_id})
    return recommendations


def _briefing_response(review: agents.BriefingOutput, data: dict) -> dict:
    return {
        "top_focus": review.top_focus[:3],
        "recommendations": _briefing_recommendations(review, data),
        "reasoning": review.reasoning,
        "overdue_count": len(data["overdue_tasks"]),
        "due_today_count": len(data["due_today"]),
    }


async def morning_briefing(session: AsyncSession):
    """Conversational daily planning: recommends the Top 3 focus (plan §6.3.3)."""
    data = await _briefing_data(session)
    review: agents.BriefingOutput = await _llm_call(
        agents.run_briefing(
            data,
            model=await _request_model(session, fast=True),
            system_prompt=(await load_prompt_overrides(session)).get("briefing"),
            on_usage=make_recorder(session),
        )
    )
    return _briefing_response(review, data)


async def morning_briefing_stream(session: AsyncSession):
    """Streams partial BriefingOutput objects. Events: partial (object) → done / error."""
    data = await _briefing_data(session)
    overrides = await load_prompt_overrides(session)

    async def gen():
        try:
            final: agents.BriefingOutput | None = None
            async for partial in agents.stream_briefing(
                data,
                model=await _request_model(session, fast=True),
                system_prompt=overrides.get("briefing"),
                on_usage=make_recorder(session),
            ):
                final = partial
                yield sse("partial", {**partial.model_dump(), "recommendations": _briefing_recommendations(partial, data)})
            if final is None:
                raise RuntimeError("agent returned no output")
            yield sse("done", _briefing_response(final, data))
        except Exception as exc:  # noqa: BLE001 — SSE can't change the HTTP status mid-stream
            yield sse("error", {"message": f"AI request failed: {describe_ai_error(exc)}"})

    return stream_response(gen())


# --- ask my second brain (plan §6.3.5): retrieval + streamed cited answer ---
class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AskRequest(BaseModel):
    question: str = Field(max_length=ASK_MAX_QUESTION)
    history: list[ChatTurn] = []


class AssistRequest(BaseModel):
    action: str  # improve | continue | summarize
    text: str


def _citation_meta(hit) -> dict:
    return {"n": 0, "doc_id": hit.doc_id, "title": hit.title, "date": hit.date, "kind": hit.kind}


async def ask_second_brain(body: AskRequest, session: AsyncSession):
    """Answer a question over journals/rollups: hybrid search → streamed answer
    with [n] citations. Events: sources → partial (cumulative text) → done / error."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    hits = await hybrid_search(session, question, limit=ASK_MAX_SOURCES)
    blocks: list[str] = []
    sources: list[dict] = []
    for i, hit in enumerate(hits, start=1):
        content = await content_for(session, hit.doc_id)
        meta = _citation_meta(hit)
        meta["n"] = i
        sources.append(meta)
        blocks.append(f"[{i}] {hit.title} ({hit.kind}, {hit.date})\n{content[:ASK_SOURCE_CHARS]}")

    deps = agents.AskDeps(
        question=question,
        context="\n\n".join(blocks),
        history=[t.model_dump() for t in body.history],
    )
    overrides = await load_prompt_overrides(session)

    async def gen():
        yield sse("sources", sources)
        try:
            text = ""
            async for chunk in agents.stream_ask(
                deps,
                model=await _request_model(session, fast=True),
                system_prompt=overrides.get("ask"),
                on_usage=make_recorder(session),
            ):
                text = chunk
                yield sse("partial", {"text": text})
            yield sse("done", {"text": text, "sources": sources})
        except Exception as exc:  # noqa: BLE001 — SSE can't change the HTTP status mid-stream
            yield sse("error", {"message": f"AI request failed: {describe_ai_error(exc)}"})

    return stream_response(gen())


async def editor_assist(body: AssistRequest, session: AsyncSession):
    """Streamed journal-text assist (improve/continue/summarize). Events:
    partial (cumulative markdown) → done / error."""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    overrides = await load_prompt_overrides(session)
    deps = agents.AssistDeps(action=body.action, text=body.text[:ASSIST_SOURCE_CHARS])

    async def gen():
        try:
            text = ""
            async for chunk in agents.stream_assist(
                deps,
                model=await _request_model(session, fast=True),
                system_prompt=overrides.get(f"assist_{body.action}"),
                on_usage=make_recorder(session),
            ):
                text = chunk
                yield sse("partial", {"text": text})
            yield sse("done", {"text": text})
        except ValueError as exc:
            yield sse("error", {"message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            yield sse("error", {"message": f"AI request failed: {describe_ai_error(exc)}"})

    return stream_response(gen())
