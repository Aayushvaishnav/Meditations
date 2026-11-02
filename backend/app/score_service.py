"""Resolve scoring preferences for live telemetry and review snapshots."""

from __future__ import annotations

import math

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AppSetting
from app.scoring import (
    DEFAULT_TARGET_DEEP_WORK_HOURS,
    DailyMetrics,
    ScoreBreakdown,
    compute_daily_score,
)

TARGET_HOURS_KEY = "target_deep_work_hours"


async def get_effective_target_hours(session: AsyncSession) -> float:
    row = await session.get(AppSetting, TARGET_HOURS_KEY)
    if row is not None:
        try:
            target = float(row.value)
        except ValueError:
            pass
        else:
            if math.isfinite(target) and 0 < target <= 16:
                return target
    return DEFAULT_TARGET_DEEP_WORK_HOURS


async def score_daily_metrics(
    session: AsyncSession,
    metrics: DailyMetrics,
    *,
    target_hours: float | None = None,
    llm_nudge: float = 0.0,
) -> ScoreBreakdown:
    target = target_hours if target_hours is not None else await get_effective_target_hours(session)
    return compute_daily_score(metrics, target_hours=target, llm_nudge=llm_nudge)
