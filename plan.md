# Architecture & Implementation Plan: Modern Todo, Journaling & AI Life-Operating System

---

## 1. Executive Summary & Product Vision

This project is a modern, unified personal operating system combining:
1. **TickTick-grade Task Management**: Fast natural language capture, hierarchical subtasks, priority matrices, tags/lists, focus/Pomodoro tracking, and fluid Kanban/Calendar views.
2. **Reflective Long-Form Journaling**: TipTap-based rich block/markdown editor with automated daily activity embeds (tasks finished, focus hours logged, habits kept) and quantified mood/energy tracking.
3. **Hierarchical AI Agent System**: A proactive "Life Coach & Chief of Staff" agent that solves the LLM memory blowup problem via **hierarchical compaction**, scores daily performance objectively with deterministic math + qualitative feedback, breaks down complex tasks, and offers conversational capture and semantic search over historical entries.

### Core Philosophy
* **Frictionless Capture**: Task input must take under 3 seconds using inline shorthand (`buy milk tomorrow 5pm !1 #personal`).
* **Bounded Context Memory ($O(1)$ Token Growth)**: Raw journal entries are never re-read forever. Older days collapse into weekly summaries; weeks collapse into monthly reviews. The agent's token budget remains constant whether on Day 10 or Year 5.
* **Deterministic Scoring Over Hallucinated Scores**: Productivity scores are calculated mathematically from structured telemetry (completion rate, deep-work hours, streak multipliers), while the LLM acts as an analytical mentor providing qualitative feedback and trend diagnosis.
* **Local-First & Privacy-Focused**: Powered by SQLite (WAL mode) with optional local vector embeddings and local LLM support (Ollama), running seamlessly on EndeavourOS / Linux with minimal resource footprint.

---

## 2. Recommended Modern Tech Stack

### 2.1 Technology Matrix

| Layer | Recommended Choice | Rationale & Alternatives Considered |
|---|---|---|
| **Frontend Framework** | **React 19 + Vite** (or **Next.js 15 App Router**) + **Tauri v2** | Blazing fast development, minimal memory (~40MB RAM under Tauri vs 400MB+ under Electron). Tauri v2 allows native desktop global shortcuts (e.g., `Super+Shift+A` for instant quick-add) and system tray integration on Linux. |
| **Styling & UI Kit** | **Tailwind CSS v4** + **shadcn/ui** (Radix UI) + **Framer Motion** | Dark glass aesthetic, keyboard-accessible primitives, zero runtime CSS bloat, and fluid micro-interactions (strikethroughs, drag handles, modal drawers). |
| **Rich-Text Editor** | **TipTap v2** (ProseMirror wrapper) | Industry standard for Notion/TickTick-like editors. Extensible for slash commands (`/task`, `/callout`), markdown shortcuts, task list checkboxes, and inline AI completion. |
| **Date & Syntax NLP** | **chrono-node** | Instant client-side natural language date parsing (`tomorrow at 5pm`, `every mon, wed`) without network latency. |
| **Drag & Drop** | **@dnd-kit/core** + **@dnd-kit/sortable** | Accessible, performant, mobile-friendly drag-and-drop for Kanban boards, Eisenhower matrices, and task reordering. |
| **State & Data Fetching**| **TanStack Query (React Query v5)** + **Zustand** | Optimistic mutations for 0ms task completion latency, offline caching, and lightweight state for timers/filters. |
| **Backend API** | **FastAPI (Python 3.12+)** with `uvicorn` | First-class ecosystem for AI agent orchestration, asynchronous endpoints, Pydantic v2 data validation, and native SQLite integration. |
| **Database** | **SQLite (WAL Mode)** + **SQLModel** (or **SQLAlchemy 2.0 Async**) | Single-file zero-ops database, microsecond queries, ACID compliance, zero maintenance overhead, and privacy-preserving. |
| **Search & Vectors** | **sqlite-vec** + **SQLite FTS5** | Hybrid full-text keyword search (FTS5) plus native vector similarity embeddings (`sqlite-vec`) in the same database without running external Chroma/Qdrant services. |
| **AI Agent Framework** | **PydanticAI** (Primary) + **LiteLLM** | Modern, strictly typed agent framework with type-safe dependency injection, structured tool calls, and model-agnostic switching (Claude, OpenAI, DeepSeek, Groq, or local Ollama). Fully configurable custom `base_url` and `api_key`. |
| **Local Model / Offline**| **Ollama** (`llama3.2:3b` / `qwen2.5:7b`) + **fastembed** | Zero-cost local inference via OpenAI-compatible `base_url` (`http://localhost:11434/v1`), offline tagging, and on-device text embeddings (`bge-small-en-v1.5`). |
| **System Orchestration**| **Backend lifecycle worker** | Database-local UTC review scheduling with durable catch-up; enabled in the packaged sidecar, opt-in for standalone backends. |

---

## 3. AI Agent Architecture: Deep Dive

### 3.1 Why PydanticAI?
For modern Python-based AI agents, **PydanticAI** (created by the Pydantic team) is the top choice over legacy LangChain:
1. **Type-Safe Structured Output**: Validates all agent responses directly into Pydantic models with automated retry loops if schemas fail.
2. **Model Agnostic**: Seamlessly switches between Anthropic (Claude 3.5 Sonnet / Haiku), OpenAI (GPT-4o), Groq, and local models (Ollama).
3. **Dependency Injection**: Pass database sessions, user preferences, and configuration directly into tool functions without global state.
4. **Clean & Lightweight**: Minimal abstractions, transparent prompt chains, and pure Pythonic async execution.

### 3.2 Provider Agility: Configurable `base_url` and `api_key`
A key requirement is total freedom of model backend. You shouldn't be locked into a single cloud vendor. The agent system supports:
1. **Custom `base_url`**:
   - **Local Ollama**: `http://localhost:11434/v1` (run models like `llama3.2:3b`, `qwen2.5:7b` completely offline and private for free).
   - **OpenRouter**: `https://openrouter.ai/api/v1` (access hundreds of models with a single unified key).
   - **Groq / Together / DeepSeek / Mistral / vLLM**: Any OpenAI-compatible endpoint.
   - **Official OpenAI / Anthropic**: Native default base URLs.
2. **Dynamic API Key Management**:
   - Primary: `.env` environment variables (`AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL_NAME`).
   - App Settings: An optional `app_settings` table in SQLite so keys and endpoints can be updated directly from the frontend UI settings drawer without restarting backend services.
3. **PydanticAI Dynamic Model Loader**:
   - Supports instantiating `OpenAIModel` with custom `base_url` and `api_key`, or `AnthropicModel`, or fallbacks with automatic failover.

### 3.3 The Hierarchical Compaction Engine

The core problem of AI journaling is context bloat. As time progresses, feeding hundreds of raw daily entries into an LLM exceeds context limits and increases costs.

```
[ Day 1 .. Day 7 Raw Entries ] ──► Daily Agent (Reads today + last 6d + last week summary)
             │
             ▼ (End of Week Cron)
  [ Weekly Summary Compacted ] ──► Weekly Agent (Reads 7 daily scores + last 4 weekly summaries)
             │
             ▼ (End of Month Cron)
 [ Monthly Review Compacted ]  ──► Monthly Agent (Reads 4 weekly summaries + last 3 monthly summaries)
```

