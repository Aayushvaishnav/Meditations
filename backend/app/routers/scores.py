from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.schemas import DailyScoreResponse, saved_review_action
from app.models import DailyScore
from app.routers.deps import SessionDep
from app.scoring import (
    ScoreBreakdown,
)
from app.score_service import score_daily_metrics
from app.telemetry import collect_daily_metrics

router = APIRouter(prefix="/api/scores", tags=["scores"])


def _response(
    day: date,
    breakdown: ScoreBreakdown,
    persisted: bool,
    feedback: str | None,
    insight: str | None,
    saved_review_score: float | None = None,
    suggested_action_for_tomorrow: str = "",
) -> DailyScoreResponse:
    return DailyScoreResponse(
        date=day,
        task_score=breakdown.task_score,
        focus_score=breakdown.focus_score,
        habit_score=breakdown.habit_score,
        weighted_score=breakdown.weighted_score,
        llm_nudge=breakdown.llm_nudge,
        final_score=breakdown.final_score,
        target_deep_work_hours=breakdown.target_deep_work_hours,
        metrics=breakdown.metrics,
        persisted=persisted,
        saved_review_score=saved_review_score,
        feedback=feedback,
        insight=insight,
        suggested_action_for_tomorrow=suggested_action_for_tomorrow,
    )


@router.get("/daily/{day}", response_model=DailyScoreResponse)
async def get_daily_score(
    day: date,
    session: SessionDep,
    target_hours: float | None = Query(default=None, gt=0),
):
    """Live deterministic score; uses the stored LLM nudge if a rollup exists.

    Persistence of daily_scores rows happens with the daily agent (Phase 4).
    """
    metrics = await collect_daily_metrics(session, day)

    stored = await session.get(DailyScore, day)
    if stored is not None:
        breakdown = await score_daily_metrics(
            session, metrics, target_hours=target_hours, llm_nudge=stored.llm_nudge
        )
        return _response(
            day, breakdown, persisted=True, feedback=stored.feedback,
            insight=stored.insight, saved_review_score=stored.final_score,
            suggested_action_for_tomorrow=saved_review_action(stored.rubric_breakdown_json),
        )

    breakdown = await score_daily_metrics(session, metrics, target_hours=target_hours)
    return _response(day, breakdown, persisted=False, feedback=None, insight=None)
