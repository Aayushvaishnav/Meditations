from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, Index, Integer, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.util import new_id, utc_now


class TaskList(SQLModel, table=True):
    __tablename__ = "lists"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    color: str = Field(default="#64748b")
    icon: str | None = None
    is_favorite: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class TaskFields(SQLModel):
    id: str = Field(default_factory=new_id, primary_key=True)
    list_id: str | None = Field(default=None, foreign_key="lists.id", ondelete="SET NULL", index=True)
    parent_id: str | None = Field(default=None, foreign_key="tasks.id", ondelete="CASCADE", index=True)
    title: str
    description: str | None = None
    priority: int = 0  # 0 none, 1 low (!3), 2 med (!2), 3 high (!1)
    status: str = Field(default="todo", index=True)  # todo|in_progress|completed|canceled
    due_date: datetime | None = Field(default=None, index=True)
    deadline_date: Date | None = Field(default=None, index=True)
    estimated_minutes: int | None = None
    actual_minutes: int = 0
    recurrence_rule: str | None = None
    recurrence_series_id: str | None = None
    recurrence_occurrence: int | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    order_index: float = 0.0
    completed_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Task(TaskFields, table=True):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("uq_task_recurrence_occurrence", "recurrence_series_id", "recurrence_occurrence", unique=True),
        CheckConstraint("due_date IS NULL OR deadline_date IS NULL", name="ck_task_deadline_exclusive"),
    )


class TimeBlock(SQLModel, table=True):
    __tablename__ = "time_blocks"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'timed' AND timezone IS NOT NULL "
            "AND start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at "
            "AND start_date IS NULL AND end_date IS NULL) OR "
            "(kind = 'all_day' AND timezone IS NULL "
            "AND start_at IS NULL AND end_at IS NULL "
            "AND start_date IS NOT NULL AND end_date IS NOT NULL AND end_date > start_date)",
            name="ck_time_block_shape",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", ondelete="CASCADE", index=True)
    kind: str = Field(default="timed")
    # Preserve explicit NULL for all-day blocks
    timezone: str | None = Field(
        default="UTC", sa_column=Column(String().evaluates_none(), nullable=True),
    )
    start_at: datetime | None = Field(default=None, index=True)
    end_at: datetime | None = Field(default=None, index=True)
    start_date: Date | None = Field(default=None, index=True)
    end_date: Date | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class FocusSession(SQLModel, table=True):
    __tablename__ = "focus_sessions"

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str | None = Field(default=None, foreign_key="tasks.id", ondelete="SET NULL", index=True)
    duration_minutes: int
    session_type: str = Field(default="pomodoro")  # pomodoro | stopwatch
    notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)


class Habit(SQLModel, table=True):
    __tablename__ = "habits"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    target_frequency: str = Field(default="daily")  # daily | weekdays | 3x_week | ...
    created_at: datetime = Field(default_factory=utc_now)