#### Bounded Input Constraints:
* **Daily Agent Run** (Scheduled after the UTC day closes, or requested manually):
  * Inputs: Today's raw text + deterministic metrics + past 6 days' raw text + latest 1 weekly summary + latest 1 monthly summary.
  * Maximum token footprint: ~4,000 tokens ($O(1)$).
  * Output: Qualitative feedback, identified cognitive blindspots, suggested wins/misses, and nudges.
* **Weekly Agent Run** (Scheduled after Monday 00:00 UTC for the closed week):
  * Inputs: 7 daily scores & structured metadata (tasks done, deep-work hours) + last 4 weekly summaries + latest monthly summary. **Raw daily journal text is never read again.**
  * Output: Week rollup (average score, primary wins, friction points, carried-over habits).
* **Monthly Agent Run** (Scheduled after the month's final Monday-owned week closes):
  * Inputs: 4–5 weekly summaries from the current month + last 2–3 monthly summaries.
  * Output: High-level narrative, macro productivity trends, personal growth insights.

Manual `POST /api/agents/rollup/monthly` requests accept `month=YYYY-MM` or
`month=previous`. Omitting `month` selects the current UTC month, except on the
first day of a month when it selects the previous month. Explicit months require
a four-digit year and two-digit month; invalid values return HTTP 422. A valid
month without weekly summaries returns HTTP 404 without calling the model.

#### Scheduled review ownership and recovery (FIX-05)

`app/review_scheduler.py` runs inside the packaged sidecar against its session
factory, independent of the ephemeral HTTP port. Standalone backends default to
scheduling off (`JOURNAL_SCHEDULED_REVIEWS=true` opts in); one backend process
owns a database. The worker starts after migrations/search recovery, checks at
startup and every minute, and is cancelled before engine disposal.

All boundaries use UTC; persisted datetimes remain naive UTC. A daily target is
an existing journal date before today. Weeks are half-open Monday-to-Monday
periods and become eligible only after closing. Months retain the rollup API's
Monday ownership of weekly summaries: the final week whose Monday lies in the
month must close before its monthly job can run, even if that is several days
into the next month. All calls pass explicit target periods.

Migration v4 adds `review_jobs`, keyed by `(kind, period)`, with explicit
`pending`, `completed`, and `skipped` states. Planning uses existing journal days
and weekly summary periods, including unreviewed historical sources on first
launch. Work runs by UTC closing date, with daily → weekly → monthly ordering at a
shared boundary, so earlier summaries are available to later daily/weekly
reviews as context.
Failures preserve pending state and stop the pass so parents cannot summarize
unfinished work. Missing sources yield skipped jobs. Existing review outputs
satisfy pending jobs, recovering the interruption between output commit and
ledger commit without another model call. Completed/skipped jobs stay terminal;
later edits, source restoration, or output deletion require a manual review.
Manual reviews remain re-runnable snapshots. The application must be running
for scheduling; restart catches up missed work. Initial historical catch-up can
incur provider costs. Existing installed systemd timers must be retired using
`systemd/install.sh`; legacy HTTP unit files are no longer shipped.

### 3.4 Deterministic Hybrid Scoring Formula

To prevent LLM "score drift" (where a score of 75 on Day 1 means something completely different on Day 60), the quantitative score is computed deterministically in Python:

$$\text{Daily Score} = (W_{\text{task}} \times S_{\text{task}}) + (W_{\text{focus}} \times S_{\text{focus}}) + (W_{\text{habit}} \times S_{\text{habit}}) + \Delta_{\text{LLM}}$$

Where:
* $S_{\text{task}} = \min(100, \frac{\text{tasks\_completed}}{\max(\text{tasks\_planned}, 1)} \times 100)$ (Weight: 40%)
* $S_{\text{focus}} = \min(100, \frac{\text{hours\_deep\_work}}{\text{target\_hours}} \times 100)$ (Weight: 35%)
* $S_{\text{habit}} = \frac{\text{habits\_done}}{\text{habits\_scheduled}} \times 100$ (Weight: 15%)
* $\Delta_{\text{LLM}} \in [-10, +10]$: A bounded qualitative adjustment given by the LLM with an explicit documented justification (e.g., handled an unexpected high-stress emergency well, or procrastinated despite empty calendar).

### Score targets and review snapshots

`app/score_service.py` resolves the effective focus target for preferences, live
scores, daily reviews (including streaming), and weekly fallback scores. Missing
or invalid stored targets use the four-hour default; valid preferences are finite,
greater than zero, and at most 16 hours. All paths use `compute_daily_score`,
including the final bounded nudge and the persisted rubric.

Daily reviews snapshot metrics, target, and nudge at review time. Changing the
focus target or activity does not rewrite saved reviews. Re-running a review
replaces that day's snapshot. Weekly reviews use saved daily scores where present;
unreviewed days use current telemetry and the current target with zero nudge.
Existing weekly/monthly summaries remain unchanged until explicitly re-run.

`GET /api/scores/daily/{day}` always recalculates live with the current target
(or its request-only `target_hours` override) and any saved LLM nudge. Its
`score_basis` is `live`; daily rollup responses use `review_snapshot`.
`saved_review_score` exposes the stored final score, or null when no review exists.
`persisted` indicates that a review exists, rather than that the live number was
stored. The journal card labels its live score and displays the saved review score
separately. Older reviews remain snapshots; historical targets are not inferred
or rewritten.

---

## 4. System Architecture & Component Design

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Vite / Tauri v2)                      │
│                                                                        │
│  ┌───────────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │   Quick Add Bar       │  │  TipTap Editor  │  │  Views:          │  │
│  │   (chrono-node NLP,   │  │  (Daily Notes,  │  │  • Kanban Board │  │
│  │   !priority, #tags)   │  │  Auto-Embeds)   │  │  • Calendar/Time │  │
│  └───────────────────────┘  └─────────────────┘  │  • Habit Grid    │  │
│  ┌────────────────────────────────────────────┐  └──────────────────┘  │
│  │     Zustand Store + TanStack Query         │                        │
│  │     (Optimistic UI updates, Pomodoro clock)│                        │
│  └────────────────────────────────────────────┘                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST / WebSocket
┌───────────────────────────────────▼────────────────────────────────────┐
│                        BACKEND (FastAPI API)                           │
│                                                                        │
│  ┌───────────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │ Task & Habit Routes   │  │ Journal Routes  │  │ Focus Timer API  │  │
│  └───────────────────────┘  └─────────────────┘  └──────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   AI Agent Module (PydanticAI)                   │  │
│  │   • Daily/Weekly Compactor   • Natural Language Task Extractor   │  │
│  │   • Task Decomposition Agent • Hybrid RAG (sqlite-vec + FTS5)    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │ SQLModel / SQLite Engine        │
┌──────────────────▼─────────────────────────────────▼───────────────────┐
│                     STORAGE & SYSTEM ORCHESTRATION                     │
│                                                                        │
│  SQLite DB (WAL Mode):                                                 │
│  • tasks, subtasks, habits, focus_sessions                             │
│  • entries, daily_scores, weekly_summaries, monthly_summaries           │
│  • virtual tables: fts_entries (FTS5), vec_entries (sqlite-vec)        │
│                                                                        │
│  Backend lifecycle review worker (same database, no HTTP):             │
│  • closed UTC days → weeks → months; explicit period targets          │
│  • review_jobs: pending / completed / skipped                          │
│  • startup + minute catch-up; cancelled before database shutdown       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Database Schema Specification (SQLite)

Startup applies the ordered migrations in `backend/app/migrations/` before
search initialization, requests, or startup jobs. `PRAGMA user_version` records
the schema version: v1 is the frozen pre-identity baseline; v2 adds task
recurrence identity; v3 adds `search_vector_state` (`doc_id` primary key and
`state`, either `pending` or `ready`). v4 adds the durable review-job ledger. Fresh installations run all four.
Existing unversioned installations adopt the baseline and then upgrade. An explicit SQLite
`BEGIN IMMEDIATE` serializes startup writers; pending schema changes, backfills,
and version updates commit together. A failed upgrade rolls back the pending
batch and reports the failed version; resolve the reported cause and restart.
A database from a newer app version is refused instead of downgraded.
Future model changes require a new migration; startup does not use `create_all`.
Existing file-backed databases get a verified private online checkpoint before
pending DDL; fresh databases, current versions, and in-memory engines skip it.
Checkpoint failure aborts the upgrade. See DATA-03 recovery below.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. Lists & Projects
CREATE TABLE lists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#64748b',
    icon TEXT,
    is_favorite BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. Tasks & Subtasks
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    list_id TEXT REFERENCES lists(id) ON DELETE SET NULL,
    parent_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 0, -- 0: None, 1: Low (!3), 2: Med (!2), 3: High (!1)
    status TEXT DEFAULT 'todo', -- 'todo', 'in_progress', 'completed', 'canceled'
    due_date DATETIME,
    estimated_minutes INTEGER,
    actual_minutes INTEGER DEFAULT 0,
    recurrence_rule TEXT, -- e.g. 'FREQ=DAILY;INTERVAL=1' or 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR'
    recurrence_series_id TEXT,
    recurrence_occurrence INTEGER, -- zero-based identity; independent of due_date
    tags TEXT, -- JSON array of tags: ["work", "dev"]
    order_index REAL NOT NULL DEFAULT 0.0,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uq_task_recurrence_occurrence
    ON tasks (recurrence_series_id, recurrence_occurrence);

-- 3. Focus / Pomodoro Sessions
CREATE TABLE focus_sessions (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    duration_minutes INTEGER NOT NULL,
    session_type TEXT DEFAULT 'pomodoro', -- 'pomodoro', 'stopwatch'
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 4. Habits & Logs
CREATE TABLE habits (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_frequency TEXT DEFAULT 'daily', -- 'daily', 'weekdays', '3x_week'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE habit_logs (
    id TEXT PRIMARY KEY,
    habit_id TEXT NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    completed BOOLEAN DEFAULT 1,
    UNIQUE(habit_id, date)
);

-- 5. Journal Entries
CREATE TABLE journal_entries (
    date DATE PRIMARY KEY,
    raw_markdown TEXT NOT NULL,
    mood INTEGER CHECK(mood BETWEEN 1 AND 5),
    energy INTEGER CHECK(energy BETWEEN 1 AND 5),
    hours_deep_work REAL DEFAULT 0.0,
    tasks_planned INTEGER DEFAULT 0,
    tasks_done INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 6. Hierarchical Compactions & Scoring
CREATE TABLE daily_scores (
    date DATE PRIMARY KEY REFERENCES journal_entries(date) ON DELETE CASCADE,
    deterministic_score REAL NOT NULL,
    llm_nudge REAL DEFAULT 0.0,
    final_score REAL NOT NULL,
    rubric_breakdown_json TEXT NOT NULL,
    feedback TEXT NOT NULL,
    insight TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE weekly_summaries (
    week_start DATE PRIMARY KEY,
    avg_score REAL NOT NULL,
    trend TEXT NOT NULL, -- 'rising', 'declining', 'stable'
    wins TEXT NOT NULL,
    misses TEXT NOT NULL,
    carried_action_items TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE monthly_summaries (
    month TEXT PRIMARY KEY, -- 'YYYY-MM'
    avg_score REAL NOT NULL,
    trend TEXT NOT NULL,
    narrative TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. Detailed Feature Specifications

### 6.1 Feature Module 1: The TickTick-Grade Task Engine
1. **Quick-Add Parsing Bar**:
   - Parses date, time, recurring patterns, tags, priority, and target list simultaneously.
   - Example syntax: `Review Q3 budget tomorrow 3pm !1 #finance @urgent ~45m`
   - Parsed entities:
     - Title: `Review Q3 budget`
     - Due: Tomorrow at 15:00
     - Priority: High (`!1`)
     - List: `finance`
     - Tag: `urgent`
     - Estimated duration: 45 minutes
2. **Multi-View Modes**:
   - **List View**: Grouped by Today, Upcoming, Overdue, or custom tag/list.
   - **Kanban Board**: Drag-and-drop between lists or statuses (`To Do`, `In Progress`, `Done`).
   - **Interactive Calendar**: Six-week month grid of task due dates; drag between days to reschedule. Task-linked work blocks remain planned scheduling work.
3. **Integrated Focus Engine (Pomodoro & Stopwatch)**:
   - Floating or full-screen focus timer linked to the active task.
   - Automatically writes finished session durations into `focus_sessions` and task `actual_minutes`.

#### Calendar, date, and timer contracts (QA-04)

`frontend/src/lib/task-filter.ts` shares scope and title/tag search selection
between task sections and the calendar. Today includes overdue and today's
local dates; Upcoming includes tomorrow and later; All and list scopes contain
unfinished tasks, including undated ones. Completed scope contains completed
tasks. Canceled tasks are excluded. Nested list children follow the same filters;
a matching child whose parent is excluded can appear at the top level. The
calendar renders only tasks with valid due instants, including dated subtasks,
and limits each day cell to four chips with the remainder available in its dialog.
Calendar creation uses the currently selected list, or no list for smart scopes.

Task scheduling still has one `due_date` instant. Date-only quick-add phrases
and calendar creation choose 09:00 local time; this is a fallback time rather
than an all-day flag. Naive backend timestamps are parsed as UTC, then grouped
by the browser's local date. Moving a task preserves its local hours, minutes,
seconds, and milliseconds and serializes the new instant as ISO UTC. Local Date
construction advances nonexistent DST times by the gap and picks the earlier
offset for ambiguous times. Explicit all-day intervals, IANA timezone metadata,
and separate deadlines/work blocks remain SCHED-01 through SCHED-03.

The focus timer measures running wall time using `Date.now()` deltas, carrying
fractional seconds across ticks and pauses. Delayed callbacks and system suspend
count within the current app lifecycle; paused time does not. Synchronization
happens on interval callbacks, pause, reset, mode changes, and stopwatch log-stop.
Reset/mode changes discard unfinished progress but retain any completed work
discovered at synchronization. Backward wall-clock jumps contribute zero for
that synchronization; forward corrections count as elapsed wall time.

A Pomodoro work boundary queues one session with its configured duration and
linked task. Delayed callbacks consume elapsed break time, then stop at a fresh
paused work phase; they never synthesize additional work cycles. The controller
drains completion events before side effects, including under StrictMode. Hiding
the widget keeps the controller active. Stopwatch log-stop records only when at
least 60 whole seconds have elapsed and rounds to the nearest minute. Settings
persist, but application reload starts paused with progress reset. Session dates
remain the backend recording time, including completions discovered after
suspend. Delivery is once per client event; durable network retry/idempotency is
outside this change.

`npm run test:timezones` runs the controlled calendar, selector, parsing, date,
and timer regressions in fresh processes under UTC, Asia/Kolkata,
America/New_York, and Pacific/Kiritimati. Fake clocks exercise delayed callbacks
without relying on actual host sleep or callback cadence.

#### Task cache concurrency and telemetry refresh (QA-03)

All task views share the `['tasks']` query. `frontend/src/hooks/task-cache.ts`
coordinates optimistic task creation, updates, deletion, and list removal per
QueryClient. A mutation cancels task fetches, then adds its change to a shared
snapshot. Rollback removes only the failed change and replays the remaining
changes in submission order, including successes still overlapping pending
requests. Creation replaces its temporary row with the server-assigned task;
deletion hides the full descendant tree. These changes affect the cache only;
server transactions and recurrence remain authoritative.

Settlement invalidates the canonical task query, but active refetch waits until
all overlapping task changes settle. Focus logging, capture, and decomposition
use the same invalidation gate. Independent task refetches retain in-flight
changes over the fresh server snapshot; canceled query results cannot replace
that snapshot. Once the batch finishes, refetch reconciles server-generated
recurrences and actual server ordering, including concurrent writes to the same
field. Inactive queries stay invalidated and refresh when revisited.

Task create/update/delete, focus logging, and capture also invalidate all cached
journal activity, daily scores, and insights ranges: overdue tasks and edits to
completion dates can affect more than the current day. Focus logging refreshes
focus summaries. Capture additionally refreshes journal entries and calendar
dots. Task-only changes do not alter journal-day metadata; deleting a list only
clears task associations, and decomposition adds undated, unfinished subtasks.
Neither changes telemetry. Saved review scores remain snapshots until rerun.

#### Completion-triggered recurrence identity

`backend/app/recurring_tasks.py` owns task-series identity and successor creation;
`recurrence.py` owns RRULE date arithmetic. This is separate from future calendar
provider recurrence. The supported subset remains DAILY/WEEKLY with INTERVAL
and optional weekly BYDAY.

- Recurring tasks receive a server-managed `recurrence_series_id` equal to the
  root task ID and `recurrence_occurrence = 0`. Clones share the series ID and
  increment the occurrence number. These fields are returned by task APIs;
  create/update inputs cannot assign them.
- Non-recurring tasks have null identity fields until recurrence is enabled.
  Removing the rule stops regeneration but retains any existing identity;
  re-enabling recurrence resumes the same identity.
- Completion preserves the finished row and its focus/completion history. The
  successor copies task configuration, starts as todo with zero actual minutes,
  and shares the completion transaction. Its due date is computed from the
  current task's due date, or completion time when undated.
- `(series_id, occurrence_number)` is unique in SQLite. Conflict-targeted insert
  makes recompletion idempotent even if a successor was renamed, moved,
  rescheduled, completed, or canceled. Title, rule, date, and status are not
  identity. Changing a task edits only that row; it does not rewrite an existing
  successor or the rest of the series.
- Series IDs are values instead of foreign keys to a root row. Deleting a root
  does not invalidate surviving occurrences. If a successor is deleted,
  reopening and recompleting its predecessor may regenerate that occurrence.
  Deleted rows do not leave recurrence tombstones.
- Existing databases contain no reliable historical lineage. Migration v2
  preserves every legacy recurring row as an independent occurrence-zero
  series, including completed rows; it never merges rows by matching names or
  dates. Reopening legacy history can therefore regenerate an occurrence even
  if an unrelated legacy row happens to match it. The upgrade cannot repair
  previously suppressed or duplicated occurrences automatically.

### 6.2 Feature Module 2: The Modern Journaling Engine
1. **TipTap Markdown Block Editor**:
   - Clean typographical hierarchy with Notion-style slash commands (`/h1`, `/task`, `/quote`, `/callout`).
   - Saves use a 700 ms debounce with the day, markdown, mood, and energy frozen at schedule time. Undoing to the loaded text replaces queued content while preserving current ratings.
   - Loading stored markdown suppresses editor update events. The editor, ratings, and content-insertion buttons stay disabled until the selected day's entry resolves; the journal surface exposes its busy state. Visiting an empty day creates no entry; every day switch (including Today and search-result navigation), section exit, and editor unmount flushes queued changes to their original day.
   - Activity insertion belongs to the active editor lifecycle: changing days, leaving the journal, or unmounting invalidates pending results, even after returning to the same day. Same-day results append to the latest text rather than overwriting edits made during the request. Slash-extension callbacks dispatch through current handlers because ProseMirror retains the initially configured callbacks.
   - External `journalDay` is a one-shot navigation command and is consumed even when that day is already selected.
2. **Automated Daily Activity Rollup Embeds**:
   - At the top or bottom of today's journal entry, a one-click button inserts live data:
     - **Tasks Completed Today**: `[x] Submit report`, `[x] Code review`.
     - **Focus Stats**: Total deep-work time (e.g., `3h 45m across 4 sessions`).
     - **Habit Checklist**: Water, Workout, Reading.
3. **Daily Reflection Templates**:
   - Configurable prompts: "What was the main friction point today?", "What is one win to celebrate?", "What should be deprioritized tomorrow?"

### 6.3 Feature Module 3: Proactive AI Agent Features
1. **Hierarchical Summarization & Review Agent**:
   - Evaluates daily balance, detects habit degradation early, and produces actionable insights.
2. **Smart Task Decomposition Agent**:
   - User inputs: `Plan product launch`.
   - Agent outputs structured subtasks with estimated times and priority suggestions.
3. **Conversational Daily Planning Briefing**:
   - Every morning, agent reviews overdue tasks, today's calendar, and yesterday's reflection to recommend an achievable Top 3 Priority Focus.
4. **Natural Language Omnibar & Conversational Capture**:
   - Dictate or paste unstructured text: *"Spoke with Alex. Need to email him the slide deck by Thursday 4pm and schedule team sync for Monday."*
   - Agent creates the journal note snippet and registers two tasks with explicit due dates.
5. **Ask My Second Brain (Hybrid Search)**:
   - Ask questions like: *"When did I start feeling burned out on the backend refactor and what caused it?"*
   - Queries `sqlite-vec` embeddings and `fts_entries` to cite past journal entries and weekly rollups.

#### Consistent database backups (DATA-02)

`POST /api/backup` downloads a full SQLite snapshot from the active application
engine through `app/backup.py` and SQLite's online backup API. It includes schema
version, committed source data and associations, settings, reviews/job ledger,
and derived search indexes, including committed pages still in WAL. Uncommitted
writes, unsaved editor state, environment files, and external embedding caches
are excluded. Backups require no schema migration.

The route accepts no filesystem paths and stages each snapshot in a private
temporary directory. File delivery uses an attachment with `Cache-Control:
no-store`; completion, transmission errors, and cancellation release temporary
files. Cancellation must drain SQLite's backup worker before releasing either
connection or deleting its target. File-backed WAL connections allow concurrent
committed writes; the in-memory StaticPool test configuration requires a
quiescent shared connection.

Settings exposes this operation through the resolved backend URL. Browser users
receive a `.db` download. Packaged desktop users choose a path through the
first-party Tauri dialog plugin; the filesystem plugin writes with exclusive
creation and Unix mode `0600`, so saving cannot replace an existing database or
backup. Capabilities grant only save-dialog and write-file operations; the dialog
dynamically scopes access to the selected file. Cancellation before choosing a
path creates no backup. Native write errors may leave an incomplete new file and
must not report success.

A backup is unencrypted and includes provider credentials persisted in
`app_settings`. UI and documentation warn users to protect it. This is distinct
from portable data export (DATA-04).

#### Offline restore and pre-upgrade recovery (DATA-03)

`python -m app.recovery restore BACKUP --database DESTINATION` performs an offline
restore; the packaged backend exposes the same subcommand without starting the
server or parent watcher. The desktop must be quit (not hidden to tray) and all
other database users stopped. There is no live restore endpoint or Settings
restore UI.

`DatabaseLock` uses an OS advisory lock on a persistent sibling `.lock` file keyed
by the resolved database path. A backend acquires it before connecting and holds
it through connection disposal, including failed startup. Restore holds the same
lock for staging, validation, checkpointing, and replacement. This enforces one
cooperating backend per database; older apps, hard-link aliases, and external
SQLite tools remain the operator's responsibility. Lock files must not be unlinked.

Recovery uses SQLite online backup into a private same-directory staged file,
checks integrity, foreign keys, and the frozen versioned source-schema contract,
and migrates the staged copy without modifying the input backup. Missing derived
search indexes are allowed and reconstructed by normal startup reconciliation.
Newer or incompatible schemas are refused before destination replacement.
An existing destination is snapshotted before its WAL is checkpointed and all
recovery connections close; `os.replace` then installs the staged database.
The command prints the prior checkpoint path. Interrupted staging or replacement
failure leaves the original database usable; a completed replacement can be undone
by restoring that checkpoint offline.

Before an existing file database's pending migration batch, `migrate()` saves a
verified SQLite online checkpoint under `recovery/` beside the database while
holding `BEGIN IMMEDIATE`, before changing schema or data. Failure aborts startup;
migration errors retain both the rolled-back database and its checkpoint. Staging
restores disable this redundant checkpoint. Unix checkpoint files are `0600`, the
recovery directory is `0700`, and no automatic pruning runs. They include private
content and stored credentials. Current-schema startups, fresh installs, and
in-memory databases do not create checkpoints.

#### Portable data export (DATA-04)

`POST /api/export` creates an unencrypted ZIP from `app/data_export.py`. Settings
exposes a distinct portable-export action alongside full database backup. Native
and browser delivery share `lib/file-download.ts`; separate module wrappers and
hooks retain independent artifact lifetimes, pending states, and errors.
No export importer or database-restore behavior is implied.

The archive's independent format is `journal-data-export`, version 1. It contains
an embedded `README.md` field guide, `manifest.json` (format, version, UTC assembly
time, collection counts), `data.json`, and exact saved UTF-8 journal files under
`journals/YYYY-MM-DD.md`. Markdown retains existing frontmatter and line endings;
rating-only entries have empty files and absent days have no row or file. Journal
JSON points to each file with `markdown_file` instead of duplicating raw content.

An explicit allowlist of columns exports nine source collections: lists, tasks,
focus sessions, habits, habit logs, journal metadata, daily scores, weekly
summaries, and monthly summaries. Existing primary/foreign keys and recurrence
identity remain unchanged. Tasks retain scheduling values, tags, statuses,
relationships, estimates, and ordering. Datetimes use explicit UTC `Z`, retaining
fractional precision; calendar dates and month keys remain labels. Optional nulls
and JSON types are preserved. Rubric JSON stays a string. Reviews and stored
journal metrics are snapshots; export does not recalculate live telemetry.

All table reads use one AsyncConnection with explicit SQLite `BEGIN` before the
first SELECT, followed by rollback when materialization completes. This read
snapshot remains consistent across concurrent WAL commits. Collections are
ordered by primary key. Export makes no source writes, migrations, AI, or
embedding calls. The route owns a private temporary artifact and removes it on
success, creation/serialization/response failure, or cancellation.

The entire settings table (including provider credentials and prompt overrides),
AI usage, review-job state, and search indexes/state are excluded. New source
columns require explicit format inclusion; no SQLite file is packaged. User text
is not redacted, so content can still contain secrets. UI and documentation warn
that archives contain private unencrypted data. Full SQLite backup/offline restore
remains the recovery workflow. Native packaged save verification is separate from
browser downloads and mocked native component tests.

#### Search index consistency

Journal saves, deletions, capture appends, and weekly/monthly rollups commit
source data, FTS, and vector-index state in one SQLite transaction. Index storage
errors roll back that transaction. Embedding inference is optional: if it is
unavailable, current FTS still commits, accessible old vectors are removed, and
`search_vector_state` records `pending`. Successful vector insertion records
`ready`. Pending state is written even when the extension is unavailable, so a
later startup can replace an inaccessible stale vector instead of trusting its
presence.

Startup reconciliation compares source text and kind with FTS, repairs missing,
stale, or duplicate rows, removes orphan FTS/vector/state records, and retries
pending or missing vectors when the extension is available. Existing vectors
without freshness state are regenerated once. Healthy vectors are retained.
Recovery and full reindex acquire SQLite's writer lock before reading sources;
index changes commit together or roll back together. Full reindex clears derived
indexes and state before rebuilding from current sources, including an empty
database. Both recovery paths can run keyword-only. Missing embeddings retry at
the next startup or explicit reindex; no background embedding worker is added.
`GET /api/search/status` reports extension readiness; the reindex response's
`semantic` flag reports whether the rebuilt index contains a ready vector.


### 6.4 Planned: Optional Local-First Calendar Interoperability

Calendar interoperability is roadmap work, tracked in `todo.md`; the following defines the intended boundary rather than implemented functionality.

- **Local-only by default**: SQLite remains the source of truth for local tasks and time blocks. Calendar features require no app account; Google APIs, browser OAuth, and cloud notification relays are outside scope.
- **ICS milestone first**: Export selected time blocks as iCalendar (`.ics`) events without calendar accounts, credentials, or a server. File export is a snapshot; import, read-only subscriptions, and CalDAV are separate later extensions instead of prerequisites.
- **Deferred optional CalDAV client**: After ICS export ships, optionally connect to a user-managed server using its supported password/app-password authentication. Radicale may run as a user-level service, installed and managed by the user; Journal does not bundle, install, start, or manage it. Verify server interoperability separately, including Nextcloud and Baïkal. OAuth-only server configurations are outside scope.
- **Future sync availability**: Journal synchronizes only while running. A localhost server serves clients on the same machine; other devices need a reachable server. No public callback endpoint is required.
- **Domain separation**: Calendar events and task-linked time blocks remain distinct from task deadlines, completion, and scoring. CalDAV `VTODO` task synchronization is a separate optional feature.
- **Module boundary**: Keep ICS serialization self-contained and independent of CalDAV. Any future CalDAV adapter, synchronization service, worker, and connection routes live in separate modules. Local changes commit independently of the server; persist resource links, UIDs, ETags, and queued work. Use conditional writes and explicit conflict states; use optional sync tokens with an ETag-based reconciliation fallback.
- **Future connection credentials**: Keep server credentials behind an OS credential-store interface and outside ordinary settings and data exports. Linux desktop calendar bridges and outgoing automation remain optional extensions.

---

## 7. AI Implementation Blueprint with PydanticAI

### 7.1 Model Factory: Dynamic Base URL & API Key Configuration

The AI subsystem allows switching providers on the fly (cloud Claude/OpenAI, OpenRouter, or local Ollama) by configuring `base_url` and `api_key` via environment variables (`.env`) or database settings.

Personal gateways rate-limit aggressively and often mask upstream 429s as HTTP
503s; pydantic-ai's `retries=` only covers validation/tool retries. The factory
therefore wraps every model in `ResilientModel` (spaced retries on 429/5xx,
`app/ai_factory.py`) and user-facing surfaces translate failures via
`describe_ai_error()` (rate limit / auth / unreachable). The settings
connection-test runs with `resilient=False` so misconfiguration fails fast.

```python
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.openai import OpenAIProvider

class AISettings(BaseSettings):
    AI_PROVIDER: str = "openai_compatible"  # "openai_compatible" or "anthropic"
    AI_MODEL_NAME: str = "llama3.2:3b"     # e.g., "llama3.2:3b", "gpt-4o-mini", "claude-3-5-sonnet-latest"
    AI_BASE_URL: Optional[str] = "http://localhost:11434/v1"  # Custom endpoint (Ollama, OpenRouter, Groq, vLLM)
    AI_API_KEY: Optional[str] = "ollama"   # API key (sk-... or dummy string for local Ollama)

    class Config:
        env_file = ".env"
        extra = "ignore"

def create_agent_model(settings: Optional[AISettings] = None):
    """Instantiates a model client with configurable base_url and api_key."""
    s = settings or AISettings()

    if s.AI_PROVIDER == "anthropic":
        return AnthropicModel(
            model_name=s.AI_MODEL_NAME,
            api_key=s.AI_API_KEY,
            base_url=s.AI_BASE_URL  # Supports Anthropic reverse proxies if provided
        )
    else:
        # Generic OpenAI-compatible provider: works with Ollama, OpenRouter, Groq, DeepSeek, LocalAI
        return OpenAIModel(
            model_name=s.AI_MODEL_NAME,
            provider=OpenAIProvider(
                base_url=s.AI_BASE_URL or "https://api.openai.com/v1",
                api_key=s.AI_API_KEY or "not-needed"
            )
        )
```

### 7.2 Daily Review & Scoring Agent Example

```python
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from typing import List, Optional
from dataclasses import dataclass
import datetime

# 1. Output Schemas
class RubricBreakdown(BaseModel):
    task_completion_rate: float = Field(description="Tasks completed / planned (0.0 to 1.0)")
    deep_work_hours: float = Field(description="Actual deep work hours logged")
    habit_consistency: float = Field(description="Habits completed / scheduled (0.0 to 1.0)")

class DailyReviewOutput(BaseModel):
    llm_nudge: float = Field(description="Score modifier from -10.0 to +10.0 based on subjective context", ge=-10.0, le=10.0)
    nudge_rationale: str = Field(description="Explanation for the score adjustment")
    feedback: str = Field(description="Direct, constructive feedback on the day's execution")
    key_insight: str = Field(description="One high-leverage observation or behavioral pattern identified")
    suggested_action_for_tomorrow: str = Field(description="Single most important recommendation for next day")

# 2. Agent Dependencies
@dataclass
class AgentDeps:
    today_raw_text: str
    past_6d_entries: List[dict]
    latest_weekly_summary: Optional[str]
    latest_monthly_summary: Optional[str]
    deterministic_metrics: dict

# 3. Agent Definition using dynamic model factory
model = create_agent_model()
daily_agent = Agent(
    model,
    deps_type=AgentDeps,
    result_type=DailyReviewOutput,
    system_prompt=(
        "You are an executive personal coach and productivity analyst. "
        "You analyze daily journal entries, task telemetry, and recent historical summaries. "
        "Your role is not to flatter, but to provide rigorous, actionable, empathetic analysis. "
        "You will receive computed deterministic metrics (task rate, focus hours). "
        "You may adjust the score with an LLM nudge between -10 and +10 with an explicit reason."
    )
)

@daily_agent.system_prompt
def build_context(ctx: RunContext[AgentDeps]) -> str:
    return f"""
    --- CONTEXT (BOUNDED MEMORY) ---
    Monthly Context: {ctx.deps.latest_monthly_summary or 'No prior month recorded.'}
    Weekly Context: {ctx.deps.latest_weekly_summary or 'No prior week recorded.'}
    Past 6 Days Scores & Notes: {ctx.deps.past_6d_entries}
    Deterministic Metrics Today: {ctx.deps.deterministic_metrics}

    Today's Raw Entry:
    \"\"\"{ctx.deps.today_raw_text}\"\"\"
    """
```

### 7.3 Task Decomposition Tool Example

```python
class SubtaskItem(BaseModel):
    title: str
    estimated_minutes: int
    priority: int = Field(ge=0, le=3)

class DecompositionPlan(BaseModel):
    task_breakdown: List[SubtaskItem]
    advice: str

breakdown_agent = Agent(
    'anthropic:claude-3-5-haiku-latest',
    result_type=DecompositionPlan,
    system_prompt="Decompose complex user goals into atomic, actionable steps (20-45 minutes each)."
)
```

---

## 8. Implementation Roadmap

### Phase 1: Foundation & Data Layer (Days 1–3) — `feat/backend-data-layer` ✅ (implemented on branch `feat/backend-data-layer`)
- [x] Initialize Git repo, `.gitignore`, and Python virtual environment with `uv`.
- [x] Implement SQLite schema with SQLModel / SQLAlchemy 2.0.
- [x] Build core CRUD endpoints in FastAPI for tasks, subtasks, lists, and focus sessions.
- [x] Implement deterministic scoring calculation utility.
- [x] Configure `AISettings` supporting custom `base_url` and `api_key`.

### Phase 2: Core Task UI & Natural Language Capture (Days 4–7) — `feat/task-engine-ui` ✅ (implemented on branch `feat/task-engine-ui`)
- [x] Set up Vite + React 19 + Tailwind CSS v4 + shadcn/ui.
- [x] Build Quick Add Bar with `chrono-node` for real-time natural language date/priority/tag parsing.
- [x] Implement Task List and Kanban Board views using `@dnd-kit`.
- [x] Wire TanStack Query with optimistic updates for instant check-offs.

### Phase 3: Focus Timer & TipTap Journaling (Days 8–11) — `feat/focus-tiptap-journal` ✅ (implemented on branch `feat/focus-tiptap-journal`)
- [x] Build Pomodoro / Stopwatch focus tracker with Zustand state.
- [x] Implement TipTap rich-text editor for daily journal entries.
- [x] Build "Insert Daily Activity" component to embed completed tasks and focus metrics into journal notes.
- [x] Store mood/energy ratings.

### Phase 4: AI Hierarchical Compaction & Agent Workflows (Days 12–15) — `feat/ai-compaction-agents` ✅ (implemented on branch `feat/ai-compaction-agents`)
- [x] Implement PydanticAI agents (`daily_agent`, `weekly_agent`, `monthly_agent`).
- [x] Build dynamic provider switcher supporting local Ollama (`http://localhost:11434/v1`), OpenRouter, Groq, and Claude.
- [x] Build task decomposition agent and conversational omnibar capture.
- [x] Integrate automated daily, weekly, and monthly compactions with the backend lifecycle; retire legacy systemd HTTP timers (FIX-05).

### Phase 5: Search, Polish & Desktop Packaging (Days 16–18) — `feat/rag-desktop-polish` ✅ (implemented on branch `feat/rag-desktop-polish`)
- [x] Integrate `sqlite-vec` or `fastembed` for hybrid semantic and keyword search.
- [x] Wrap frontend in **Tauri v2** for lightweight Linux desktop tray and system-wide hotkeys.
- [x] Implement dark-mode glass styling and fluid Framer Motion transitions.

### Phase 6: AI UX — RAG chat, streaming, editor assists, model routing — `feat/ai-ux` ✅
- [x] **Ask my second brain** (§6.3.5): `/api/agents/ask/stream` retrieves via hybrid search (6 sources, 1200 chars each) and streams a cited answer (`[n]` markers) over SSE; Second Brain UI has Ask/Search modes, clickable citations and bounded client-held chat history (last 6 turns × 1000 chars).
- [x] **Streaming everywhere** (§6.3.1/§6.3.3): SSE variants for daily review (`rollup/daily/stream`, persists the final partial — upsert) and briefing; SSE framing in `app/sse.py`, consumed via plain fetch + ReadableStream (`frontend/src/lib/stream.ts`). Event protocol: `partial` → `done` / `error`.
- [x] **Editor AI assists**: slash-menu actions (improve / continue / summarize whole entry) stream into an accept/discard preview panel above the day score; apply = `setContent` → debounced save.
- [x] **Model routing + prompts + usage**: fast tier `ai_fast_model_name` (capture/briefing/Q&A/assists), per-agent system-prompt overrides (`prompt_*` app_settings, `GET/PUT /api/settings/ai/prompts`), token/duration telemetry (`ai_usage` table, `GET /api/settings/ai/usage?days=`).
- [x] **Gateway resilience**: `ResilientModel` retries 429/5xx and connection errors with spaced backoff (Antigravity masks upstream 429s as 503s); `describe_ai_error()` renders human-readable failures in the UI; connection test uses `resilient=False`.

---

## 9. Recommended Development Commands & Dependencies

### Backend (`requirements.txt` / `pyproject.toml`)
```toml
[project]
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlmodel>=0.0.22",
    "pydantic>=2.9.0",
    "pydantic-ai>=0.0.14",
    "sqlite-vec>=0.1.1",
    "litellm>=1.49.0",
    "fastembed>=0.3.0",
    "python-multipart>=0.0.9"
]
```

### Frontend (`package.json`)
```json
{
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "@tanstack/react-query": "^5.59.0",
    "zustand": "^5.0.0",
    "@tiptap/react": "^2.8.0",
    "@tiptap/starter-kit": "^2.8.0",
    "@tiptap/extension-task-list": "^2.8.0",
    "@tiptap/extension-task-item": "^2.8.0",
    "@dnd-kit/core": "^6.1.0",
    "@dnd-kit/sortable": "^8.0.0",
    "chrono-node": "^2.7.5",
    "lucide-react": "^0.453.0",
    "framer-motion": "^11.11.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.4"
  }
}
```

---

## 10. Git Workflow, Branching Strategy & Project Hygiene

To ensure clean development, isolation of complex AI/frontend features, and easy rollback, the project enforces a strict Git branching workflow.

### 10.1 Branch Structure

* **`main`**: The single source of truth. Always deployable and buildable. Direct commits to `main` are prohibited except for initial project bootstrap and docs.
* **`feat/<feature-name>`**: Dedicated branch for every feature or architectural phase.
  * `feat/backend-data-layer`: FastAPI models, SQLite schema, CRUD routes.
  * `feat/task-engine-ui`: Quick-add bar, task list, Kanban views, optimistic UI.
  * `feat/focus-tiptap-journal`: TipTap block editor, daily activity embeds, focus clock.
  * `feat/ai-compaction-agents`: Daily, weekly, monthly PydanticAI rollups & systemd timers.
  * `feat/ai-provider-config`: UI & API settings for custom `base_url` and `api_key`.
  * `feat/rag-desktop-polish`: sqlite-vec search, Tauri v2 desktop integration.
* **`fix/<bug-name>`**: Targeted fixes for unexpected behavior or edge-case regressions.
* **`refactor/<component>`**: Non-functional refactoring or performance optimization.

### 10.2 Feature Branch Lifecycle Workflow

For every new feature, follow this standard cycle:

```bash
# 1. Ensure main is clean and up to date
git checkout main
git pull origin main

# 2. Branch off into an isolated feature branch
git checkout -b feat/task-engine-ui

# 3. Work incrementally with atomic, descriptive Conventional Commits
git add <files>
git commit -m "feat(tasks): add chrono-node inline NLP parsing to quick-add bar"

# 4. Run tests and linting before merge
pytest tests/
npm run lint

# 5. Merge feature back into main (using --no-ff or PR to preserve history)
git checkout main
git merge --no-ff feat/task-engine-ui -m "merge: feat/task-engine-ui into main"

# 6. Clean up the merged branch
git branch -d feat/task-engine-ui
```

### 10.2.1 Pull-request checks

Branch pushes and pull requests run `.github/workflows/ci.yml` independently of
release tags. Its required-check candidates are `Backend tests`, `Frontend test`,
`Frontend build`, and `Frontend lint`. Backend checks use Python 3.12 and the uv
lockfile; frontend checks use Node 24 and `npm ci`. The frontend matrix runs all
three checks even if one fails. Tests retain isolated SQLite fixtures and stubbed
AI/embedding calls; CI disables scheduled reviews and Hugging Face downloads.
A repository administrator must require these four checks in the target branch's
ruleset or branch protection to enforce merge blocking. The release workflow
calls this workflow through `workflow_call` and waits for all four checks.

### 10.3 Commit Message Convention (Conventional Commits)

Use single-line, standardized commit messages:
* `feat(scope): add new feature` (e.g., `feat(ai): support custom base_url for Ollama`)
* `fix(scope): fix bug or calculation error` (e.g., `fix(scoring): prevent division by zero when planned tasks is 0`)
* `refactor(scope): internal restructuring without changing behavior` (e.g., `refactor(db): extract session dependency into separate module`)
* `docs(scope): update documentation or plans` (e.g., `docs(plan): update agent base_url architecture`)
* `chore(scope): build, dependency or tooling changes` (e.g., `chore(deps): bump pydantic-ai to latest version`)

### 10.4 Repository Hygiene & `.gitignore` Blueprint

Create a root `.gitignore` from day one to guarantee secrets, local databases, and temporary files never touch version control:

```gitignore
# Python & Virtual Environments
__pycache__/
*.py[cod]
*$py.class
.venv/
env/
build/
dist/
*.egg-info/

# SQLite & Data Stores
*.db
*.sqlite
*.sqlite3
data/
*.wal

# Node & Frontend
node_modules/
.next/
dist/
.vite/
npm-debug.log*

# Tauri & Native Build Artifacts
src-tauri/target/

# Environment Variables & Secrets (CRITICAL)
.env
.env.local
.env.*.local
*.pem
*.key

# OS & IDE Metadata
.DS_Store
Thumbs.db
.idea/
.vscode/
*.swp
*.swo
```

### 10.5 Releases & Distribution (Linux)

Releases are cut by CI (`.github/workflows/release.yml`), not by local builds —
the vendored sysroot in `.tauri-sysroot/` stays a no-root fallback for dev only:

1. Bump `version` in `frontend/src-tauri/tauri.conf.json` (and `src-tauri/Cargo.toml` to match).
2. Commit, then tag: `git tag app-v0.1.1 && git push origin app-v0.1.1`. The workflow
   fails early if the tag doesn't match the config version.
3. The release workflow first calls the branch CI workflow and requires backend
   tests plus frontend tests, build, and lint to pass. The bundle job then builds
   inside an **`ubuntu:22.04` container** on the current runner
   (the 22.04 runner label retired Sept 2026): glibc floor stays at 2.35 and
   old binutils avoids the `.relr.dyn`/old-strip breakage. Python 3.12, pinned uv,
   and the locked `packaging` dependency group build the PyInstaller sidecar.
   Before Tauri runs, `backend/scripts/smoke_sidecar.py` launches that exact
   executable on an OS-assigned loopback port. Health and linked list/task CRUD
   must pass against an isolated temporary database. The harness isolates its
   working directory and home/cache paths, disables scheduling and model
   downloads, and cleans up the process and temporary files on success or
   failure. Journal writes are excluded because indexing may initialize an
   embedding model even for rating-only entries; no AI endpoint is called.
   **tauri-action was removed**; the tag path runs
   the same `npm run tauri build` as manual branch builds, then creates the
   draft release and uploads bundles via the REST API directly (reusing and
   cleaning stale same-tag drafts and assets). No upload step runs after a
   failed check, sidecar build, smoke test, or Tauri build. Manual runs exercise
   the same gates and upload build artifacts instead of creating releases.
4. Review and publish the draft on GitHub Releases. Manual administrator
   publication or uploads to an existing draft remain outside workflow gating.

RPM packages must declare their runtime libs explicitly via
`bundle.linux.rpm.depends` (`webkit2gtk4.1`, `gtk3`,
`libayatana-appindicator-gtk3` — Fedora names): unlike deb, the bundler adds no
library deps by default, so an RPM without them installs fine and then fails to
start. The tray and global-shortcut setup in `src-tauri/src/lib.rs` is
deliberately non-fatal (`log::warn!` instead of `?`) so a missing desktop
integration never prevents launch.

### 10.6 Desktop Sidecar (packaged backend)

The desktop build bundles the FastAPI backend as a PyInstaller **one-dir**
sidecar (fast startup; onefile would re-extract ~300 MB every launch):

- **Build order matters** — `./build-sidecar.sh` (or the CI step) must run
  BEFORE `npm run tauri build`: `tauri.conf.json` declares
  `bundle.resources: ["binaries/meditations-backend"]` and bundling fails if
  the directory is absent.
- **Runtime contract** (`src-tauri/src/lib.rs`): the shell binds `127.0.0.1:0`
  to grab a free port (small TOCTOU race accepted; uvicorn fails loudly),
  spawns the sidecar **from the resource dir**
  (`resource_dir()/binaries/meditations-backend/meditations-backend` — NOT
  `shell().sidecar()`, which resolves next to the executable and can never
  see a resources-bundled one-dir tree) with `MEDITATIONS_PORT` +
  `JOURNAL_DB_PATH` (`<app_data_dir>/journal.db`, i.e.
  `~/.local/share/dev.journal.app/`), polls the TCP port for ≤15 s, drains
  stdout/stderr into the log, and kills the child on `RunEvent::Exit`.
  The port is published to the UI only while the child is alive: a failed
  spawn or a `Terminated` event flips it to `None` and the frontend falls
  back to the dev default. `MEDITATIONS_LEGACY_DB=<path>` triggers a one-time
  copy import when the target DB doesn't exist yet; the import is SKIPPED if
  `-wal`/`-shm` sidecars exist (uncheckpointed writes). The sidecar itself
  runs a parent watchdog (exits when `os.getppid()` changes) so a SIGKILLed
  shell never orphans it.
- **Frontend port bridge** (`lib/backend-base.ts`): `resolveBackendBase()`
  runs before React mounts, invokes the `backend_port` command, and sets
  `window.__BACKEND_BASE__`; `api/client.ts` and `lib/stream.ts` call
  `backendBase()` at request time — never at module-load time (imports
  evaluate before the port resolution finishes; this bit us once).
- **Dev mode**: `cfg!(dev)` skips the sidecar entirely; the app falls back to
  `VITE_API_URL` / `127.0.0.1:8000` (the `./dev.sh` backend).
- **PyInstaller traps**: `httpx` is a RUNTIME dep (pydantic-ai model calls) —
  never exclude it; `sqlalchemy.dialects.sqlite.aiosqlite` resolves via
  entry point so it needs an explicit hiddenimport; `sqlite_vec`'s `vec0.so`
  ships as package data (`collect_data_files`); onnxruntime needs
  `collect_dynamic_libs`.
- **Frozen-runtime traps** (both crashed the packaged app on real machines):
  pydantic plugins (logfire, via pydantic-ai) call `inspect.getsource()` —
  impossible in frozen apps, so `sidecar_main.py` sets
  `PYDANTIC_DISABLE_PLUGINS=1` before any import; and deps reading their
  version via `importlib.metadata` (genai_prices, …) need their dist-info
  shipped — the spec copies ALL distributions' metadata. PyInstaller's
  `build/` analysis cache silently ignores spec data changes on rebuild —
  `build-sidecar.sh` deletes it first.
