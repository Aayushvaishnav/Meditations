# Journal Backend

Local-first FastAPI + SQLite backend for the task/journal/AI life-OS (see `../plan.md`).

## Setup

```bash
cd backend
uv sync                 # creates .venv from pyproject.toml + uv.lock
cp .env.example .env    # optional; defaults target local Ollama
```

## Run

```bash
uv run uvicorn app.main:app --reload
# API docs: http://127.0.0.1:8000/docs
```

## Test

```bash
uv run pytest
```

## Conventions

- **All datetimes are UTC, naive** (no `tzinfo` in JSON). The client converts to local time for display. Server normalizes any incoming aware datetime to UTC and strips the offset (the SQLite dialect stores offsets but drops them on read, so aware round-trips would be asymmetric).
- **IDs** are 32-char UUID4 hex strings.
- **`tasks.actual_minutes`** is maintained by the focus-session routes (added on create, subtracted on delete) and can also be set manually via task PATCH.
- **Subtasks are tasks** with `parent_id`; deletion cascades via SQLite FKs (`PRAGMA foreign_keys=ON` per connection, `journal_mode=WAL` on the file DB).

## Task-linked time blocks

Timed and all-day work plans use a separate API from task deadlines and recorded
focus. All intervals use an inclusive start and exclusive end. Create a task first,
then POST one of these shapes to `/api/time-blocks`:

```json
{"task_id":"<task-id>","kind":"timed","start_at":"2026-11-02T09:00:00Z","end_at":"2026-11-02T10:30:00Z","timezone":"Asia/Kolkata"}
```

Timed inputs are absolute instants: naive values mean UTC, and aware values are
converted to UTC. The separately stored IANA timezone identifies the intended
local display zone instead of changing the meaning of `start_at`/`end_at`.
Omitting `kind` retains the earlier timed contract; `timezone` defaults to `UTC`.

For local clock scheduling, use `kind:local` and local endpoints:

```json
{"task_id":"<task-id>","kind":"local","start_local":"2026-11-02T09:00:00","end_local":"2026-11-02T10:30:00","timezone":"America/New_York"}
```

A local input resolves through its required IANA zone and returns a canonical
`timed` block with naive-UTC instants and the zone name. Nonexistent local times
are rejected instead of moved forward. Repeated times require an explicit matching
offset, for example `2026-11-01T01:30:00-04:00` or `-05:00` in New York. An incorrect
offset is rejected even outside DST overlaps. Numeric epochs and date-only datetime
inputs are refused. The locked PSF `tzdata` fallback is bundled for systems without
host timezone data. Names are validated against the bundled IANA registry, retaining
supported aliases while rejecting host-only `posix/`, `right/`, and `posixrules` keys.

All-day blocks keep date labels without conversion or midnight timestamps:

```json
{"task_id":"<task-id>","kind":"all_day","start_date":"2026-11-02","end_date":"2026-11-03"}
```

This example covers November 2 only. Dates require `YYYY-MM-DD`; timezone and
instant fields are inapplicable. Responses contain `kind`, all interval fields,
and metadata; inapplicable fields are null. Mixed shape properties, even nulls,
are rejected on writes.

POST returns 201 with a stable ID. GET `/{id}` reads it; PUT `/{id}` replaces the
entire input shape and can switch kinds while preserving ID/creation time. DELETE
removes it (204). Missing blocks or tasks return 404; malformed shapes, zones,
nonpositive intervals, DST ambiguity/gaps, and range overflow return 422.

Collection filters are optional: `task_id`, `kind=timed|all_day`, `start`/`end`
for timed instant overlap, or `start_date`/`end_date` for all-day date overlap.
Endpoints exactly touching a query boundary are excluded. A single bound is
valid; paired bounds must increase. Combining date and instant ranges or a range
incompatible with `kind` returns 422. Instant queries exclude all-day blocks
instead of inventing a timezone for them. Without ranges both kinds appear,
ordered by kind (all-day first), start date/instant, then ID.

Multiple and overlapping blocks are allowed. Block changes leave deadlines,
status, focus history, and scores unchanged. Task completion/cancellation preserves
blocks; recurring task successors receive none. Deleting a task deletes its blocks,
including blocks owned by deleted subtasks.

SQLite backup/restore and portable export v1 preserve block IDs, task references,
IANA metadata, precise UTC timestamps, and all-day date labels. The export's
`time_blocks` collection uses canonical timed/all-day fields. Consumers should
ignore unknown collections and fields. Migration v7 preserves all existing timed
values and marks their zone `UTC`; it infers neither original local zones nor
all-day intent.

