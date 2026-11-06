# Journal Backend

Local-first FastAPI + SQLite backend for the task/journal/AI life-OS (see the [root architecture reference](../plan.md)).

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

The UI calendar displays deadlines and separate timed/all-day work blocks. Block
rescheduling changes only the selected block, preserves displayed browser-local
start time and elapsed duration (or all-day date span), and keeps saved timezone
metadata. Nonexistent displayed target times are rejected; repeated times select
the earlier occurrence. The day dialog offers a date-input alternative to drag.
Block creation/deletion and time/zone editing remain API-only. Calendar offers
selected-block .ics snapshots, described below. Future calendar recurrence must keep the anchor's local clock
in its stored IANA zone and resolve each date separately, with explicit resolution
of gaps/folds, instead of adding fixed UTC days (SCHED-03). SCHED-04 defines the
ownership boundary below, not series or exception storage.

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

`app.ai_factory.create_agent_model()` builds a pydantic-ai model for any OpenAI-compatible endpoint or Anthropic. The installed v2 API uses `OpenAIChatModel` with provider objects and `output_type=` on agents; see the [AI implementation reference](../plan.md#7-ai-implementation-blueprint-with-pydanticai).

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
unversioned databases reach schema v15 through the same versioned migrations.
Version 3 tracks pending and ready search vectors for recovery after offline
embedding or extension failures. Version 5 adds date-only task deadlines without
rewriting legacy due instants; a CHECK prevents conflicting date/timed values.
Version 6 adds task-owned timed work blocks without deriving any from deadlines.
Version 7 adds IANA timezone metadata and all-day intervals, retaining legacy
instants as timed UTC blocks without shifting them.
Version 15 adds the read-only inbound calendar cache
(`calendar_inbound_state` per connection, `calendar_inbound_events` per remote
resource); the state includes a monotonic reconciliation revision. Token
capability requires a persisted token, and stored components
require parsed projection fields.
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
and completed again.

New explicit task-rule writes accept only `FREQ=DAILY` or `FREQ=WEEKLY`, positive
integer `INTERVAL` within RFC 5545's signed 32-bit range, and unnumbered `BYDAY`
only for weekly rules. A successor outside the supported date range returns 422
without completing the task. Parsing tolerates case, whitespace, and an optional
`RRULE:` prefix; no silent clamping or field
filtering occurs. Unknown, duplicate, malformed, or unsupported fields return 422.
Existing invalid stored rules remain readable and portable-exportable unchanged;
unrelated edits are allowed, but completion requires clearing or replacing the
rule (otherwise 422). No migration is introduced. Weekly intervals use
Monday-based weeks; task UTC/date arithmetic remains unchanged.

### Task/calendar recurrence boundary (SCHED-04)

`app/recurring_tasks.py` owns completion-triggered task successors;
`app/recurrence.py` owns task-rule arithmetic. Calendar `VEVENT` recurrence belongs
to a separate domain. Current local blocks are nonrecurring and reject calendar
recurrence inputs. ICS-02 retains original external series; REV-17 projects supported
occurrences read-only through the separate `app/external_recurrence.py` module.
Imported and live overlay endpoints accept optional paired `start`/`end` dates
(exclusive end, at most 370 days); calls without a window retain opaque recurrence.
Expansion does not create tasks, blocks, scores, or publication records.
Selected-block CalDAV publication, individual-block ICS snapshot export and
read-only file import are implemented separately below. SCHED-04 itself required
no migration.

- Snapshot export derives each individual block's stable `VEVENT` UID from its
  stable local ID. Never export a task RRULE as a `VEVENT` RRULE; event
  attendance/status must never trigger task successor clones.
- External identity is collection/source + UID + original typed
  `RECURRENCE-ID`: DATE, local date-time with TZID, or UTC date-time. A series
  master uses an explicit master marker. Moved occurrences retain the original
  identity rather than their new start time; never match by title or date.
  Floating series keep their source clock labels. `RANGE=THISANDFUTURE` remains
  unsupported and produces an unplaced diagnostic without changing the resource.
- Preserve overrides, cancellation tombstones, and `EXDATE`/`RDATE` values.
  Unsupported raw provider rules stay opaque/read-only or are rejected atomically,
  never converted to task rules or partially expanded.
- External wall-clock display follows the source timezone with explicit unsafe
  gap/fold diagnostics; local block recurrence remains deferred and task UTC/date
  semantics are unchanged.

## Known limitations / deferred

- Timezone-aware scheduling (store local + convert) is deferred until the frontend lands; naive-UTC is the interim contract.
- Task recurrence supports the strict DAILY/WEEKLY subset above. Local block
  recurrence and external series editing remain deferred; REV-17 supplies bounded
  read-only external occurrence display.
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


## iCalendar snapshot export

In Calendar, expand **Export work blocks**, select blocks, and choose **Download
.ics**. Candidates overlap the displayed month and follow current filters. Each
selected block exports its whole interval; deadlines remain separate. Selection
starts empty and resets on month/filter changes. Finish saving edits first.

API clients can `POST /api/calendar/export` with `{"block_ids":["BLOCK_ID"]}`.
The request allows only a nonempty list of nonempty string IDs; duplicates collapse
and events sort by ID. A missing ID returns 404 without a partial file. The
UTF-8 attachment `meditations-calendar.ics` contains independent VEVENTs:

- UTC timed instants, with source zone metadata in `X-JOURNAL-TIMEZONE`; receiving
  clients display times in their chosen timezone. All-day DATE values retain
  their exclusive end without conversion.
- Stable UUID5-derived UIDs from block IDs, including across moves, task renames,
  and backup/restore. Task title is SUMMARY; canceled owners map to CANCELLED,
  all others to CONFIRMED. LAST-MODIFIED includes task and block updates.
- Task recurrence stays completion-triggered. There is no event RRULE, recurrence
  expansion, or automatic deadline export. Descriptions, journals, credentials,
  tags, and focus history are excluded.
- RFC TEXT escaping and UTF-8-safe 75-octet folding use CRLF. Fractional seconds
  truncate; intervals collapsing at second precision and forbidden TEXT control
  characters return 422 for the entire request. Source data stays unchanged.

The file is unencrypted and includes selected task titles. Export is a snapshot,
instead of live synchronization. Open/import it in a calendar client; reimport
and update behavior varies, so repeated imports may create duplicates. Later
block edits/deletions do not update earlier imports. Subscriptions and calendar
series expansion remain deferred; read-only ICS file imports and outbound CalDAV
are separate features.


## CalDAV connections

For setup, optional user-managed Radicale, and Settings controls, see the
[user calendar synchronization guide](../docs/calendar-sync.md).

Calendar connections can be configured in **Settings → Calendar synchronization**
or through the API below. The backend queue captures changes to explicitly opted-in
blocks and drains only verified, enabled destinations. Journal does not install or start
a server. Use an existing server, optionally a user-managed Radicale instance;
Nextcloud and Baïkal compatibility is not yet verified.

1. `POST /api/calendar/connections` with `server_url` and `calendar_url` to save
   a disabled draft. URLs must share an origin, omit embedded credentials,
   query strings and fragments, and the calendar URL must end in `/`.
2. `POST /api/calendar/connections/{id}/discover` with `username`, `password`, and
   explicit `auth_type` (`basic` or `digest`). This returns calendar URLs, names,
   writable flags and VEVENT support without saving credentials. A password can
   be an app password supported by the server. Browser OAuth is outside scope.
3. `POST /api/calendar/connections/{id}/connect` with those credentials and the
   selected `calendar_url`. Journal rediscovers the destination and accepts only
   a writable event calendar. A dedicated **Meditations** calendar is recommended.
   Password operations require HTTPS or loopback HTTP, such as local Radicale.
4. After a backend restart, `POST /api/calendar/connections/{id}/verify` to use
   stored credentials. Startup disables activity and requires explicit verification
   without opening your vault or contacting the server. Submit `/connect` again
   to replace credentials, including after password changes.
5. `POST /api/calendar/connections/{id}/disconnect` to disable activity, detach
   mappings and remove OS credentials. Remote events remain unchanged. If the
   vault is locked or removal fails, unlock it and retry disconnect. Pending
   cleanup must finish before reconnecting. DELETE on `/{id}` removes only an
   unused disconnected draft without credentials or resource links.

GET `/api/calendar/connections` lists metadata; GET `/{id}/links` lists retained
mappings. Responses never return credentials. A successful connection remains
disabled for synchronization and does not select any local blocks for export.
Ordinary task CRUD works without a configured or reachable calendar server.

### Credential storage and recovery

CalDAV username/password/authentication type are held together in the OS vault,
instead of SQLite or ordinary settings. Linux requires an available Secret
Service provider; macOS uses Keychain and Windows uses Credential Manager.
KWallet must expose a compatible Secret Service interface to work with this
backend. Unavailable vaults fail explicitly instead of falling back to files.

Credential records are scoped to the canonical database path and connection ID.
Moving a database to another path or machine requires entering credentials again;
clean up old records from the original path or with your OS vault tools. Backups
and checkpoints contain connection metadata, instead of OS-vault credentials;
portable exports exclude integration metadata entirely. Restoring a database
requires verification before reconnecting. Interrupted credential writes/removal
leave explicit `removal_pending` metadata: retry disconnect before connecting.

The CalDAV adapter supports discovery and ETag-conditional resource operations;
the separate inspection worker is read-only and runs as part of the lifecycle
queue. Connecting never overwrites linked remote changes. Transactional
edit/deletion capture and scheduling are implemented; explicit synchronization
controls are described below.

### Outbound dispatch service (CAL-04)

Backend integrations can explicitly invoke `OutboundService(sessions, manager)`
from `app.calendar_sync.outbound`; use the application-scoped connection manager
so writes serialize with disconnect and credential changes. `prepare(link_id)`
freezes a revision, `dispatch(link_id)` writes or reconciles it, and
`detach(link_id)` leaves the remote event unchanged. This service consumes
existing link intent; it does not opt in blocks. Database triggers capture source
edits independently of this service.
The connection must be verified, enabled, and have stored credentials.

Schema v10 preserves each dispatch separately from newer local edits. The
serialized event, random ownership marker, resource URL, revision, expected ETag,
and attempted flag survive interruption. Retries inspect the same resource and
use conditional requests. A matching UID alone never establishes ownership.
Conflicts return a link in `conflict` state; callers must inspect that state
instead of treating every nonexceptional return as remote success. Authentication
and operational failures raise fixed-message `OutboundFailure` exceptions after
retaining intent. Local preparation errors can be repaired and retried.

Remote recurrence, invitations, unknown properties, changed versions, and
unowned resources block writes. Recovery of an uncertain successful upsert
requires identical validated properties, including the dispatch marker. Only
line folding and property order within each component are ignored; values,
parameters, whitespace, and component membership remain exact. Other server
rewrites can still require explicit detachment instead of automatic recovery.
Detachment preserves unresolved dispatch evidence and blocks further writes.
Real-HTTP interoperability checks target Radicale 3.9.0 only; see the
[verification scope](../docs/calendar-sync.md#verification-scope). Restarts still require
explicit verification and enablement before any dispatch; the lifecycle worker
remains idle for disabled destinations.

Tests use fake vaults and mocked HTTP, without real accounts or user databases.
See the [root architecture reference, §6.4](../plan.md#64-optional-local-first-calendar-interoperability) for the complete lifecycle contract.

### Durable offline queue (CAL-05)

Changes to linked blocks and event-visible task fields are captured transactionally
in schema v11, including block/task/subtask deletion. Unlinked blocks remain local.
Task completion does not cancel appointments; only task cancellation changes event
status. Ordinary deadlines, descriptions, focus history, and scores stay independent.
Missing or altered required capture triggers cause offline restore validation to fail.

The backend worker retries eligible queued work and inspects acknowledged events
at startup and every 30 seconds after the previous pass finishes. Network or vault
failures retain intent; authentication failures require explicit verification and
enablement. Startup/restore always disables activity first. Setup alone cannot
start publishing events: opt in individual blocks and explicitly enable synchronization.
A local save confirms SQLite persistence, instead of remote synchronization.

Retries reconcile the same immutable resource before writing. Newer edits wait
behind uncertain writes, and changed/missing remote resources become conflicts
instead of being overwritten. A create deleted before any remote attempt needs
no remote cleanup; an uncertain create is reconciled before its queued deletion.
Disconnect leaves remote events unchanged. Closing the app stops the worker;
server availability and other clients are independent of the app lifecycle.
Settings exposes pause/resume and manual Sync now. Real-HTTP Radicale 3.9.0
checks and packaged discovery against a local test server are covered in the
[calendar guide](../docs/calendar-sync.md#developer-verification); native vault
and full desktop verification remain outstanding. Fixed-interval retries have no exponential backoff or
OS network-change listener.

`app/calendar_sync/inbound.py` additionally mirrors read-only external events
(schema v15 cache) from enabled, verified connections. Servers offering
RFC 6578 sync-collection REPORTs reconcile incrementally with stored tokens;
rejected tokens rebuild the cache within the same pass. Other servers use
complete Depth-1 listings. Deletions require a completed inventory or explicit
token-report tombstones; no partial or failed batch can remove cache rows. Initial token reports
replace the complete inventory, including removed members, and GET ETags must
match their reports. Writer-locked cursor/connection comparisons prevent stale
batches from overwriting newer state; cached IDs remain stable. Changing the
selected calendar clears its previous cache/token. Each batch commits atomically
with its durable state. The worker starts with the backend, runs on the
30-second worker interval, on Sync now, and on app resume
(`POST /api/calendar/connections/resume`). Mirrored events surface through
`GET /api/calendar/connections/{id}/inbound/overlay` with explicit freshness/error
status and never modify task data; unparsable resources stay cached with an
explicit state. Startup/restore still require verification and enablement before
remote activity; local-only resume never accesses the vault. A malformed report
fails; only an explicitly unsupported REPORT (405/501) selects listing fallback.

### Settings and explicit publication (CAL-06)

Open **Settings → Calendar synchronization** to discover and select a writable
event calendar, connect, verify after restart, or replace credentials. Prefer a
dedicated **Meditations** calendar. Local-only use requires no account or server.
Setup and verification leave synchronization paused and every block unselected.

Select an individual task-linked block and choose **Publish selected block**,
then **Enable sync**. Blocks publish their whole interval, independently of task
deadlines, completion, focus history, and calendar display filters. **Sync now**
requests one connection-scoped pass; inspect queued changes, conflicts, and errors
instead of interpreting a completed request as proof that every event synced.
The periodic worker also processes eligible work while the app is running.

Additional routes under `/api/calendar/connections/{id}`:

| Method and suffix | Operation |
|---|---|
| `PATCH /sync` | `{ "enabled": true }` enables a verified connection; `false` pauses it |
| `GET /status` | Connection, queued/conflict/error/detached counts, last-success timestamp/state |
| `POST /sync-now` | Drain one finite pass for this enabled connection |
| `POST /blocks/{block_id}/opt-in` | Select one block explicitly |
| `POST /blocks/{block_id}/opt-out` | Queue removal of its linked event, preserving local data |
| `POST /links/{link_id}/detach` | Keep the remote event and stop synchronization |

**Remove remote event** queues conditional deletion; it can remain pending offline.
A newer explicit opt-in retains the same resource URL/UID and reconciles uncertain
older requests first. **Stop syncing; keep remote** resolves a conflict through
explicit detachment. Detached/disconnected mappings cannot silently resume.
**Disconnect** stops activity and removes local OS credentials, leaving remote
events unchanged. For credential removal failures, unlock the vault and retry.
Remote cleanup should be completed with opt-out before disconnecting if desired.

Schema v12 stores explicit selection intent and real acknowledgment timestamps.
`last_success_state` is `observed` with `last_success_at`, `unknown` for legacy
acknowledgments lacking a recorded time, or `never` before any known remote sync.
Local edits and conflicts do not change the recorded acknowledgment time.
Backups/checkpoints/offline recovery retain the fields; portable exports omit
integration metadata. Neither database migrations nor opening Settings contacts
the server or vault automatically. The server is user-managed and must be reachable;
other devices cannot access a localhost-only server. Real-HTTP integration checks target Radicale 3.9.0, including discovery,
authentication, writes, conflicts, response loss, offline/restart behavior, DST,
and all-day dates. Packaged discovery is checked against a local server only.
Native vault and full desktop operation remain unverified. Nextcloud and Baïkal
are unverified; no support claim is made for them. See the
[calendar guide](../docs/calendar-sync.md) for setup and verification commands.


## Read-only iCalendar file imports

Settings provides explicit new/existing destinations, upload feedback, a source-value
inventory, and confirmed removal. `app/calendar_import/` parses with `icalendar`
and persists independently of tasks, work blocks, focus, scoring and outbound sync.
Schema v13 adds sources, retained upload snapshots and opaque event identities.
Imports do not expand occurrences. Calendar optionally projects standalone
appointments through a read-only overlay.

`POST /api/calendar/imports` accepts `{target: {kind: "new", name: "Personal"},
content: "..."}` or `{target: {kind: "existing", source_id: "..."}, content: "..."}`.
Within a source, UID plus original typed recurrence ID/TZID identifies a record;
a master has an explicit identity. Latest explicit import wins, absent identities
remain, and duplicate incoming identities reject the whole file. Original text
retains timezone definitions, properties, recurrence and exception semantics.
Unsupported components and detected malformed data fail atomically before writes.
Stored source times remain labeled opaque strings. The separate overlay projection
resolves supported standalone intervals without changing stored imports.

GET on the prefix lists destinations; `/{source_id}/events` reads inventory and
`/{source_id}/snapshots` returns original text/history. `/{source_id}/overlay`
returns explicit date/timed/floating standalone intervals and unplaced reasons
for recurrence, cancellations, durations or unsafe clock values. Named timezone
resolution uses each event's retained snapshot context, with embedded VTIMEZONE
definitions taking precedence over IANA registry zones. Definitions cannot leak
between sources or historical snapshots. Output timed instants are UTC Z strings.
The endpoint never writes sources or local task data.
DELETE `/{source_id}`
cascades imported content only. Backups/offline restore include all imported
content; portable export deliberately excludes these tables. Source deletion is
the retention control. See [calendar import guide](../docs/calendar-import.md).

Packaged import verification can be run after building the sidecar:

```bash
uv run python scripts/smoke_sidecar.py /path/to/meditations-backend --calendar-import
```

This uses a disposable database and local API only; the import check retains a
BOM-prefixed recurring event and its original text without expanding occurrences.
It does not access a native credential store or any user calendar server.

## Optional outgoing webhooks

`app/webhooks/` owns versioned transactional automation events and the durable
per-endpoint delivery worker. `/api/webhooks` configures event/list scopes,
optional title sharing, endpoint enablement, synthetic tests, status, and retry.
The four subscriptions cover time-block create/update/delete and task completion.
The worker runs with the backend and retains offline work in SQLite; local saves
never depend on a reachable receiver. Endpoint secrets use the OS credential-store
interface with a separate webhook namespace. SQLite backups include configuration
and outbox payloads, while portable data exports exclude them.

See [the event/signature contract and local workflow example](../docs/webhooks.md).
HTTP acknowledgement is separate from successful downstream calendar updates.