class HabitLog(SQLModel, table=True):
    __tablename__ = "habit_logs"
    __table_args__ = (UniqueConstraint("habit_id", "date", name="uq_habit_log_day"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    habit_id: str = Field(foreign_key="habits.id", ondelete="CASCADE", index=True)
    date: Date
    completed: bool = True


class JournalEntry(SQLModel, table=True):
    __tablename__ = "journal_entries"

    date: Date = Field(primary_key=True)
    raw_markdown: str
    mood: int | None = None  # 1..5, validated at the API layer
    energy: int | None = None
    hours_deep_work: float = 0.0
    tasks_planned: int = 0
    tasks_done: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DailyScore(SQLModel, table=True):
    __tablename__ = "daily_scores"

    date: Date = Field(primary_key=True, foreign_key="journal_entries.date", ondelete="CASCADE")
    deterministic_score: float
    llm_nudge: float = 0.0  # bounded [-10, +10]
    final_score: float
    rubric_breakdown_json: str
    feedback: str
    insight: str
    created_at: datetime = Field(default_factory=utc_now)


class WeeklySummary(SQLModel, table=True):
    __tablename__ = "weekly_summaries"

    week_start: Date = Field(primary_key=True)
    avg_score: float
    trend: str  # rising | declining | stable
    wins: str
    misses: str
    carried_action_items: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class MonthlySummary(SQLModel, table=True):
    __tablename__ = "monthly_summaries"

    month: str = Field(primary_key=True)  # 'YYYY-MM'
    avg_score: float
    trend: str
    narrative: str
    created_at: datetime = Field(default_factory=utc_now)


class AppSetting(SQLModel, table=True):
    """Key/value overrides for env config (AI provider, base_url, api_key, ...)."""

    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=utc_now)


class AiUsage(SQLModel, table=True):
    """Token/duration telemetry for every LLM call (observability only)."""

    __tablename__ = "ai_usage"

    id: str = Field(default_factory=new_id, primary_key=True)
    ts: datetime = Field(default_factory=utc_now, index=True)
    agent: str = Field(index=True)  # daily | weekly | monthly | decompose | capture | briefing | ask | assist | test
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0


class SearchVectorState(SQLModel, table=True):
    __tablename__ = "search_vector_state"

    doc_id: str = Field(primary_key=True)
    state: str  # pending|ready; updated in the source/FTS transaction


class ReviewJob(SQLModel, table=True):
    __tablename__ = "review_jobs"

    kind: str = Field(primary_key=True)  # daily|weekly|monthly
    period: str = Field(primary_key=True)  # UTC day, Monday, or YYYY-MM
    state: str  # pending|completed|skipped


class CalendarConnection(SQLModel, table=True):
    __tablename__ = "calendar_connections"
    __table_args__ = (
        CheckConstraint("state IN ('disconnected', 'connected', 'authentication_required')",
                        name="ck_calendar_connection_state"),
        CheckConstraint("credential_state IN ('absent', 'present', 'removal_pending')",
                        name="ck_calendar_connection_credential_state"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    server_url: str
    calendar_url: str
    state: str = "disconnected"
    enabled: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    credential_state: str = Field(
        default="absent", sa_column=Column(String, nullable=False, server_default="absent")
    )


class CalendarLink(SQLModel, table=True):
    __tablename__ = "calendar_links"
    __table_args__ = (
        UniqueConstraint("local_block_id", name="uq_calendar_link_local_block"),
        UniqueConstraint("connection_id", "resource_url", name="uq_calendar_link_resource"),
        CheckConstraint("state IN ('pending', 'syncing', 'synced', 'conflict', 'error', 'detached')",
                        name="ck_calendar_link_state"),
        CheckConstraint("desired_action IN ('upsert', 'delete')", name="ck_calendar_link_action"),
        CheckConstraint("local_revision >= 1 AND acknowledged_revision >= 0 "
                        "AND acknowledged_revision <= local_revision", name="ck_calendar_link_revisions"),
        CheckConstraint("(payload_state = 'unprepared' AND payload IS NULL) OR "
                        "(payload_state = 'prepared' AND payload IS NOT NULL)", name="ck_calendar_link_payload"),
        CheckConstraint("(error_state = 'none' AND last_error IS NULL) OR "
                        "(error_state = 'present' AND last_error IS NOT NULL)", name="ck_calendar_link_error"),
        CheckConstraint("acknowledged_action IN ('unknown', 'upsert', 'delete')",
                        name="ck_calendar_link_acknowledged_action"),
        CheckConstraint("block_id IS NULL OR block_id = local_block_id", name="ck_calendar_link_block_identity"),
        CheckConstraint("selection_state IN ('opted_in', 'opted_out', 'detached')",
                        name="ck_calendar_link_selection_state"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    connection_id: str = Field(foreign_key="calendar_connections.id", ondelete="RESTRICT", index=True)
    block_id: str | None = Field(default=None, foreign_key="time_blocks.id", ondelete="SET NULL", index=True)
    # Independent identity survives source deletion; absence of a link means unlinked
    local_block_id: str
    uid: str
    resource_url: str
    etag: str | None = None
    state: str = "pending"
    local_revision: int = 1
    acknowledged_revision: int = 0
    desired_action: str = "upsert"
    payload_state: str = "unprepared"
    payload: str | None = None
    error_state: str = "none"
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    acknowledged_action: str = Field(
        default="unknown", sa_column=Column(String, nullable=False, server_default="unknown")
    )

    last_synced_at: datetime | None = None
    selection_state: str = Field(default="opted_in", sa_column=Column(
        String, nullable=False, server_default="opted_in"
    ))


class CalendarDispatch(SQLModel, table=True):
    __tablename__ = "calendar_dispatches"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_calendar_dispatch_revision"),
        CheckConstraint("action IN ('upsert', 'delete')", name="ck_calendar_dispatch_action"),
        CheckConstraint("(action = 'upsert' AND payload IS NOT NULL) OR "
                        "(action = 'delete' AND payload IS NULL)", name="ck_calendar_dispatch_payload"),
        CheckConstraint("attempted IN (0, 1)", name="ck_calendar_dispatch_attempted"),
    )

    link_id: str = Field(primary_key=True, foreign_key="calendar_links.id", ondelete="CASCADE")
    revision: int
    action: str
    resource_url: str
    uid: str
    expected_etag: str | None = None
    payload: str | None = None
    attempted: bool = False


class CalendarImportSource(SQLModel, table=True):
    __tablename__ = "calendar_import_sources"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CalendarImportSnapshot(SQLModel, table=True):
    __tablename__ = "calendar_import_snapshots"

    id: str = Field(default_factory=new_id, primary_key=True)
    source_id: str = Field(foreign_key="calendar_import_sources.id", ondelete="CASCADE", index=True)
    content: str
    context: str
    imported_at: datetime = Field(default_factory=utc_now)


class CalendarImportEvent(SQLModel, table=True):
    __tablename__ = "calendar_import_events"
    __table_args__ = (UniqueConstraint("source_id", "identity", name="uq_calendar_import_identity"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    source_id: str = Field(foreign_key="calendar_import_sources.id", ondelete="CASCADE", index=True)
    snapshot_id: str = Field(foreign_key="calendar_import_snapshots.id", ondelete="CASCADE")
    identity: str
    uid: str
    summary: str
    recurrence_kind: str
    recurrence_id: str
    time_zone: str | None = None
    recurrence_time_zone: str | None = None
    start_kind: str
    status: str
    has_recurrence: bool
    start_value: str | None = None
    end_value: str | None = None
    component: str
    component_index: int


class CalendarInboundState(SQLModel, table=True):
    """Per-connection inbound reconciliation cache; token is None in ETag-listing mode."""
    __tablename__ = "calendar_inbound_state"
    __table_args__ = (
        CheckConstraint("capability IN ('unknown', 'sync_token', 'listing')", name="ck_calendar_inbound_capability"),
        CheckConstraint("revision >= 0", name="ck_calendar_inbound_revision"),
        CheckConstraint("(capability = 'sync_token' AND sync_token IS NOT NULL) OR capability != 'sync_token'",
                        name="ck_calendar_inbound_token"),
        UniqueConstraint("connection_id", name="uq_calendar_inbound_connection"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    connection_id: str = Field(foreign_key="calendar_connections.id", ondelete="CASCADE", index=True)
    capability: str = "unknown"
    revision: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    sync_token: str | None = None
    last_synced_at: datetime | None = None
    error_state: str = Field(default="none", sa_column=Column(String, nullable=False, server_default="none"))
    last_error: str | None = None


class CalendarInboundEvent(SQLModel, table=True):
    """Cached copy of one remote VEVENT resource; the server stays authoritative."""
    __tablename__ = "calendar_inbound_events"
    __table_args__ = (
        UniqueConstraint("connection_id", "resource_url", name="uq_calendar_inbound_resource"),
        CheckConstraint("component_state IN ('stored', 'unparsable')", name="ck_calendar_inbound_component"),
        CheckConstraint("(component_state = 'stored' AND identity IS NOT NULL AND uid IS NOT NULL "
                        "AND summary IS NOT NULL AND component IS NOT NULL AND component_index IS NOT NULL) OR "
                        "(component_state = 'unparsable' AND identity IS NULL AND uid IS NULL AND summary IS NULL "
                        "AND component IS NULL AND component_index IS NULL)",
                        name="ck_calendar_inbound_content"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    connection_id: str = Field(foreign_key="calendar_connections.id", ondelete="CASCADE", index=True)
    resource_url: str
    etag: str
    content: str  # raw resource text; retained even when unparsable
    identity: str | None = None
    uid: str | None = None
    summary: str | None = None
    component: str | None = None
    component_index: int | None = None
    component_state: str = "stored"
    fetched_at: datetime = Field(default_factory=utc_now)


class WebhookEndpoint(SQLModel, table=True):
    __tablename__ = "webhook_endpoints"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    url: str
    enabled: bool = True
    events: str
    scope: str
    include_titles: bool = False


class WebhookVersion(SQLModel, table=True):
    __tablename__ = "webhook_versions"
    entity_id: str = Field(primary_key=True)
    version: int


class WebhookDelivery(SQLModel, table=True):
    __tablename__ = "webhook_deliveries"
    id: str = Field(default_factory=new_id, primary_key=True)
    endpoint_id: str = Field(foreign_key="webhook_endpoints.id", ondelete="CASCADE", index=True)
    event_id: str
    event_type: str
    entity_id: str
    entity_version: int
    payload: str
    state: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    next_attempt_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)