The UI calendar still edits deadlines; work-block UI and calendar export remain
later backlog items. Future calendar recurrence must keep the anchor's local clock
in its stored IANA zone and resolve each date separately, with explicit resolution
of gaps/folds, instead of adding fixed UTC days. Recurrence expansion and occurrence
exceptions remain SCHED-04; existing completion-triggered task recurrence is unchanged.

## Scoring (plan §3.4)

Deterministic, computed from live telemetry (`/api/scores/daily/{date}`):

```
score = 0.40*task + 0.35*focus + 0.15*habit + clamp(llm_nudge, ±10)
```

- `task = min(100, done/max(planned,1)*100)` — planned = due that day (incl. overdue, still open) or undated-but-completed that day; canceled never counts.
- `focus = min(100, hours/target*100)` — uses the target configured in Settings (4h by default); `?target_hours=` overrides only that live request.
- `habit = done/scheduled*100` — scheduled = `daily` habits existing by that day.

A component the user has not opted into is **neutral (100), not punitive**: no habits configured → habit 100; `target_hours=0` → focus 100. Weights sum to 0.90; the remaining 10 points come from the (Phase 4) LLM nudge. The endpoint is live-only for now — `daily_scores` persistence happens with the daily agent.

### Focus targets and saved reviews

Changing the focus target in Settings refreshes live day scores, including past
days. Saved AI reviews retain the metrics and target used when they ran. The
journal card displays the current live score and saved review score separately.
Run the review again to replace its saved score using current activity and target.
Weekly reviews use saved daily scores when available; other days use the current
target. Existing weekly and monthly reviews change only when re-run.

The live score API returns `score_basis: "live"`; daily review responses return
`score_basis: "review_snapshot"`. Both expose `saved_review_score` when a review
exists. `persisted` means a saved review exists, even when its score differs from
the recalculated live value.

## AI provider config (plan §3.2)

`AISettings` reads `AI_PROVIDER`, `AI_MODEL_NAME`, `AI_BASE_URL`, `AI_API_KEY` from the env/.env. Fields can be overridden at runtime (frontend settings drawer) via `app_settings` rows through the API:

- `GET /api/settings/ai` — effective config; returns `api_key_set`, never the key itself
- `PUT /api/settings/ai` — set overrides (`""` clears one back to the env default)
- `DELETE /api/settings/ai` — drop all overrides

`app.ai_factory.create_agent_model()` builds a pydantic-ai model for any OpenAI-compatible endpoint or Anthropic. Note: the plan's §7.1 snippet targets pydantic-ai 0.x; the installed v2 API is used instead (`OpenAIChatModel` + provider objects, `output_type=` on agents).

## API surface (Phase 1)

- `GET /api/health`
- `/api/lists` — CRUD
- `/api/tasks` — CRUD + filters (`list_id`, `parent_id`, `top_level`, `status`, `tag`, `due_before/after`, `overdue`), `GET /{id}/children`, `POST /reorder`
- `/api/time-blocks` — task-linked timed blocks: list/create, `GET/PUT/DELETE /{id}`; list filters `task_id`, `start`, `end`
- `/api/focus` — `sessions` (list/create/delete, filters `task_id`, `on_date`), `summary?on_date=`
- `/api/habits` — CRUD, `GET /logs` (by day or range), `PUT /{id}/logs` upsert
- `/api/scores/daily/{date}`
- `/api/settings/ai`

## API surface (Phase 4 — AI agents)

All agent endpoints call the configured provider (env or `PUT /api/settings/ai`).
Provider failures surface as `502` with the underlying error; everything else is
deterministic.

- `POST /api/agents/rollup/daily[?day=YYYY-MM-DD]` — daily review agent; persists
  `daily_scores` (deterministic score + ±10 LLM nudge with rationale, feedback,
  insight). Bounded inputs: today's raw entry + past 6 days (truncated) + latest
  weekly/monthly summaries. Requires a journal entry for the day.
- `POST /api/agents/rollup/weekly[?week_start=YYYY-MM-DD]` — ISO week rollup from
  daily scores/metadata (raw journals never read again); stores `weekly_summaries`.
  Defaults to the current UTC week; scheduled runs pass an explicit closed week.
- `POST /api/agents/rollup/monthly[?month=YYYY-MM|previous]` — month narrative from
  that month's weekly rollups; stores `monthly_summaries`. Defaults to the current
  month, or the previous one on the 1st.
