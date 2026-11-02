"""Portable, allowlisted user data export; never copies database files."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app import models

FORMAT = "journal-data-export"
# Explicit columns are the format contract; new database fields are opt-in.
TABLES = (
    (models.TaskList, "id name color icon is_favorite created_at"),
    (
        models.Task,
        "id list_id parent_id title description priority status due_date estimated_minutes actual_minutes recurrence_rule recurrence_series_id recurrence_occurrence tags order_index completed_at created_at updated_at",
    ),
    (models.FocusSession, "id task_id duration_minutes session_type notes created_at"),
    (models.Habit, "id name target_frequency created_at"),
    (models.HabitLog, "id habit_id date completed"),
    (
        models.JournalEntry,
        "date raw_markdown mood energy hours_deep_work tasks_planned tasks_done created_at updated_at",
    ),
    (
        models.DailyScore,
        "date deterministic_score llm_nudge final_score rubric_breakdown_json feedback insight created_at",
    ),
    (
        models.WeeklySummary,
        "week_start avg_score trend wins misses carried_action_items created_at",
    ),
    (models.MonthlySummary, "month avg_score trend narrative created_at"),
)

README = """# Journal data export, version 1

## Files and encoding

- manifest.json: format is "journal-data-export", version is 1, exported_at is
  the UTC time the archive was assembled, and counts maps each collection to its
  record count. The format version is independent of the SQLite schema version.
- data.json: collections listed below, including empty arrays when no records exist.
- journals/YYYY-MM-DD.md: exact saved UTF-8 Markdown, including any existing
  frontmatter and original line endings. No metadata is prepended. Rating-only
  entries have empty files; days without entries have no file or metadata row.
- README.md: this guide.

All text uses UTF-8. JSON preserves numbers, booleans, arrays, strings and nulls.
A null represents a genuinely missing optional value. Collections are ordered by
primary key, without reordering the stored order_index values.

## Dates, times, and identity

IDs are existing opaque strings, not regenerated identifiers. list_id, parent_id,
task_id and habit_id retain references to those IDs. Recurrence series IDs remain
unchanged and occurrence numbers are zero-based. Journal dates, habit-log dates,
and week_start are YYYY-MM-DD date labels; do not convert them between timezones.
week_start identifies Monday and month uses YYYY-MM.

Timestamps are ISO 8601 UTC with a trailing Z, preserving stored fractional seconds.
Naive database datetimes are interpreted as UTC. No timezone or all-day intent is
inferred. Task due_date preserves the existing scheduling value, including legacy
synthetic 09:00 local values; it does not create a separate deadline or work block.
Focus created_at is the recorded session timestamp, not a reconstructed start time.

## Collections and fields

Every record includes the following fields; missing collections are not omitted.

- lists: id, name, color, icon, is_favorite, created_at.
- tasks: id, list_id, parent_id, title, description, priority, status, due_date,
  estimated_minutes, actual_minutes, recurrence_rule, recurrence_series_id,
  recurrence_occurrence, tags, order_index, completed_at, created_at, updated_at.
  Priority is 0 (none), 1 (low), 2 (medium), or 3 (high). Status is todo,
  in_progress, completed, or canceled. tags is a JSON array. recurrence_rule is
  preserved as stored; exporting does not expand recurrence or create occurrences.
- focus_sessions: id, task_id, duration_minutes, session_type, notes, created_at.
- habits: id, name, target_frequency, created_at.
- habit_logs: id, habit_id, date, completed.
- journal_entries: date, mood, energy, hours_deep_work, tasks_planned, tasks_done,
  created_at, updated_at, markdown_file. markdown_file points to the relative
  journals/ file instead of duplicating raw_markdown. Mood and energy retain
  their 1-to-5 ratings or null when unset.
- daily_scores: date, deterministic_score, llm_nudge, final_score,
  rubric_breakdown_json, feedback, insight, created_at. date references the journal
  entry. rubric_breakdown_json is the original JSON string, not a nested object.
- weekly_summaries: week_start, avg_score, trend, wins, misses,
  carried_action_items, created_at.
- monthly_summaries: month, avg_score, trend, narrative, created_at.

Scores, journal activity metrics, and reviews are saved records, not recalculated
values. A journal entry without a saved daily review has no daily_scores record.

## Snapshot and privacy

All related records are read from one SQLite transaction snapshot. Only committed
state is included; finish saving editor changes first. Later writes are excluded.
Application settings (including provider credentials and prompt overrides), AI
usage, review jobs, search indexes/state, and database snapshots are excluded.
User-authored text is preserved without redaction and may contain sensitive
information. This ZIP is unencrypted; review it before sharing.

This is a portable export for inspection and other tools. It is not a database
restore backup, and Journal does not currently import this ZIP. Use the full
SQLite backup and offline restore workflow for application recovery.
"""


def _json_value(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode(
        "utf-8"
    )


async def create_export(engine: AsyncEngine, destination: Path) -> None:
    """Write one ZIP from a single explicit SQLite read snapshot."""
    data = {}
    markdown = {}
    async with engine.connect() as connection:
        # SQLite legacy transaction mode does not BEGIN for SELECT.
        await connection.exec_driver_sql("BEGIN")
        try:
            for model, fields in TABLES:
                names = fields.split()
                table = model.__table__
                result = await connection.execute(
                    select(*(table.c[name] for name in names)).order_by(
                        *table.primary_key.columns
                    )
                )
                records = []
                for row in result.mappings():
                    record = {name: _json_value(row[name]) for name in names}
                    if model is models.JournalEntry:
                        path = f"journals/{record['date']}.md"
                        markdown[path] = record.pop("raw_markdown")
                        record["markdown_file"] = path
                    records.append(record)
                data[table.name] = records
        finally:
            await connection.rollback()
    manifest = {
        "format": FORMAT,
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "counts": {name: len(records) for name, records in data.items()},
    }
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("README.md", README.encode("utf-8"))
        archive.writestr("manifest.json", _json_bytes(manifest))
        archive.writestr("data.json", _json_bytes(data))
        for path, content in markdown.items():
            archive.writestr(path, content.encode("utf-8"))
