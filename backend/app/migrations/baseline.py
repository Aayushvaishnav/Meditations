"""Frozen pre-recurrence-identity DDL; never regenerate from live models."""

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS ai_usage (
    id VARCHAR NOT NULL,
    ts DATETIME NOT NULL,
    agent VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE INDEX IF NOT EXISTS ix_ai_usage_agent ON ai_usage (agent)""",
    """CREATE INDEX IF NOT EXISTS ix_ai_usage_ts ON ai_usage (ts)""",
    """CREATE TABLE IF NOT EXISTS app_settings (
    "key" VARCHAR NOT NULL,
    value VARCHAR NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY ("key")
)""",
    """CREATE TABLE IF NOT EXISTS habits (
    id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    target_frequency VARCHAR NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE INDEX IF NOT EXISTS ix_habits_name ON habits (name)""",
    """CREATE TABLE IF NOT EXISTS journal_entries (
    date DATE NOT NULL,
    raw_markdown VARCHAR NOT NULL,
    mood INTEGER,
    energy INTEGER,
    hours_deep_work FLOAT NOT NULL,
    tasks_planned INTEGER NOT NULL,
    tasks_done INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (date)
)""",
    """CREATE TABLE IF NOT EXISTS lists (
    id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    color VARCHAR NOT NULL,
    icon VARCHAR,
    is_favorite BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE INDEX IF NOT EXISTS ix_lists_name ON lists (name)""",
    """CREATE TABLE IF NOT EXISTS monthly_summaries (
    month VARCHAR NOT NULL,
    avg_score FLOAT NOT NULL,
    trend VARCHAR NOT NULL,
    narrative VARCHAR NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (month)
)""",
    """CREATE TABLE IF NOT EXISTS weekly_summaries (
    week_start DATE NOT NULL,
    avg_score FLOAT NOT NULL,
    trend VARCHAR NOT NULL,
    wins VARCHAR NOT NULL,
    misses VARCHAR NOT NULL,
    carried_action_items VARCHAR,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (week_start)
)""",
    """CREATE TABLE IF NOT EXISTS daily_scores (
    date DATE NOT NULL,
    deterministic_score FLOAT NOT NULL,
    llm_nudge FLOAT NOT NULL,
    final_score FLOAT NOT NULL,
    rubric_breakdown_json VARCHAR NOT NULL,
    feedback VARCHAR NOT NULL,
    insight VARCHAR NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (date),
    FOREIGN KEY(date) REFERENCES journal_entries (date) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS habit_logs (
    id VARCHAR NOT NULL,
    habit_id VARCHAR NOT NULL,
    date DATE NOT NULL,
    completed BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_habit_log_day UNIQUE (habit_id, date),
    FOREIGN KEY(habit_id) REFERENCES habits (id) ON DELETE CASCADE
)""",
    """CREATE INDEX IF NOT EXISTS ix_habit_logs_habit_id ON habit_logs (habit_id)""",
    """CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR NOT NULL,
    list_id VARCHAR,
    parent_id VARCHAR,
    title VARCHAR NOT NULL,
    description VARCHAR,
    priority INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    due_date DATETIME,
    estimated_minutes INTEGER,
    actual_minutes INTEGER NOT NULL,
    recurrence_rule VARCHAR,
    tags JSON NOT NULL,
    order_index FLOAT NOT NULL,
    completed_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(list_id) REFERENCES lists (id) ON DELETE SET NULL,
    FOREIGN KEY(parent_id) REFERENCES tasks (id) ON DELETE CASCADE
)""",
    """CREATE INDEX IF NOT EXISTS ix_tasks_completed_at ON tasks (completed_at)""",
    """CREATE INDEX IF NOT EXISTS ix_tasks_due_date ON tasks (due_date)""",
    """CREATE INDEX IF NOT EXISTS ix_tasks_list_id ON tasks (list_id)""",
    """CREATE INDEX IF NOT EXISTS ix_tasks_parent_id ON tasks (parent_id)""",
    """CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status)""",
    """CREATE TABLE IF NOT EXISTS focus_sessions (
    id VARCHAR NOT NULL,
    task_id VARCHAR,
    duration_minutes INTEGER NOT NULL,
    session_type VARCHAR NOT NULL,
    notes VARCHAR,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE SET NULL
)""",
    """CREATE INDEX IF NOT EXISTS ix_focus_sessions_created_at ON focus_sessions (created_at)""",
    """CREATE INDEX IF NOT EXISTS ix_focus_sessions_task_id ON focus_sessions (task_id)""",
)