- `POST /api/agents/decompose` `{task_id}` — persists AI-planned subtasks under a task.
- `POST /api/agents/capture` `{text}` — extracts tasks with due dates from free text
  and appends a snippet to today's journal.
- `POST /api/agents/briefing` — Top-3 focus recommendation from overdue/today tasks
  and yesterday's reflection.

Tests never touch the network: agent runners live in `app/agents.py` and are
monkeypatched in `tests/test_agents.py`; `pydantic_ai.models.test.TestModel` proves
the prompt/output-schema wiring.

## Search (Phase 5)

`GET /api/search?q=…` fuses two indexes with reciprocal-rank fusion:

- **FTS5** (`fts_entries`) — always available; indexes journal entries, weekly and
  monthly rollups as they are written.
- **sqlite-vec** (`vec_entries`) — local `bge-small-en-v1.5` embeddings via
  fastembed; strictly optional. If the extension or the model is unavailable the
  app silently degrades to keyword search. Vectors only count when
  `distance <= 1.0` (cosine ≥ 0.5) so small indexes never fabricate matches.

Journal saves/deletes, captured journal snippets, and weekly/monthly rollups
update their source data and keyword index in the same transaction. A storage
failure rolls back the save. An unavailable embedding model still allows keyword
search; missing vectors retry at startup or through `POST /api/search/reindex`.
Startup also repairs stale keyword content and removes deleted-document results.
Reindex replaces the indexes from current source data, removing orphan records.
Both operations commit their index changes atomically.

`GET /api/search/status` reports whether the vector extension is available. The
reindex response reports `semantic: true` when at least one current vector was
built. The embedding model (~90 MB) downloads on first use into
`~/.cache/fastembed`.

## Scheduled rollups

The packaged desktop backend runs a database-local review worker while the app
is open. It uses the same database and configured AI provider as interactive
reviews, independent of the sidecar's loopback port. Standalone/development
backends default to scheduling off. To opt in:

```bash
JOURNAL_SCHEDULED_REVIEWS=true uv run uvicorn app.main:app
```

Set `JOURNAL_SCHEDULED_REVIEWS=false` to disable scheduling in the packaged app.
Run one backend process per database (one uvicorn worker). The worker checks at
startup and every minute, catches up missed periods, and is cancelled before
the database closes. Closing the desktop app pauses scheduling.

Periods use **UTC**, matching journal telemetry, instead of the old host-local
systemd clock. Daily reviews cover journal days before today. Weekly reviews
cover closed Monday-to-Monday weeks. Monthly reviews retain the API's existing
week-start ownership: a week belongs to the month containing its Monday. A
month becomes eligible only after its final assigned week closes; January 2026,
for example, is eligible on February 2. Every invocation passes an explicit day,
week start, or month, so delayed execution keeps its intended target.

Schema v4 stores `review_jobs` with `pending`, `completed`, or `skipped` state.
Catch-up queues historical journal days and their parent periods, then runs
jobs by their UTC closing date, with daily → weekly → monthly ordering at a
shared boundary. Earlier summaries are available as context for later reviews. Existing saved reviews satisfy a job,
including recovery after an output commit interrupted before ledger completion.
A failed job stays pending, blocks later work for that pass, and retries next
minute. A source removed before execution is recorded as skipped. Empty periods
without source data produce no AI calls. Later edits, source restoration, or
manual review deletion do not reopen completed/skipped jobs; use the manual
review action to refresh snapshots. First launch can review all previously
unreviewed history and incur the corresponding configured-provider cost.

If you previously installed the systemd timers, retire their installed copies
before using this version:

```bash
./systemd/install.sh   # disables/removes the legacy user timers and services
```

The legacy units are no longer shipped. Their old port-8000 HTTP calls could
reach a separate development database; the new worker makes no HTTP requests.


## Database backups

`POST /api/backup` returns a complete SQLite file as an attachment
(`application/vnd.sqlite3`, `Cache-Control: no-store`). No request body or
filesystem path is needed. For example, against a standalone backend:

```bash
curl --fail --request POST http://127.0.0.1:8000/api/backup --output journal-backup.db
```

Choose an output path separate from the live database. The Settings action uses
the currently connected backend, including the packaged sidecar's ephemeral
port. Desktop saving uses a native dialog and exclusive file creation, preserving
existing files. Browser saving uses the browser's download manager.

`app/backup.py` uses the active engine's aiosqlite connection and SQLite's online
backup API. The snapshot includes committed WAL data, schema version, source
records, associations, settings, review-job state, and derived search indexes.
It does not checkpoint or copy the live main file. The route creates a private
temporary directory and removes it after delivery or failure. A standalone
snapshot is readable with SQLite; full-text/vector queries may require the same
extensions as the app.

Backups include credentials stored in `app_settings`; the file is unencrypted.
Do not upload it as an ordinary diagnostic artifact. Environment configuration
and external embedding caches are excluded. See the root README for default
packaged/development paths and `JOURNAL_DB_PATH` overrides. See Offline recovery
below for restore and automatic pre-upgrade checkpoints.

Ordinary endpoint tests use the in-memory fixture. The WAL concurrency regression
uses an isolated database under pytest's `tmp_path`, because SQLite WAL mode
requires a file database; it never opens user data. In-memory `StaticPool`
backups require a quiescent shared connection; concurrent writes are supported
on the application's file-backed database with independent pooled connections.

## Portable data export

`POST /api/export` downloads a ZIP (`application/zip`, `Cache-Control: no-store`)
with no request body or filesystem path. For a standalone backend:

```bash
curl --fail --request POST http://127.0.0.1:8000/api/export --output journal-export.zip
```

Choose a new output path. Settings uses the active backend URL, including the
packaged sidecar, with browser downloads or an exclusive native save dialog.
Unlike full SQLite backups, portable exports omit the entire `app_settings`
table, AI usage, review jobs, and derived search data. User-authored text is
preserved verbatim, including any sensitive information it contains.

`app/data_export.py` defines explicit column allowlists for ten collections:
`lists`, `tasks`, `time_blocks`, `focus_sessions`, `habits`, `habit_logs`, `journal_entries`,
`daily_scores`, `weekly_summaries`, and `monthly_summaries`. New database columns
are opt-in to the export format. One connection executes an explicit SQLite
`BEGIN` before its first SELECT; every collection is materialized in primary-key
order within that read transaction. This pins a consistent snapshot even in
legacy sqlite transaction mode. No source data is written, no scores are
recalculated, and no embedding or AI calls run.

Archive format `journal-data-export`, version 1:

| Member | Contents |
|---|---|
| `README.md` | Versioned field guide embedded by the serializer |
| `manifest.json` | Format/version, UTC assembly time, per-collection counts |
| `data.json` | UTF-8 JSON collections, including empty arrays |
| `journals/YYYY-MM-DD.md` | Original UTF-8 Markdown; linked from `markdown_file` in journal metadata |

IDs and foreign keys are preserved opaque strings. Timestamps retain fractional
seconds and gain explicit UTC `Z`; dates and month keys retain their stored
labels. Optional nulls remain null; tags remain arrays and flags remain booleans.
Journal content is in Markdown instead of duplicated in JSON. Rating-only
entries have empty files. Review rubric JSON remains a stored string, and
historical scores and journal metrics remain saved snapshots. Timed `due_date`
values, including legacy synthetic 09:00 local fallbacks, are exported unchanged.
The additive v1 `deadline_date` field preserves date-only labels without UTC
conversion. The two fields are mutually exclusive; neither creates a work block.
Consumers should ignore unknown fields when reading v1 archives.

The route owns a private temporary directory and removes it after delivery,
serialization/response failure, or cancellation. No SQLite snapshot is included
in the ZIP. The archive is unencrypted; it is not a restorable database and has
no import endpoint. Regression tests use in-memory fixtures except the isolated
`tmp_path` WAL writer test proving related records come from one snapshot.

## Schema upgrades and recurring tasks

Schema upgrades run automatically before the API starts. Fresh and existing
unversioned databases reach schema v7 through the same versioned migrations.
Version 3 tracks pending and ready search vectors for recovery after offline
embedding or extension failures. Version 5 adds date-only task deadlines without
rewriting legacy due instants; a CHECK prevents conflicting date/timed values.
Version 6 adds task-owned timed work blocks without deriving any from deadlines.
Version 7 adds IANA timezone metadata and all-day intervals, retaining legacy
instants as timed UTC blocks without shifting them.
A failed upgrade leaves the pending changes rolled back and reports the cause;
resolve it and restart the backend. Opening a database written by a newer app
requires upgrading the app.

### Offline recovery

Stop the backend and quit the desktop tray process before restoring. From
`backend/`:

```bash
uv run python -m app.recovery restore /path/to/backup.db --database /path/to/journal.db
```

The bundled sidecar also accepts `restore BACKUP --database DESTINATION`; this
mode does not start uvicorn, scheduling, or the parent-process watcher. Always
specify the intended database, rather than relying on environment defaults.

`app/recovery.py` stages a SQLite online snapshot, validates integrity, foreign
keys, and the versioned source schema, then migrates the staged copy. The input
backup is not upgraded in place. The current destination gets a private online
checkpoint before WAL checkpointing and atomic replacement. Restore prints its
checkpoint path; restore that file with the same command to undo replacement.
Search reconciliation runs on the next normal startup; it rebuilds missing derived
indexes without changing source data. Backups newer than this app are refused.

Before migrations of an existing file database, a verified checkpoint is saved
under the sibling `recovery/` directory and logged. This happens under the startup
writer transaction, before DDL. Failure to save the checkpoint aborts startup.
Pending migrations still roll back atomically on failure; retry after resolving
the reported problem, or use the offline command to restore the checkpoint.
Fresh databases, in-memory tests, and current schemas skip checkpoints. There is
no automatic retention cleanup. Checkpoints contain credentials and private data;
files use mode `0600` and their directory uses `0700` on Unix.

`app/database_lock.py` holds a per-canonical-path OS advisory lock from engine
creation through disposal. Startup failures dispose connections and release it.
Offline recovery takes the same lock; competing backends or restores fail rather
than replacing an open database. The persistent `.lock` file is not a stale PID
marker and must not be removed. Older versions, hard-link aliases, and external
SQLite clients do not participate: stop them before restore. Do not manually
remove `-wal` or `-shm` files. Lock behavior is tested on Linux; packaged restore
and Windows locking still need native smoke verification.

Completing a recurring task keeps its completed history and creates the next
occurrence. Separate tasks can have the same name, rule, and due time without
suppressing each other. Recurring task responses include server-managed
`recurrence_series_id` and zero-based `recurrence_occurrence` fields. Renaming,
moving, or rescheduling an occurrence preserves its identity. Reopening and
recompleting a task reuses its existing successor, including a completed or
canceled successor, instead of creating another copy. Edits apply to that task
only, instead of propagating through the series.

The upgrade treats each existing recurring row as a separate series because
older databases did not record lineage. It preserves the rows instead of
attempting to merge similar tasks or repair past duplicate/missing occurrences.
Deleting a successor permits regeneration if its predecessor is later reopened
and completed again. Supported rules remain DAILY/WEEKLY, INTERVAL, and BYDAY.

## Known limitations / deferred

- Timezone-aware scheduling (store local + convert) is deferred until the frontend lands; naive-UTC is the interim contract.
- Recurrence supports DAILY/WEEKLY rules only; unsupported rules are stored without generating successors.
- Journal routes (TipTap content, mood/energy) are Phase 3; the tables already exist.
- `daily_scores`/`weekly_summaries`/`monthly_summaries` are written by the Phase 4 agents; scoring is live-computed until then.

### Typed task deadlines (schema v5)

Task responses expose `deadline`: `{"kind":"none"}`, `{"kind":"date","date":"YYYY-MM-DD"}`,
or `{"kind":"timed","at":"ISO datetime"}`. Create/PATCH accepts the same non-null
object; clear explicitly with `kind: none`. Unknown union fields, raw
`deadline_date` writes, and simultaneous `deadline`/`due_date` writes return 422.
Legacy `due_date` writes remain a timed alias; null clears. Timed values normalize
to naive UTC. `deadline_date` is a nullable indexed DATE, mutually exclusive with
`due_date`; migration v5 leaves every legacy instant (including 09:00) unchanged.
No work blocks are created.

Date-only deadlines are calendar labels, not midnight instants. Daily telemetry
compares them to the requested UTC day label. Overdue uses `deadline_date < UTC
today` by default; callers may pass `as_of_date=YYYY-MM-DD` for their local today.
Timed overdue remains strict instant comparison. `due_before`/`due_after` filter
only timed deadlines. Clients should treat date-only tasks as overdue after the
end of their local deadline day.

Recurrence preserves date-only versus timed kind; midnight is used only for
calendar arithmetic on date-only recurrence. Undated recurring tasks retain the
existing completion-derived timed successor behavior. Capture without a time
creates a date-only deadline; explicit times retain server-local interpretation.
Export format v1 adds nullable `tasks.deadline_date` compatibly; credentials remain
excluded and calendar labels are exported unchanged.
