# Journal architecture and implementation record

## Document status and ownership

This is the authoritative architecture reference for the current worktree, including
implemented changes that have not yet been committed or released. It does not
certify that an installed package contains those changes.

- Sections 2–6 and 7 describe shipped source contracts and their implementation
  locations. Explicitly labeled proposals and deferred items are outside that scope.
- Section 1 records product goals, not performance guarantees. Section 5's SQL is
  a partial schema illustration; ordered migrations and models define the full schema.
- Section 8 preserves the historical delivery roadmap, not the active backlog.
- Sections 9–10 describe current development, verification, and release procedures.
- [README.md](README.md) is the user/setup guide; [backend/README.md](backend/README.md)
  documents API and recovery operations. Dependency manifests and lockfiles define
  supported versions instead of copied dependency lists in this document.
- The local [feature backlog](features/todo.md) records implementation and QA
  evidence. The local [review plan](features/plan.md) preserves findings and future
  proposals; it is not another shipped-architecture specification. These ignored
  files may be absent from a fresh clone. The former root `todo.md` is absent and
  is not required to use the architecture reference.

Verification results are dated evidence, not permanent test-count guarantees.
Native development-shell, extracted-package, host-installation, physical-input,
assistive-technology, and real-provider acceptance are separate scopes; passing
unit tests or a sidecar smoke test does not establish them.

---

## 1. Executive Summary & Product Vision

This project is a modern, unified personal operating system combining:
1. **TickTick-grade Task Management**: Fast natural language capture, hierarchical subtasks, priority matrices, tags/lists, focus/Pomodoro tracking, and fluid Kanban/Calendar views.
2. **Reflective Long-Form Journaling**: TipTap-based rich block/markdown editor with automated daily activity embeds (tasks finished, focus hours logged, habits kept) and quantified mood/energy tracking.
3. **Hierarchical AI Agent System**: A proactive "Life Coach & Chief of Staff" agent that solves the LLM memory blowup problem via **hierarchical compaction**, scores daily performance objectively with deterministic math + qualitative feedback, breaks down complex tasks, and offers conversational capture and semantic search over historical entries.

### Core Philosophy
* **Frictionless Capture**: Task input must take under 3 seconds using inline shorthand (`buy milk tomorrow 5pm !1 #personal`).
* **Bounded Context Memory ($O(1)$ Token Growth)**: Raw journal entries are never re-read forever. Older days collapse into weekly summaries; weeks collapse into monthly reviews. The agent's token budget remains constant whether on Day 10 or Year 5.
* **Deterministic Scoring Over Hallucinated Scores**: Productivity scores are calculated mathematically from structured telemetry (completion rate, deep-work hours, habit completion), while the LLM acts as an analytical mentor providing qualitative feedback and trend diagnosis.
* **Local-First & Privacy-Focused**: Powered by SQLite (WAL mode) with optional local vector embeddings and local LLM support (Ollama), running seamlessly on EndeavourOS / Linux with minimal resource footprint.

---

## 2. Implemented technology stack

### 2.1 Technology matrix

| Layer | Implemented choice | Source of truth |
|---|---|---|
| Frontend | React 19, Vite 8, TypeScript, Tauri v2 | `frontend/package.json`, `frontend/src-tauri/Cargo.toml` |
| Styling and UI | Tailwind CSS v4, shadcn v4 components using Base UI, Framer Motion, Lucide | `frontend/package.json`, `frontend/src/components/ui/` |
| Rich-text editor | TipTap v3, StarterKit, task lists from `@tiptap/extension-list`, `tiptap-markdown` | `frontend/src/components/journal/extensions.ts` |
| Date parsing | chrono-node 2.x with local parsing corrections | `frontend/src/lib/parsing.ts` |
| Drag and drop | dnd-kit core and sortable | `frontend/package.json` |
| State and fetching | TanStack Query v5 and Zustand | `frontend/src/hooks/` domain modules (`api.ts` compatibility exports), `frontend/src/stores/` |
| Backend | Python 3.12+, FastAPI, Pydantic v2, uvicorn | `backend/pyproject.toml`, `backend/uv.lock` |
| Database | SQLite WAL, SQLModel and async SQLAlchemy/aiosqlite | `backend/app/db.py`, `backend/app/models.py`, `backend/app/migrations/` |
| Search | SQLite FTS5, sqlite-vec, optional fastembed inference on a serialized worker | `backend/app/search.py`, `backend/app/embedding_worker.py` |
| AI | PydanticAI v2 API, OpenAI-compatible or Anthropic provider objects, resilient model wrapper | `backend/app/ai_factory.py`, `backend/uv.lock` |
| Scheduling | Backend lifecycle review worker with database-local UTC catch-up | `backend/app/review_scheduler.py` |

Next.js, Radix UI, and LiteLLM were considered in the initial proposal but are
not the implemented stack. Ollama is the default local AI endpoint; hosted
providers are optional configuration. Model availability and provider-specific
behavior require separate verification.

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
   - Environment defaults: `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL_NAME` (or `backend/.env` when running from `backend/`).
   - Settings overrides: persisted `app_settings` values take precedence on request paths; changes do not require a backend restart.
3. **PydanticAI Dynamic Model Loader**:
   - `create_agent_model()` constructs `OpenAIChatModel` with `OpenAIProvider`, or `AnthropicModel` with `AnthropicProvider`. `ResilientModel` retries transient failures; it does not automatically switch providers. Request paths load database settings before model construction.

### 3.3 The Hierarchical Compaction Engine

The core problem of AI journaling is context bloat. As time progresses, feeding hundreds of raw daily entries into an LLM exceeds context limits and increases costs.

```
[ Day 1 .. Day 7 Raw Entries ] ──► Daily Agent (Reads today + last 6d + last week summary)
             │
             ▼ (Closed UTC Week)
  [ Weekly Summary Compacted ] ──► Weekly Agent (Reads 7 daily scores + last 4 weekly summaries)
             │
             ▼ (Closed UTC Month)
 [ Monthly Review Compacted ]  ──► Monthly Agent (Reads 4 weekly summaries + last 3 monthly summaries)
```

#### Bounded Input Constraints:
* **Daily Agent Run** (Scheduled after the UTC day closes, or requested manually):
  * Inputs: Today's raw text + deterministic metrics + past 6 days' raw text + latest 1 weekly summary + latest 1 monthly summary.
  * Maximum token footprint: ~4,000 tokens ($O(1)$).
  * Output: Qualitative feedback, identified cognitive blindspots, suggested wins/misses, and nudges.
* **Weekly Agent Run** (Scheduled after Monday 00:00 UTC for the closed week):
  * Inputs: 7 daily scores & structured metadata (tasks done, deep-work hours) + last 4 weekly summaries + latest monthly summary whose month is strictly before the requested week's start month. Manual reruns and scheduler catch-up use the same target-period boundary, not the current date; missing eligible monthly context is omitted. A week crossing a month/year boundary belongs to its start month, so its own parent monthly summary cannot feed back into regeneration. **Raw daily journal text is never read again.**
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
                                    │ HTTP / REST / SSE
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

The SQL below illustrates core tables instead of providing a complete bootstrap script.
Use the migrations and models for exact DDL, indexes, constraints, and auxiliary tables.

Startup applies the ordered migrations in `backend/app/migrations/` before
search initialization, requests, or startup jobs. `PRAGMA user_version` records
the schema version: v1 is the frozen pre-identity baseline; v2 adds task
recurrence identity; v3 adds `search_vector_state` (`doc_id` primary key and
`state`, either `pending` or `ready`). v4 adds the durable review-job ledger;
v5 adds indexed `tasks.deadline_date` and an exclusive deadline-storage constraint;
v6 adds task-owned timed `time_blocks` with an interval CHECK and cascading task FK;
v7 rebuilds blocks with exclusive timed/all-day shapes and IANA timezone metadata.
v8 adds calendar connections/links; v9 adds credential bookkeeping; v10 adds
immutable calendar dispatches and acknowledgment actions; v11 adds transactional
calendar source-capture triggers; v12 adds sync acknowledgment times and explicit
link selection state; v13 adds independent import sources, original upload snapshots,
and opaque event identities. v14 adds the webhook outbox; v15 adds calendar inbound
reconciliation. v16 adds independent task importance and urgency with non-null
`unassigned` defaults and allowed-state CHECK constraints. v17 repairs historical
JSON-null task tags to empty arrays. Fresh installations run all seventeen migrations.
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
    importance TEXT NOT NULL DEFAULT 'unassigned'
        CHECK (importance IN ('unassigned', 'important', 'not_important')),
    urgency TEXT NOT NULL DEFAULT 'unassigned'
        CHECK (urgency IN ('unassigned', 'urgent', 'not_urgent')),
    status TEXT DEFAULT 'todo', -- 'todo', 'in_progress', 'completed', 'canceled'
    due_date DATETIME, -- compatibility storage for timed deadlines; naive UTC
    deadline_date DATE, -- date-only deadline label; no timezone conversion
    estimated_minutes INTEGER,
    actual_minutes INTEGER DEFAULT 0,
    recurrence_rule TEXT, -- e.g. 'FREQ=DAILY;INTERVAL=1' or 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR'
    recurrence_series_id TEXT,
    recurrence_occurrence INTEGER, -- zero-based identity; independent of due_date
    tags TEXT, -- JSON array of tags: ["work", "dev"]
    order_index REAL NOT NULL DEFAULT 0.0,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_task_deadline_exclusive CHECK (due_date IS NULL OR deadline_date IS NULL)
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

### 6.0 Frontend section and task-view loading (PERF-01, REV-13)

`App.tsx` keeps the List task view and shared shell eager. Matrix, Journal,
Insights, Second Brain, and Settings use module-scoped React lazy imports;
TipTap and its editor dependencies load only when Journal is selected.
Calendar and Board load on first selection inside `TasksView`. Shared UI and
API modules remain available to both the initial bundle and deferred sections.
No manual vendor-chunk rules or additional dependencies are required.

Within Tasks, a separate Suspense boundary keyed by task view owns only the
view content, inside the API query boundary. Header, filter, and quick-add
controls retain their identity and remain usable while a view loads. The
existing Board or task skeleton supplies loading feedback; API loading/error
states take precedence and do not request a view module. Resolving an abandoned
view import does not navigate back to it. Loaded views receive current tasks,
scope, and search, and modules are reused on subsequent visits. Calendar source
opt-in still resets on a fresh Calendar mount, rather than on mode changes.

A Suspense boundary keyed by section owns only the central content. Its
fallback has a busy main landmark and a section-specific loading status;
the sidebar, focus timer, and command palette remain mounted and usable.
Leaving Journal still unmounts it immediately and flushes its frozen pending
save, including when the destination module has not loaded. A late module
resolution cannot change the selected section. Cached modules do not reload
on revisits; section component state retains its existing unmount semantics.
Persisted initial section selection uses the same loading path.

PERF-01's historical build reduced production initial JavaScript from
1,399,489 to 817,780 bytes minified (41.6%). REV-13 compares the later worktree
before/after task-view splitting: 884,536 to 773,227 bytes minified (12.6%),
including every transitive static import; gzip totals are 276,348 and 246,862
bytes (10.7%). The main file alone falls from about 749 KB to 536 KB; Journal
remains deferred at about 597 KB. These are profiling builds with identical
manifest/sourcemap flags, rather than comparisons against the older baseline.
Generate the build graph with `npm run build -- --manifest`; inspect
`dist/.vite/manifest.json` and include all recursive `imports` when comparing
initial bytes. The entry and Journal still exceed Vite's 500 KB advisory
threshold; it is not suppressed.

Five context-cold local Chromium samples with 200 synthetic tasks and a
100-paragraph journal show median startup of 708 ms before and 687 ms after;
that small difference is insufficient to claim a reliable runtime speedup.
First Board/Calendar visits trade startup bytes for deferred loading: medians
increase from 281/180 ms to 497/448 ms in a fixed Board-then-Calendar workflow;
Calendar may reuse dependencies from Board. Journal opening remains 480 ms.
Measurements include automation overhead and use unthrottled local preview,
rather than representative hardware or native WebView performance. No warm
switch, field Core Web Vitals, or low-end-device improvement is established.
The benefit is reduced initial payload, with an explicit first-use latency cost.

### 6.0.1 Navigation, section widths and calendar source controls (NAV-01 / LAY-01 / CAL-01)

Desktop navigation has a persisted `expanded | collapsed` preference in the
`journal-ui` store; older preferences default to expanded. The collapsed state
is an icon rail with the app icon, named destinations and a Lists flyout.
The app icon remains visible in both desktop sidebar states. List creation uses
an explicit form; list deletion requires confirmation and keeps tasks. Settings
is a footer outside the scrolling navigation region. Below 768px, navigation
uses a modal drawer without changing the desktop preference. Closing the drawer
restores its trigger; crossing the breakpoint transfers navigation focus to a
visible control. Changing sidebar width does not remount the selected section.

`SectionLayout` owns the section scrollbar and provides explicit `workspace`
(90rem maximum) and `reading` (80ch maximum) variants. Journal, Insights and
Second Brain use workspace width, including lazy-loading and error states.
Container queries adapt charts/results to available content width. Journal
keeps its editor near 82ch, with ratings/review/assist alongside on wide
containers and below on smaller ones; its calendar uses the workspace width.
Second Brain answer prose stays near 72ch. Its Ask/Search input has an explicit
mode-specific accessible name and retains the shared visible keyboard-focus ring.
Journal citations and search hits remain navigation buttons; weekly/monthly
rollup sources render as descriptive text instead of inert controls.
Insights keeps its period controls mounted through query loading/error states,
exposes the selected period with `aria-pressed`, and names each chart by metric
and period. These layout changes preserve the existing frozen-save and empty-day
contracts.

Insights journal current/best streaks use all qualifying entry dates through the
current UTC date, independently of the selected 14–90-day chart period. Text,
mood-only and energy-only entries qualify, matching journal saves and calendar
dots; whitespace-only unrated rows and future dates do not. Current streaks may
end today or yesterday. Daily-habit current streaks likewise use all completed
log dates through today. Habit `rate_30` remains completed days in the inclusive
UTC interval `[today - 29 days, today]`, divided by 30; incomplete and future
logs are excluded. Neither streak query imposes a historical day limit. Journal
history is streamed as participation fields, while chart entry data stays bound
to the selected period. This does not change score formulas, saved reviews or
bounded AI context.

#### Score display and reflection-first preference (REV-19)

Settings → Appearance → **Score display** offers `scored | reflection`, persisted
locally in the `journal-ui` store alongside theme and sidebar preferences.
Existing preferences default to `scored`; invalid stored values normalize to that
default, including the legacy Matrix-view migration. The preference survives
navigation and reload; it is device-local instead of a server preference or an
export/backup field. Settings card pairs use content-container breakpoints instead
of viewport breakpoints so the expanded sidebar does not force narrow two-column
controls; the theme trigger shrinks within its card.

`components/score-display.tsx` owns the preference control and shared scoring
explanation. Full task, focus and habit components contribute 40 + 35 + 15 = 90
points before the bounded ±10 AI nudge; the final score is clamped to 0–100.
Unscheduled habits and a disabled focus target receive their full components;
zero completed tasks yield zero task points. No scoring or telemetry calculation
changes with the display preference.

Journal's day score remains a live recalculation from current activity and the
current focus target, plus the latest saved AI nudge when present. Its separate
saved review value is a snapshot replaced only when the review is rerun. Insights
uses saved daily review snapshots where available and live deterministic scores
for other days; seven-day averages aggregate those same values. Weekly/monthly
score trends are saved rollup snapshots instead of live recalculations. Both
surfaces explain this distinction rather than implying all displayed scores are
current or all are frozen.

Reflection-first removes structured final/saved scores, nudges, scoring
explanations, daily-score charts, score averages and score-derived rollup trends
from the rendered Journal/Insights UI and accessibility tree. The Journal card
becomes **Day reflection**. The daily-review completion toast checks the current
preference at completion, including a preference changed during streaming, and
omits its numeric score in reflection-first mode. Mood/energy ratings, focus
hours/targets, task and habit counts/rates, streaks, review progress/errors,
recommendation actions and narrative text remain available. User/AI-authored
prose, search excerpts and citations are left verbatim even if they mention
numbers. This is a presentation boundary, not numeric-text filtering. Requests,
review execution, score storage, exports, search and bounded AI context are
unchanged; reflection-first does not disable scoring or AI reviews.

The task calendar presents a closed-by-default **Calendar sources** disclosure
with a compact selected-source/error/stale summary. Imported/live query owners
remain mounted outside its visibility boundary: closing controls preserves
selection, polling and visible appointments. Each Calendar mount starts with
both overlays hidden; range navigation and implemented calendar-mode switches preserve explicit
selections. Setup, authentication and sync management remain in Settings. External
events remain read-only, use independent query families and do not affect task
filters or scores. All six calendar modes share this source-selection contract.

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
   - **Kanban Board**: Drag-and-drop between statuses (`To Do`, `In Progress`, `Done`). The selected list or smart scope and title/tag search filter cards through the shared task selector. All and list scopes include their matching completed tasks in Done; Today (including overdue), Overdue and Upcoming show matching active tasks only; Completed shows Done only. Canceled tasks and subtasks are excluded. The Done column displays at most 30 matching cards after scope/search filtering and reports the remaining count. Drag ordering uses only displayed cards in the destination column; completion uses the shared task mutation and leaves list membership unchanged. `lib/board.ts` owns Board selection, while List/Calendar/Matrix retain their existing completed-task policy.
   - **Interactive Calendar**: Month uses a six-week Monday-start grid; Agenda groups 14 local calendar days with separate all-day and timed items. Week and configurable Multi-Day use a shared time grid with separate all-day items and due-time flags. Drag between days or use explicit date actions to reschedule deadlines. Task-linked work blocks render independently with actual timed ranges or all-day labels; moving a block leaves its task deadline unchanged.
3. **Integrated Focus Engine (Pomodoro & Stopwatch)**:
   - Floating or full-screen focus timer linked to the active task.
   - Automatically writes finished session durations into `focus_sessions` and task `actual_minutes`.

#### Bulk task organization (features/REV-18)

List, Board, and the independent Matrix section share a view-local bulk-selection
provider and toolbar. **Select tasks** exposes selection checkboxes separately
from completion. Tab and Space operate the native checkboxes; Escape exits when
idle. Selection is unpersisted and resets on view, section, scope, or filter
navigation. Navigation during a batch stops unsent requests and shows a notice;
an already submitted update still settles through the canonical mutation hook.
Calendar and external events are outside bulk selection.

**Select all visible** uses each rendered projection: List respects its 20
completed-root cap and reveals immediate scoped subtasks during selection;
Board respects its 30 Done-card cap and excludes subtasks; Matrix retains its
active-task policy. Parents and children are selected independently. Temporary
optimistic task IDs are ineligible. Shared pure List sections and Board columns
keep rendering and selection boundaries consistent.

Bulk actions assign a list (including No list), change status, or add/remove one
tag. Each batch requires an inline confirmation; completing recurring tasks
warns about successor creation. There is no automatic undo, since reopening an
occurrence cannot retract a spawned successor or integration delivery. Existing
server completion, recurrence, subtask, telemetry, and integration rules apply.

Each task goes through the canonical optimistic update hook with independent
rollback and invalidation. Confirmed target IDs are frozen; new successors are
outside the batch. Tag edits use the current task cache. Successes remain saved;
named failures can be reviewed and retried independently without replaying
successful completions. Selection and actions are locked while applying. Tasks
no longer available in the current view are excluded from new edits. No endpoint,
schema, dependency, AI context, score formula, or external-calendar ownership
contract changes.

#### Partial-update validation (features/REV-01)

Task PATCH requests distinguish omission from explicit null: omitted fields stay
unchanged; explicit null for `title`, `priority`, `status`, or `tags` returns 422
before persistence. Nullable fields remain clearable, and `tags: []` is valid.
List PATCH likewise rejects null `name`, `color`, and `is_favorite`, while allowing
`icon` to be cleared. Settings null overrides retain their existing reset semantics.
Schema v17 repairs historical JSON-null task tags to `[]`; SQL `NOT NULL` alone
cannot reject JSON null. The migration preserves other task fields and timestamps,
and uses the existing transactional migration and pre-upgrade checkpoint path.

#### Task classification (features/MAT-01)

Tasks store independent `importance` (`unassigned | important | not_important`)
and `urgency` (`unassigned | urgent | not_urgent`). Both default to `unassigned`
for existing and ordinary new tasks, including AI capture/decomposition. No
classification is inferred from priority, dates, overdue status or AI output.
Create/PATCH reject null and unknown classification values; PATCH omission leaves
a dimension unchanged, and explicit `unassigned` resets only that dimension.
Classification edits leave priority, deadlines, completion and scoring unchanged.

Recurring successors copy both dimensions from the completed occurrence; subtasks
have their own classifications and do not inherit parent edits. The frontend
uses the canonical tasks cache and its concurrent optimistic replay/rollback
contract; temporary creations carry explicit defaults. Portable task JSON exports
include both fields. SQLite backups preserve them; older restored databases gain
`unassigned` values through v16. Portable JSON remains export-only; ICS import and
work-block export do not assign classification. The Matrix UI uses this contract as
described below.

#### Eisenhower matrix (features/MAT-02)

Matrix is a persisted top-level section, separate from Tasks, available from
the sidebar (including the collapsed rail and mobile drawer) and command menu.
Tasks offers only List, Board and Calendar; entering Matrix leaves the saved
task view and scope unchanged, so returning to Tasks restores both. Matrix
shows all active tasks independently of the selected Tasks scope and uses the
shared title/tag filter. Its header has no Tasks view switcher.
`matrix-section.tsx` and `tasks-view.tsx` own their sections;
`task-query-boundary.tsx` shares loading, error and retry behavior over the
canonical tasks cache. Persisted legacy `view: matrix` preferences migrate to
the Matrix section with List as the Tasks default, retaining other section
selections when Matrix was not visible. `lib/eisenhower.ts` owns pure classification
mapping and deterministic ordering. It reuses the shared title/tag selector with
an All tasks scope that excludes completed/canceled tasks. Matching subtasks appear independently once,
with parent context, instead of being recursively repeated beneath parents.

The desktop grid orders Urgent & important, Not urgent & important, Urgent & not
important, then Not urgent & not important. Narrow windows use a labeled vertical
stack. A separate Unclassified tray holds tasks with either dimension unassigned;
partial states remain visible and can be completed independently or reset.
The four quadrants use distinct red, blue, amber and green surfaces with
high-contrast matching text and borders in light and dark themes; Unclassified
remains neutral. Labels communicate classification independently of color.

Dedicated dnd-kit pointer handles and native Move to quadrant selectors submit
both classification dimensions atomically through the existing task update hook.
Moves do not change priority, deadlines, status, list membership or ordering. The
canonical tasks cache provides optimistic placement, concurrent replay and scoped
rollback. Move feedback is per task; different tasks settle independently, and a
pending move blocks a second classification edit on that task. Keyboard focus
returns after final placement or rollback unless the person moved to another
control. Existing TaskItem menus/completion remain shared and visible on touch.

Each zone has a task-creation form with explicit classification; Unclassified
creates both dimensions unassigned. Matrix-created tasks do not inherit the
Tasks section's selected list or scope. New tasks appear when they match the
current search. Failed creates retain their draft;
success does not clear a different draft typed while the request was pending.
Matrix shares the task query loading/error/retry boundary and adds empty,
pending-move and failed-move feedback. No dependency or backend contract changed.

#### Calendar display modes (features/CAL-02, CAL-03, CAL-04)

`CalendarMode` is separate from the Tasks List/Board/Calendar view. Month is
the default for older preferences; Year, Month, Week, Agenda, Multi-Day and Multi-Week
are selectable and persisted in `journal-ui`. Matrix is
a separate section instead of a task view or calendar mode.

`calendar-view.tsx` orchestrates scoped tasks, mutations, source owners and day
details. Dedicated `components/calendar/` modules own Year, Month, Agenda, Multi-Week,
shared day cells and time grids, explicit time-edit forms and toolbar; `lib/calendar-range.ts` centralizes local calendar-day ranges and
navigation. Month exports its calendar month, excluding adjacent padding cells;
Agenda displays and exports the 14-day window starting at the anchor. Previous
and next preserve the anchor's day where possible (clamping shorter months).
Mode changes retain the anchor date, task scope/search and selected sources.
Month keeps its seven-column grid at a minimum readable width inside a named,
keyboard-focusable horizontal scroll region. Narrow windows scroll the calendar
canvas instead of reducing event-title space to zero; section vertical scrolling
and day details remain independent. Day-detail dialogs fit within the dynamic
viewport with a 1rem margin; their item/edit list owns the remaining scroll space
so the heading, close control and new-task field remain reachable at browser zoom.

`lib/calendar-projection.ts` preserves distinct deadline, local-block,
imported-event and live-event identities and editability. Source intervals remain
authoritative, including floating clocks and exclusive all-day ends; unplaced
source records stay in labeled source details. Agenda distinguishes item kinds,
all-day items and deterministic timed ordering. Undated tasks have no calendar
placement but remain available in ordinary task views. Export includes only local
work blocks belonging to the filtered tasks and overlapping the displayed range;
selected blocks export their complete intervals, never external appointments.

Week spans Monday through Sunday. Multi-Day starts at the shared anchor and
initially spans three days, with an explicit 2–7-day selector retained within the
Calendar mount. Previous/next moves seven days or the selected day count using
calendar-date arithmetic. Both export the displayed range and retain source,
scope and search selections across mode changes.

Year displays twelve responsive Monday-start mini-months using their actual
4/5/6-week rows. Day shading represents eligible visible item density (1, 2–3,
4+), rather than scores; a spanning interval counts on each overlapping day.
Accessible day labels and shared day details expose exact total and per-kind
counts. Today and the anchor date have distinct states. Each mini-month has one
roving day tab stop with arrow navigation; Enter/Space use native button
activation to open details, updating the shared anchor. Month headings drill down
to Month, preserving the selected date for the anchor's month. Year navigation
moves one year and clamps leap-day anchors when necessary. Mini-months do not
provide drag targets.

Multi-Week reuses Month's day-cell grid, overflow, source distinctions, task/block
drag moves and day details. It starts Monday, defaults to two weeks and supports
2–6 weeks; the chosen count lives within the Calendar mount, independently from
Multi-Day's count. Previous/next advances by that many calendar weeks. Day cells
include month labels; shared dialogs include the year for boundary crossings.
Narrow windows use scoped horizontal scrolling around a readable seven-column
grid. Year exports its full calendar year; Multi-Week exports its displayed weeks,
using the same filtered local-block eligibility as the other modes.

`lib/calendar-time-grid.ts` clips actual timed intervals to local midnight
boundaries and assigns deterministic overlap columns per connected component.
The hour ruler is wall-clock based: spring gaps remain visible; intervals crossing
a fall-back fold that cannot be represented safely remain in labeled interval
details. Timed deadlines and zero-length external events use instant flags,
instead of acquiring durations. Floating source events retain source-clock labels
in a separate details section. All-day intervals retain exclusive ends. Every day
has a Details action exposing complete titles, source labels and existing date
moves, including short intervals and crowded flags. External items stay read-only.
The time grid owns scoped horizontal scrolling, with a pinned hour ruler; task
section vertical scrolling remains separate. The task `<main>` is shrinkable on
narrow stacked shells so its scrolling child remains reachable.

Day details provide explicit local datetime forms for timed task deadlines and
work blocks. `lib/calendar-time-edit.ts` requires exact civil-time roundtrips,
rejects nonexistent local times, requires an earlier/later choice for newly edited
ambiguous times, and preserves unchanged original instants and subminute precision.
JavaScript Date exposes no offset-transition enumeration; candidate lookup samples
the surrounding ±24-hour offset regimes at minute resolution, then validates every
candidate against the full civil value (including historical offset seconds).
Block time edits preserve linked task identity and saved timezone metadata while
using the explicitly chosen end; they never update task deadlines. Existing date
moves keep their established DST semantics: block gaps are rejected and folds use
the earlier occurrence, while deadline date moves use Date's normalization.
Time-slot dragging and resizing remain outside this release.

The frontend timezone script includes the six baseline zones plus
`Australia/Lord_Howe` for half-hour DST gaps and folds, including the new range,
time-grid and explicit-time-edit suites.

#### Calendar, date, and timer contracts (QA-04)

`frontend/src/lib/task-filter.ts` shares scope and title/tag search selection
between task sections and the calendar. Today includes overdue and today's
local dates; Upcoming includes tomorrow and later; All and list scopes contain
unfinished tasks, including undated ones. Completed scope contains completed
tasks. Canceled tasks are excluded. Nested list children follow the same filters;
a matching child whose parent is excluded can appear at the top level. The
calendar renders valid date-only/timed deadlines, including dated subtasks, plus
work blocks belonging to the selected tasks even without deadlines. Each day cell
shows up to four deadlines and three blocks, with the rest available in its dialog.
Calendar creation uses the currently selected list, or no list for smart scopes.

Task deadlines have explicit none, date-only, or timed states (SCHED-01 below).
Date-only quick-add phrases and calendar creation keep the selected calendar date;
explicit times stay timed, including 09:00. Timed backend values are parsed as UTC,
then grouped by the browser's local date. Date-only labels bypass UTC conversion.
Moving a dated task changes its deadline, preserves its kind, and preserves local
hours, minutes, seconds, and milliseconds for timed deadlines. Native Date setters
advance nonexistent DST times by the gap and choose the earlier offset for overlaps.
Calendar copy identifies deadline changes instead of implying work attendance.
Work blocks use separate shaded chips with timed ranges or All day labels; they
appear on every overlapping browser-local day (timed) or date label (all-day),
respecting exclusive ends. All blocks follow the owner's smart/list scope and
search, including terminal-state visibility. Drag identity includes both block ID
and rendered day; dragging a continuation shifts the complete interval by the
source/target calendar-day delta. Day dialogs expose all blocks plus a date-input
Move block action for keyboard and single-pointer use.

Block moves preserve displayed browser-local start time, fractional elapsed
duration, task association, and saved IANA metadata. Nonexistent local target
times are rejected instead of silently shifted; repeated times use the earlier
occurrence through native Date resolution. This single-block interaction policy
is distinct from future saved-zone recurring-series expansion below. All-day
moves preserve date-span length and exclusive ends without creating UTC instants.
Only the selected block is replaced; deadlines, status, recurrence successors,
recorded focus, and scores remain unchanged. Block creation/deletion and direct
time/zone editing remain API-only.

`["time-blocks"]` is an independent query cache. Full-replacement PUTs wait for
server confirmation, disable block movement through settlement/refetch, and
invalidate only blocks. A shared mutation key keeps pending protection across
calendar remounts. Confirmed PUT responses replace existing cached blocks before
refetch, so a failed refresh does not discard the confirmed move or resurrect a
removed block. Failed moves retain the current cache and show an error;
query loading/error/retry is visible without hiding deadlines. Task/list deletion
invalidates blocks to reflect backend cascades.

Task overdue indicators in list, board, and calendar views subscribe through
`hooks/use-deadline-passed.ts`. Timed deadlines become overdue strictly after their
instant; date-only deadlines become overdue at the next browser-local midnight,
using the next calendar day instead of adding 24 hours across DST. Completed tasks
have no deadline subscription. Rescheduling replaces the timer, long delays are
split at the browser timer limit, and focus/visibility changes recheck wall time
after suspended callbacks. This updates the indicators only; scope selection,
section grouping, and relative date labels retain their existing refresh behavior.

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
deadline, and timer regressions in fresh processes under UTC, Asia/Kolkata,
America/New_York, Pacific/Kiritimati, America/Sao_Paulo, and Pacific/Apia. Historical
midnight DST gaps and a skipped local date cover label-preserving arithmetic.
Fake clocks exercise delayed callbacks without relying on host sleep or cadence.

#### Task-linked time blocks (SCHED-02 / SCHED-03)

`backend/app/time_blocks.py` owns discriminated block inputs;
`app/time_zones.py` owns IANA validation and local-clock resolution. The dedicated
`routers/time_blocks.py` exposes `/api/time-blocks` independently of tasks and focus.
All blocks retain stable IDs, required cascading `task_id`, and creation/update
UTC timestamps. Multiple and overlapping blocks are allowed. Blocks are plans
instead of attendance: CRUD never changes task deadlines/status/actual minutes,
focus history, journal metrics, or scores. Completion/cancellation preserves blocks;
recurring task successors receive none. Deleting a task or descendant deletes its
owned blocks.

**Write shapes** (POST creates with 201; PUT `/{id}` replaces all input fields,
preserving ID/creation time):

| Input kind | Required fields besides `task_id` | Meaning |
|---|---|---|
| `timed` | `start_at`, `end_at`; `timezone` defaults to `UTC` | Absolute instants plus a separately stored IANA display/wall-clock zone |
| `local` | `start_local`, `end_local`, `timezone` | Resolve local clock readings through the named zone; persist and return canonical `timed` |
| `all_day` | `start_date`, `end_date` | Inclusive start and exclusive end calendar labels; no zone or synthetic instants |

Omitted `kind` retains the SCHED-02 timed input contract. Naive `start_at`/`end_at`
remain UTC even when timezone metadata is supplied; aware inputs normalize to
naive UTC. Metadata never reinterprets absolute instants, and an input offset need
not equal the display zone's offset. Local inputs instead express clock readings
in that zone. Dates require `YYYY-MM-DD`; datetimes require an extended ISO time
component. Unknown fields, mixed shapes (including inapplicable null fields),
null required values, unknown zones, and nonpositive intervals return 422.

The user selected explicit DST resolution. `ZoneInfo` candidates for both folds
must round-trip through UTC to the original local clock reading. Gaps (including
skipped dates) are rejected even with an offset. Repeated local times require an
explicit offset matching a real occurrence; mismatching offsets are rejected for
ordinary times too. Valid endpoints compare by UTC elapsed time, so a block may
span a fold even when the end clock reading appears earlier. UTC and local
projection overflow return 422. `tzdata` (PSF IANA fallback) is a locked dependency
and is bundled with the frozen sidecar; standard `zoneinfo` uses host data when
available, otherwise the bundled fallback. Accepted names come from the bundled
IANA registry, including its aliases, instead of host-only `posix/`, `right/`, or
`posixrules` keys. Zone IDs are retained without guessing the user's host zone.

GET `/{id}` reads a block; DELETE removes it with 204. Missing blocks or associated
tasks return 404. Responses have explicit `kind` (`timed` or `all_day`) and flat
storage fields; inapplicable fields are null. Full PUT switches kinds by clearing
all incompatible fields, including timezone for all-day blocks.

GET collection filters are optional:
- `task_id` and `kind=timed|all_day` select associations/shapes.
- `start`/`end` are UTC instant bounds and select timed blocks.
- `start_date`/`end_date` are calendar-label bounds and select all-day blocks.
- Each range is half-open overlap (`block.end > start`, `block.start < end`);
  one bound is valid and paired bounds require strictly increasing values.
  Mixed instant/date ranges or a range incompatible with `kind` return 422.
  All-day dates are never projected into an instant window or shifted by timezone.
- Without a range both kinds are returned. Ordering is `(kind, start_at,
  start_date, id)` (all-day first, then chronological within each kind).
  Unknown task filters return an empty list.

Migration v6 introduced timed blocks. Migration v7 rebuilds that table with
`kind`, `timezone`, nullable instant fields, and nullable `start_date`/`end_date`.
A single CHECK enforces the complete timed or all-day shape, explicit null
exclusivity, and positive intervals; indexes cover task and both range families.
All existing rows retain their IDs, associations, instant/timestamp bytes and
become `kind=timed, timezone=UTC`; no host timezone or all-day intent is inferred.
Existing file databases receive normal pre-upgrade checkpoints. SQLite backup and
offline restore preserve both kinds; portable export v1 adds the explicit kind,
zone, and date fields to its allowlist while retaining UTC fractional precision.
Consumers ignore unknown fields/collections. No deadline becomes a block.

For future calendar recurrence, wall-clock intent is the anchor's local clock in
its stored IANA zone. Each occurrence must resolve its own local calendar date
through that zone instead of adding a fixed UTC duration: 09:00 stays 09:00 across
DST. Gaps need an explicit reschedule and ambiguous occurrences need a matching
offset; the service must not silently shift or choose. All-day recurrence operates
on calendar labels. This is the boundary contract only: no block RRULE, automatic
expansion, series, or exception storage is introduced here. SCHED-04 defines
the ownership boundary below; ICS-02 retains external series opaquely, while
expanded occurrence storage remains deferred.
Existing completion-triggered task recurrence keeps its UTC/date semantics.
Work-block calendar rendering/rescheduling is implemented under UX-03. ICS file
export/import and outbound CalDAV are described below; none implies attendance
or block completion.

#### Task deadlines and scheduled work (SCHED-01)

A deadline answers when a task is due; a work block answers when work is planned.
These are independent dimensions. A task without a deadline can have future work
blocks, and a dated task can remain unscheduled. The time-block API supports
multiple timed or all-day blocks per task (SCHED-02/SCHED-03 above). No migration
creates appointments, durations, or attendance from a deadline. Date-only deadlines
are separate from all-day events.

`Task.deadline` is the canonical API value:

| State | JSON shape | Meaning |
|---|---|---|
| No deadline | `{"kind":"none"}` | No completion deadline; unrelated to future work-block presence |
| Date-only | `{"kind":"date","date":"2026-11-02"}` | A calendar date label, unchanged by timezone conversion; no assumed hour |
| Timed | `{"kind":"timed","at":"2026-11-02T09:00:00"}` | A naive-UTC instant on read; aware ISO input is normalized to naive UTC |

Task create and PATCH accept this discriminated value. Omission on create means
no deadline; omission on PATCH leaves the deadline unchanged. Explicit `kind:none`
clears it. Null, malformed states, extra union properties, and conflicting
`deadline` plus `due_date` writes return HTTP 422. The response also retains
`due_date` as a timed-only compatibility projection and nullable read-only
`deadline_date`. Legacy `due_date` writes select a timed deadline, and null clears
any kind. Raw `deadline_date` writes are refused. The frontend's canonical tasks
cache updates and rolls back the deadline and its legacy projection together.

Storage keeps `due_date DATETIME` for timed deadlines and adds `deadline_date DATE`
for date labels. A SQLite CHECK prevents both from being populated. The explicit
API kind is derived from these columns instead of storing a redundant discriminator.
Migration v5 adds the date column and index without rewriting any existing value:
all non-null legacy `due_date` values remain timed deadlines, including synthetic
09:00 fallbacks; null remains no deadline. Original date-only intent cannot be
recovered from those timestamps. The user explicitly selected this preservation
policy before migration. Existing IDs, recurrence identity, task associations,
completion/focus history, and saved review snapshots remain unchanged. Existing
file databases receive the usual DATA-03 pre-upgrade checkpoint; fresh and offline
restored databases follow the same migrations. Older binaries refuse schema v5.

The UI creates date-only deadlines from date-only quick-add phrases, calendar-day
creation, and menu shortcuts. Explicit clock phrases select timed deadlines.
Legacy times stay visible, including 09:00. Calendar drag edits the selected task's
deadline instead of scheduling attendance, retains its kind, and leaves task
completion/focus history independent. Lists and calendar share browser-local day
selection; date-only items sort before timed items on the same date.

`GET /api/tasks?overdue=true` uses strict instant comparison for timed deadlines
and `deadline_date < UTC today` for date-only values. Callers may supply
`as_of_date=YYYY-MM-DD` to choose the calendar-day cutoff for date-only deadlines;
it does not alter timed comparisons. Existing `due_before` (exclusive) and
`due_after` (inclusive) datetime filters remain timed-only. The browser fetches all
tasks and uses its own local day for filters and date-only overdue indicators;
UTC-default API results can therefore differ around midnight unless a caller
supplies its local `as_of_date`. This preserves the existing UTC backend versus
local-display distinction without inventing a persisted timezone.

Daily scoring retains the timed-deadline planned-task rule. Date-only deadlines
count on and after their label in the requested UTC report day, unless the task
was completed before that day; canceled tasks remain excluded. Undated tasks
count when completed that day. All planned tasks MUST have `created_at` strictly
before the requested UTC day's exclusive end; a task created at the next midnight
or later cannot enter that day's planned count, even with an older deadline.
Live historical metrics project current task fields backward within this creation
boundary; later deadline/status edits or deletion can still change them. They do
not reconstruct what the user actually planned at the time. Exact reconstruction
would require a separate event-history or planning-snapshot design; neither is
introduced here. Saved reviews remain snapshots until explicitly rerun. AI capture
with a date but no time creates a
date-only deadline; explicit times retain the existing server-local interpretation
before UTC normalization. Briefing includes date-only due/overdue tasks using
UTC day boundaries. Portable export v1 adds nullable `tasks.deadline_date` as an
additive field and preserves legacy timed values; consumers should ignore unknown
fields. SQLite backups/restores preserve both storage forms.

#### Frontend domain hooks (REV-11)

`frontend/src/hooks/api.ts` preserves the public hook imports while dedicated
modules own tasks/lists/time blocks (`tasks.ts`), journal/scores/insights
(`journal.ts`), AI settings and streaming (`ai.ts`), and calendar imports
(`calendar-imports.ts`). Calendar inbound and webhooks retain their existing
modules. Shared query keys live in `query-keys.ts`; telemetry invalidation lives
in `invalidation.ts`. Domain modules import these shared primitives directly
instead of importing the compatibility facade. Task hooks retain the single
`tasksKey` object and the existing per-QueryClient mutation coordinator.

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

`backend/app/task_completion.py` owns the status transition shared by task POST
and PATCH; `backend/app/recurring_tasks.py` owns task-series identity and successor creation;
`recurrence.py` owns RRULE date arithmetic. This is separate from future calendar
provider recurrence (SCHED-04). New explicit rule writes accept only `FREQ=DAILY`
or `FREQ=WEEKLY`, positive integer `INTERVAL`, and unnumbered `BYDAY` only for
weekly rules. `INTERVAL` is bounded by RFC 5545's signed 32-bit integer range;
a successor outside the supported calendar range returns 422 without completing
the task. Parsing tolerates case, whitespace, and an optional `RRULE:` prefix;
it never silently clamps intervals or filters fields. Unknown, duplicate, malformed,
or unsupported fields return 422. Existing invalid stored rules remain readable
and portable-exportable unchanged; unrelated edits remain allowed, but completion
requires clearing or replacing the rule (otherwise 422). No migration is needed.
Weekly intervals use Monday-based weeks; existing UTC/date task semantics remain
unchanged.

- Recurring tasks receive a server-managed `recurrence_series_id` equal to the
  root task ID and `recurrence_occurrence = 0`. Clones share the series ID and
  increment the occurrence number. These fields are returned by task APIs;
  create/update inputs cannot assign them.
- Non-recurring tasks have null identity fields until recurrence is enabled.
  Removing the rule stops regeneration but retains any existing identity;
  re-enabling recurrence resumes the same identity.
- `POST /api/tasks` accepts `status=completed`. Creation stamps naive-UTC
  `completed_at` and, for a recurring task, creates its open successor in the same
  transaction. Successor failure rolls back the entire creation. Other creation
  statuses have no completion timestamp or successor. PATCH stamps completion
  only on entry into completed; repeated completed writes retain the timestamp,
  and leaving completed clears it. A successful POST repeated by a client creates
  a new task/series; occurrence uniqueness is not request-level idempotency.
- Completion preserves the finished row and its focus/completion history. The
  successor copies task configuration, starts as todo with zero actual minutes,
  and shares the completion transaction. Timed deadlines retain their time;
  date-only deadlines advance as calendar dates without gaining a time. An undated
  recurring task retains the compatibility behavior: its next timed deadline is
  computed from completion time. No work block is cloned or created.
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

#### Task/calendar recurrence boundary (SCHED-04)

Completion-triggered task recurrence belongs to `recurring_tasks.py` and
`recurrence.py`; calendar `VEVENT` recurrence is a separate domain.
Local work blocks are currently nonrecurring and reject calendar recurrence
inputs. This boundary introduces no series schema, recurrence expansion, or provider
integration. ICS-01 implements individual-block snapshot export below. ICS-02
now stores imported series opaquely; expansion and calendar display remain
deferred. SCHED-04 itself introduced no migration.

- Snapshot export maps each individual block's stable local ID to a stable
  `VEVENT` UID. A task RRULE must never become a `VEVENT` RRULE; event attendance
  or status changes must never trigger task successor clones.
- External import identity is collection/source + UID + original typed
  `RECURRENCE-ID` (DATE, local date-time with TZID, or UTC date-time); the series
  master uses an explicit master marker instead of an occurrence ID. A moved
  occurrence retains its original recurrence identity, not its new start time.
  Never match by title or date. Floating date-times and `RANGE=THISANDFUTURE`
  require dedicated support; until then retain the whole resource as opaque and
  read-only or reject it atomically instead of dropping those semantics.
- Future series handling must preserve overrides, cancellation tombstones, and
  `EXDATE`/`RDATE` values. Unsupported raw provider rules must remain opaque and
  read-only or be rejected atomically; never convert them to task rules or
  partially expand them.
- Future calendar wall-clock recurrence follows SCHED-03's zone and explicit
  gap/fold resolution contract above; task UTC/date arithmetic is unchanged.

#### Selected-block iCalendar snapshots (ICS-01)

`app/calendar_export.py` serializes RFC 5545 calendars independently of task
recurrence and future CalDAV adapters. `POST /api/calendar/export` accepts exactly
`{"block_ids":["block-id", "another-id"]}` with a nonempty list of nonempty strict
strings. Selection is explicit per download; no export flags or migration are
introduced. One joined SELECT reads blocks and task titles/status from the same
SQLite statement snapshot. Duplicates collapse, IDs sort lexicographically, and
any missing ID returns 404 instead of a partial file. Invalid requests return 422.

- Each selected block becomes one independent `VEVENT`, with stable UID
  `meditations-time-block-{uuid5(NAMESPACE_URL, "journal:time-block:" + id)}@journal.local`.
  Moving a block, changing its kind or owner, and renaming/completing its task
  preserve that UID. Backups/restores preserve IDs; independent databases use
  independently generated IDs. No title/date matching or remote identity exists.
- Timed starts/ends export as UTC `Z` values. `X-JOURNAL-TIMEZONE` preserves the
  saved IANA metadata for inspection, instead of relying on receiving clients to
  understand custom fields. No floating time, TZID, VTIMEZONE, or calendar RRULE
  is needed for individual UTC instants. Clients display them in their own zone.
- All-day starts/ends use `VALUE=DATE`, retaining the exclusive end label without
  creating UTC instants. Fractional timed seconds truncate to whole seconds;
  an interval that collapses at that precision rejects the whole export with 422.
- SUMMARY contains the task title only. Canceled owners map to `CANCELLED`, all
  others (including completed tasks) to `CONFIRMED`; attendance and task status
  remain independent. No descriptions, deadlines, task RRULEs, journals, tags,
  credentials, focus history, or automatic task successors enter the file.
- DTSTAMP is export time; CREATED is block creation; LAST-MODIFIED is the later
  block/task update. TEXT escapes backslashes, commas, semicolons and newlines;
  forbidden control characters return 422. CRLF lines fold at 75 UTF-8 octets
  without splitting code points. Response is a UTF-8 `text/calendar` attachment
  named `meditations-calendar.ics`.

The calendar's **Export work blocks** expands an inline checkbox list. Candidates
are blocks overlapping the displayed month, following owner scope/search/status;
neighboring grid days alone do not qualify. Every candidate starts unchecked.
Changing month/scope/search resets selection. Removed candidates are excluded at
submission; the selected ID payload freezes before a native save dialog opens.
Loading, query errors, and pending block moves disable export. Each selected block
exports its complete interval, including portions outside the month. Pending,
empty, error/retry, cancellation, and saved/download-started states are explicit.
Browser/native downloads reuse the shared private file delivery lifecycle without
changing tasks or block caches. Browser URLs release on retry or departure;
native saves create a new private file and finish once a path is chosen.

Export is an unencrypted snapshot, instead of synchronization or a restorable
backup. Finish saving edits first. Stable UIDs support identification, but client
reimport/update behavior varies; repeated imports can duplicate events. Deleting
or moving blocks does not update previously imported copies. File imports are
independent read-only inventories (ICS-02 below); subscriptions and calendar-series
expansion remain deferred. Outbound CalDAV is described in §6.4.

#### Read-only iCalendar file imports (ICS-02)

`calendar_import/` owns parsing, identity and atomic persistence separately from
snapshot export, task recurrence and outbound CalDAV. The Settings import section
accepts an explicit new named destination or an existing source ID; filenames
and names never identify sources. Source-scoped identity is UID + an explicit
master marker or the original typed recurrence ID, including its TZID. Moving an
exception cannot change its original occurrence identity. Floating identities
remain explicit. No imported event has a task/block/CalDAV-link relationship.

Schema v13 stores `calendar_import_sources`, `calendar_import_snapshots`, and
`calendar_import_events`. Every successful upload retains the original text,
including calendar-level properties and timezone definitions; inventory rows
reference their supplying snapshot. Canonical component text plus calendar
context determines unchanged detection, while original snapshots provide lossless
retention. Changed matching identities replace inventory data; omitted identities
remain untouched, including cancellations and exceptions. The latest explicit
import wins regardless of SEQUENCE or DTSTAMP. Duplicate identities in one file
reject the entire upload; independent sources may contain identical UIDs.

The maintained `icalendar` library parses content with additional framing,
component-hierarchy, typed-identity and value checks. VEVENTs, their VALARMs,
and VTIMEZONE definitions are retained as data; unsupported components such as
VTODO/VJOURNAL/VFREEBUSY reject the complete upload. RRULE/RDATE/EXDATE, range
exceptions, floating times and custom properties are opaque/read-only. Nothing
expands occurrences, resolves source times to stored UTC datetimes, executes
alarms, follows attachment URLs or sends invitations. Source time strings are
explicitly labeled in the inventory instead of being guessed in the device zone.
Normal application timestamps remain naive UTC.

`POST /api/calendar/imports` validates before writing and commits the source,
snapshot and all changed events together. A missing source returns 404; rejected
content returns 422 with no partial changes. GET lists sources, reads per-source
event inventory or original upload snapshots. DELETE removes a source with
cascading inventory/snapshot cleanup. SQLite backup/offline restore preserve all
import data; ordinary portable ZIP export excludes it. Upload history is retained
until the source is removed, so backups may contain private imported content.

The self-contained Settings section supports file selection, explicit repeat
imports, inventory inspection, confirmed removal, pending states and retry.
The separate `['calendar-imports']` query family never invalidates tasks or
telemetry. Payloads capture destination and file at submission; the pending
mutation covers file reading and API persistence and survives view departure.
Completion refreshes inventory caches even after navigation; view-local notices
are shown only when the initiating view remains mounted. The standalone overlay
below reads this inventory and expands supported series only for an explicit
bounded display window (REV-17).

See [calendar import usage and API](docs/calendar-import.md).

#### Read-only imported calendar overlay (SYNC-01)

Calendar can display one explicitly selected imported file destination alongside
local deadlines and work blocks. Hidden is the initial state on each Calendar
mount; selection is view-local, persists across month/task-filter changes, and
is independent of task list, search and status filters. Imported chips have a
calendar icon, dashed outline and Imported label. They open the existing day
dialog for read-only interval/status details; they have no drag, reschedule,
completion, export selection or outbound-sync authority. Two imported chips per
day are shown before overflow; the day dialog includes all overlapping items.

`GET /api/calendar/imports/{source_id}/overlay` delegates to the separate
`calendar_import/overlay.py` projection. It returns `{source_id, items, unplaced}`;
placed records retain source/event IDs, UID, summary and status with an explicit
`interval` of `date`, `timed` or `floating`, each with `start` and `end` strings.
Date intervals use exclusive ends; missing date ends default to the next day.
Timed instants resolve using the supplying snapshot's timezone context and return
UTC ISO strings ending in Z. Embedded VTIMEZONE definitions take precedence over
registry zones, and each event uses its own snapshot even when another source or
reimport defines the same TZID differently. Without an embedded definition, IANA
zones resolve through ZoneInfo; parser-global cached definitions are never used.
Clock values and timezone parameters come from the original snapshot component,
instead of library serialization, which can replace a TZID with a UTC suffix.
Repeat-import equality compares original start/end parameters and values as well
as the canonical component/context, so changed clock intent refreshes the record.
Floating offset-free values retain source clock
labels and occupy those local calendar dates without assigning an instant, even
inside a device DST gap. Missing timed/floating ends are point events. Timed
placement uses browser-local half-open day boundaries, so DST-length days and
cross-midnight events retain their correct overlap. Points appear on their
start day; events ending at midnight do not occupy the next day.

Without a display window, recurring masters/exceptions and cancellations remain
outside the grid. Windowed recurrence follows REV-17 below. DURATION-based events,
unknown zones, ambiguous/nonexistent named local times and invalid/incomparable
intervals are listed outside the grid with explicit reasons. No guessed duration,
alarm execution or URL fetch occurs. Original imports remain unchanged. Descriptions, attendees,
attachments and raw snapshots are omitted from the projection response. Empty,
loading and retryable error states are explicit; failed queries hide stale
appointments. Selection changes never display the previous source's response.

The overlay lives only in the independent `['calendar-imports']` query family;
reimport/removal invalidates it without task/telemetry invalidations. There is no
new schema, persistent preference or remote fetch. Files are snapshots;
updates require explicit reimport. URL subscriptions remain a separate future
feature; live inbound reconciliation is SYNC-02 below.


#### Bounded external recurring occurrence display (REV-17)

Imported and live overlays share the read-only `app/external_recurrence.py`
projection. Both endpoints accept optional paired ISO `start` and `end` dates:
end is exclusive, the interval must be positive, and the maximum is 370 days.
Absent dates preserve the older standalone/unplaced-recurrence contract. Calendar
always supplies its actual visible days (including Month padding), padded by one
calendar day at either end to cover browser-local versus UTC day boundaries.
All six modes reuse the same occurrence projection. Source selection remains
view-local; imported/live query keys include source and window independently of
`['tasks']`. A new window never renders a previous window's response while loading.

The engine supports DAILY/WEEKLY/MONTHLY/YEARLY rules with INTERVAL, COUNT, UNTIL,
BYDAY (including ordinals), BYMONTHDAY, BYMONTH, WKST and BYSETPOS, plus RDATE and
EXDATE. It resolves wall-clock recurrence in the supplying snapshot's timezone,
with embedded VTIMEZONE precedence, and preserves floating clocks and exclusive
all-day ends. Original recurrence identity, instead of the moved start, identifies
an overridden occurrence; moved exceptions can enter or leave the visible range.
Cancelled occurrences are omitted; a cancelled master suppresses its series.
Occurrence IDs are deterministic within their source and use the original typed
clock/timezone domain, so range changes do not rename matching occurrences.

EXRULE, hourly/finer frequencies, period-valued RDATE and RANGE exceptions remain
unsupported. Recurring DTSTART/DTEND pairs in differing clock domains/TZIDs and
invalid rule combinations also remain unsupported instead of being coerced.
Unsupported, over-limit or unsafe series produce explicit unplaced diagnostics
instead of a partial misleading expansion. Search is bounded by both 20,000
candidates and 20,000 calendar days from the original series seed to the requested
end. An internal UNTIL horizon also prevents impossible/sparse rules searching
beyond the requested end plus two days; original COUNT/UNTIL semantics remain.
Very old or dense series may remain unplaced even for a short display window.
`python-dateutil` is an explicit dependency using the already locked distribution.

Projection does not mutate snapshots, imports, inbound resources, tasks, work
blocks, scores or publication mappings. Imported reimport remains an
omission-preserving identity merge. Live windowed projection reparses retained
valid resource text, including a master with overrides, without changing the
inbound inventory schema or its complete-collection deletion authority. Live
refresh/removal changes the next projection; stale-cache/reconciliation messaging
retains the existing contract. This grants no series-editing, task-recurrence,
alarm, invitation or bidirectional authority.

#### Capability-aware inbound reconciliation (SYNC-02)

`app/calendar_sync/inbound.py` mirrors read-only external events from enabled,
verified CalDAV connections into a dedicated schema-v15 cache.
`calendar_inbound_state` owns capability, token, monotonic revision, last
successful check, and explicit error status. `calendar_inbound_events` owns
resource URL/ETag, original UTF-8 text and parsed projection fields. These
rows never modify tasks, deadlines, work blocks, focus, scores or outbound
links. SQLite backups/recovery preserve them; portable ZIP exports exclude them.

- **Capability**: `supported-report-set` selects RFC 6578 `sync-collection`
  REPORT with `sync-level=1`, otherwise complete Depth-1 listings. An absent
  optional report property selects listing. An explicitly unsupported REPORT
  (405/501) switches to listing; a malformed/incomplete report fails instead
  of becoming an empty inventory. Successful reports require one valid token.
- **Batch boundary**: all reported changes and GET payloads are validated
  before one cache/cursor commit. GET URL and strong ETag must match the
  enumeration; a changed or disappeared resource aborts the batch for retry.
  Read sessions close before HTTP. At commit SQLite's writer lock protects
  connection and monotonic-cursor comparisons, so superseded passes cannot
  overwrite a newer cache, pause or destination. Cached resource IDs survive
  both unchanged passes and updates. Operational errors retain the last-good
  cache/token and record a generic credential-safe message.
- **Deletion authority**: the cache covers the complete selected collection,
  with no date window. Incremental reports process explicit deletion members.
  Complete listings and initial token-less reports remove cached URLs absent
  from the completed inventory, including an empty inventory. A rejected token
  (403 with the DAV `valid-sync-token` precondition) recovers through an initial
  REPORT in the same pass. Token and cache change together only after success;
  failed resets cannot remove cached events.
- **Protocol boundary**: report hrefs must be same-origin immediate collection
  members, with no duplicate/contradictory entries, query/dot aliases, DTDs or
  entities. Only REPORT's parsed DAV token precondition triggers token recovery;
  unrelated permission failures remain authentication errors.
- **Retained resources**: multiple VEVENTs in one resource retain their original
  text, including a valid recurrence master with overrides. Legacy unwindowed
  projection leaves them opaque; REV-17 reparses valid retained resources for
  bounded read-only occurrence display. Invalid iCalendar retains valid UTF-8
  text as `component_state='unparsable'`. Non-UTF-8 GET bodies fail the batch
  instead of silently replacing bytes. No alarm executes.
- **Lifecycle**: the queue worker starts with the backend and runs every 30
  seconds, on manual **Sync now**, and via the app-resume endpoint
  `POST /api/calendar/connections/resume`. Existing startup/restore verification
  gates remain: no remote or vault access occurs until a connection is explicitly
  verified and enabled. Authentication failures disable it and require
  verification again. Connection destination changes atomically clear the old
  inbound cache/cursor; same-destination credential replacement retains them.
- **Frontend**: `hooks/calendar-inbound.ts` owns independent
  `['calendar-inbound']` queries, 10-second cache polling, and stable window
  focus/visibility listeners. Overlapping resume signals share one active pass
  per QueryClient. Resume/manual controls invalidate connection and inbound
  caches without task/telemetry invalidation. The initially Hidden **Live
  calendar** selector renders separate read-only mirrored chips and unplaced
  details from `GET /api/calendar/connections/{id}/inbound/overlay`. The response
  includes `reconciliation` (`never`/`current`/`error`, capability, last successful
  timestamp, safe error). Paused, authentication-required and failed refreshes
  label retained appointments stale; failed cache reads hide them and offer retry.

Bidirectional edits and inbound write authority remain SYNC-03; `VTODO` task
synchronization remains TASKDAV-01. The REV-20 evaluation (2026-11-06) defers
both, along with Evolution Data Server/Akonadi bridges: the user confirmed no
current unmet workflow. Reconsider only after a demonstrated need, an approved
ownership/concurrency/deletion/recurrence/echo/conflict design for proposed
bidirectional writes, and current packaged native/credential acceptance.
Read-only mirroring and explicit outbound VEVENT publication retain their
existing authority; no bridge, mandatory account, server or cloud relay is added.


#### Read-only subscription evaluation (ICS-03)

ICS-03 is a design evaluation, instead of a runtime subscription feature.
External URL polling and publishing a Journal feed are separate directions:

- **External URL → Journal**: recommend a future opt-in outbound GET worker with
  separate source/polling state, credential-store protection for private URLs,
  conditional HTTP validation and atomic complete-snapshot replacement. This must
  not reuse file import's omission-preserving merge policy. Failed refreshes keep
  the last good inventory. No inbound listener is needed. A future subscription may reuse REV-17
  for supported bounded occurrence display; unsupported source semantics remain
  opaque. Startup/resume and manual refresh operate
  only while the application runs, with explicit stale/error status.
- **Journal → calendar client**: defer publishing until stable addressing and
  per-feed revocable authorization exist. The packaged ephemeral backend address
  is unsuitable. A future feed requires persistent explicit block selection,
  ICS-01 field/privacy semantics and read-only access isolated from application
  mutation routes. Loopback serves same-machine clients only while Journal runs;
  other devices need intentional reachable hosting. Cloud hosting/public relays
  remain outside scope.

Both directions are one-way and grant no authority to rewrite tasks, blocks or
telemetry. The consuming client controls polling; refresh hints do not guarantee
freshness or deletion propagation. Revocation cannot retract cached copies.
No schema, API, worker or UI is added by this evaluation. See the
[subscription evaluation](docs/calendar-subscriptions.md) for source identity,
complete-feed assumptions, recovery, credential handling and implementation gates.

### 6.2 Feature Module 2: The Modern Journaling Engine
1. **TipTap Markdown Block Editor**:
   - Clean typographical hierarchy with Notion-style slash commands (`/h1`, `/task`, `/quote`, `/callout`).
   - Saves use a 700 ms debounce with the day, markdown, mood, and energy frozen at schedule time. Undoing to the loaded text replaces queued content while preserving current ratings.
   - Loading stored markdown suppresses editor update events. The editor, ratings, and content-insertion buttons stay disabled until the selected day's entry resolves; the journal surface exposes its busy state. A settled initial-load failure clears busy state and shows an alert with query retry while editing stays locked. A 404 resolves as an empty day; failed background refetches do not lock already-loaded content or replace an unsaved draft. Visiting an empty day creates no entry; every day switch (including Today and search-result navigation), section exit, and editor unmount flushes queued changes to their original day.
   - Journal saves optimistically cache editable content for both existing and first-time entries, including rating-only entries. A return during an in-flight save hydrates from that frozen document instead of a cached empty-day response. New optimistic documents omit server telemetry and timestamps until refetch supplies them; recorded metrics render only when present. Failed saves restore the previous cache value, including an explicitly absent entry. Background refetches still do not replace an already-loaded editor or unsaved typing.
   - Activity insertion belongs to the active editor lifecycle: changing days, leaving the journal, or unmounting invalidates pending results, even after returning to the same day. Same-day results append to the latest text rather than overwriting edits made during the request. Slash-extension callbacks dispatch through current handlers because ProseMirror retains the initially configured callbacks.
   - Slash command definitions live in `components/slash-command.tsx`; `components/journal/slash-menu.ts` owns popup DOM, active selection, geometry and cleanup. Pointer hover and arrow keys share selection; keyboard navigation preserves rows and reveals the active option. Click/tap or Enter invokes a command once while retaining editor focus. Escape exits suggestion state without changing journal text.
   - The fixed slash popup recalculates its anchor on captured ancestor scrolling, viewport changes and ancestor `ResizeObserver` notifications. It flips and constrains its dimensions to available viewport space; missing or clipped anchors hide it. Listbox/options and editor active-descendant attributes expose selection. Day/section transitions, unmount and suggestion exit remove the popup and its subscriptions.
   - External `journalDay` is a one-shot navigation command and is consumed even when that day is already selected.
   - JRN-02 writing controls live in `components/journal/formatting-toolbar.tsx`; the full group offers paragraph/headings 1–6, bold/italic/strike, inline code, bullet/ordered/task lists, quote/code blocks, links and undo/redo. Active toggles compose; Clear formatting removes inline marks only from a nonempty selection, preserving block/list structure. Paragraph conversion is a separate block-style action. Pointer actions preserve selection; native controls retain keyboard access, with larger coarse-pointer targets.
   - `components/journal/selection-toolbar.tsx` uses TipTap v3's BubbleMenu with a fixed body portal, clipping-aware virtual selection geometry, viewport flipping/shifting and event/observer-driven repositioning for scrolling, sidebar and content resizing. It hides on composition, empty selection, outside focus or Escape; a new selection clears Escape dismissal. Day/editor-context changes unregister the plugin and subscriptions. Full writing controls remain available independently of the popup.
   - Link forms capture the selected range and document identity before input focus. Apply/remove restores that range; document or selection changes invalidate the draft instead of applying to stale offsets. Addresses use the installed Link extension's URI validation. Links do not navigate when clicked in the editor. Composition locks formatting controls, leaving composing text intact.
   - `components/journal/extensions.ts` centralizes the Markdown-safe schema and serialization (`html: false`, `breaks: true`). Markdown remains authoritative for saves, search/AI context and exact-file export. Underline is explicitly disabled; highlight has no control or production mark. An HTML-only highlight serializes to plain text and fails the persistence gate. Supporting either mark requires a separately approved serialization/storage decision, rather than silently losing formatting. AI rewrites remain proposals whose supported formatting is preserved on acceptance; model fidelity itself is not guaranteed.
   - Save feedback distinguishes queued unsaved changes from in-flight, failed and confirmed local saves for the displayed day. Retry local save uses the current editor text and ratings. Ratings hydrate once with the day's document, so cache rollback/refetch cannot replace failed local edits. These controls retain frozen debounced payloads, baseline/empty-day checks, rating overrides, activity lifecycle and stale-AI-preview protection.

2. **Automated Daily Activity Rollup Embeds**:
   - At the top or bottom of today's journal entry, a one-click button inserts live data:
     - **Tasks Completed Today**: `[x] Submit report`, `[x] Code review`.
     - **Focus Stats**: Total deep-work time (e.g., `3h 45m across 4 sessions`).
     - **Habit Checklist**: Water, Workout, Reading.
3. **Daily Reflection Templates**:
   - Configurable prompts: "What was the main friction point today?", "What is one win to celebrate?", "What should be deprioritized tomorrow?"

#### Independent progress receipts (REV-16)

Local persistence, search indexing, AI review and calendar publication have separate
presentation states; elapsed time never implies completion. Journal's closed-by-default
Save and search details disclosure queries `GET /api/journal/{day}/status` only while
open. The response includes entry existence, last persisted `updated_at`, and explicit
keyword (`ready | missing | not_applicable`) and semantic
(`ready | missing | unavailable | not_applicable`) states. Rating-only and absent days
have no searchable text. One SQL statement checks current persisted Markdown against
an exact single FTS row and, for semantic readiness, the transactional ready receipt
and vector existence. Missing sqlite-vec is unavailable rather than a failed local save.

`POST /api/journal/{day}/reindex` rebuilds only that saved document, or removes orphan
index data for an absent/rating-only day. It acquires SQLite's writer lock before
reading and holds it through receipt calculation/commit; concurrent saves cannot
leave an older reindex behind. Embedding failure can leave keyword ready and semantic
missing, with a retry action. Journal saves and capture invalidate document status;
reindex invalidates search results and global search status. Unsaved editor changes
are explicitly outside these persisted receipts. No new schema or durable job queue
is introduced.

Daily AI review distinguishes checking/unavailable, no saved review, in-progress,
saved snapshot and failure. Partial streams are previews; an ended stream without
`done` is a retryable failure. Existing saved reviews and journal content survive
review failure. Journal day changes remount review progress to prevent another day's
in-flight/error state appearing on the destination day.

Calendar link presentation requires both action and revision acknowledgement before
showing Remote change acknowledged; a `synced` state alone is insufficient. Deletion
acknowledgement is distinct from intentional detachment. Settings retains queue,
conflict/error counts, last acknowledged remote change and recovery controls. The
compact Calendar sources summary describes the read-only mirror's confirmed check,
active check, unknown or stale state and directs outbound publication inspection to
Settings. Mirror freshness never implies outbound acknowledgement or automatic
source selection. The existing polling/query and authority boundaries remain intact.

### 6.3 Feature Module 3: Proactive AI Agent Features
1. **Hierarchical Summarization & Review Agent**:
   - Evaluates daily balance, detects habit degradation early, and produces actionable insights.
2. **Smart Task Decomposition Agent**:
   - User inputs: `Plan product launch`.
   - Agent outputs structured subtasks with estimated times and priority suggestions.
3. **Conversational Daily Planning Briefing**:
   - The on-demand briefing reads at most 20 overdue tasks, 30 due-today tasks, yesterday's feedback and the existing 1,500-character journal excerpt to recommend an achievable Top 3. Candidate objects include stable task IDs, titles, explicit deadline fields and status; open-task totals use a count query. No additional journal/calendar history is loaded.
   - Responses retain `top_focus` strings and add aligned `recommendations: [{text, task_id}]`. An ID is executable only if supplied in the bounded candidate set and attached to the corresponding recommendation text. Unknown/misaligned IDs and legacy text-only output become general advice (`task_id: null`), without task-title matching. Partial streams use the same reference validation; frontend actions require a final `done` response. Failed or interrupted streams retain readable advice and expose retry without enabling actions.
   - `components/recommendations/task-actions.tsx` resolves references from the canonical tasks cache, independently of the current scope/search. Open task reveals the existing TaskItem actions inline without changing navigation/filter state. Renames use the current title; missing tasks keep their recommendation with an unavailable explanation. Completed/canceled tasks remain inspectable but cannot be scheduled or focused from the recommendation.
   - Schedule uses a dedicated inline form and `hooks/time-blocks.ts` to create a local all-day or timed work block. All-day ends are exclusive; local timed fields use the shared candidate calculation, reject clock gaps and require explicit earlier/later fold choices. Creation requires confirmation, leaves task deadlines unchanged, retains failed/hidden drafts for retry and refreshes the independent blocks cache. Existing different-task sessions and break phases must be finished or reset before Start focus can switch attribution. Expanded briefings scroll with task content.
   - Saved daily review responses expose `suggested_action_for_tomorrow` from existing rubric JSON; missing/invalid historical values resolve to an empty string. Journal offers an editable task draft for a saved recommendation, with optional date-only deadline and explicit Create task confirmation through the canonical task hook. Generation/partial output never creates tasks. Same-day unchanged-recommendation drafts and created-state feedback survive review regeneration; day/recommendation changes reset them. Drafts are view-local, not durable records. Weekly/monthly narrative extraction is outside this implementation; no title matching, automatic scheduling or inference from prose is introduced.
4. **Natural Language Omnibar & Conversational Capture**:
   - Dictate or paste unstructured text: *"Spoke with Alex. Need to email him the slide deck by Thursday 4pm and schedule team sync for Monday."*
   - Agent creates the journal note snippet and registers two tasks with explicit due dates.
5. **Ask My Second Brain (Hybrid Search)**:
   - Ask questions like: *"When did I start feeling burned out on the backend refactor and what caused it?"*
   - Queries `sqlite-vec` embeddings and `fts_entries` to cite past journal entries and weekly rollups.
   - `POST /api/agents/ask/stream` validates the submitted question against a 4,000-Unicode-code-point limit, including surrounding whitespace, before retrieval or model execution. Oversized input receives HTTP 422 with the field and maximum length; questions are never truncated. Accepted questions retain existing whitespace trimming and nonempty validation. Source and history context bounds are unchanged.

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

An explicit allowlist of columns exports ten source collections: lists, tasks,
time blocks, focus sessions, habits, habit logs, journal metadata, daily scores, weekly
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
database. Both recovery paths can run keyword-only. Each recovery/reindex pass
records embedding unavailability after its first initialization or inference
failure and skips embeddings for the remaining documents in that pass. Missing
embeddings retry at the next startup or explicit reindex; individual later saves
and search requests can also retry optional embeddings.

Model initialization and inference run on a dedicated serialized executor in
`app/embedding_worker.py`, never on the API event loop. Awaited results still
participate in the caller's source/index transaction; this is not an outbox or
a background indexing queue. Canceling a caller discards its result but cannot
interrupt an already-running model call; subsequent calls remain serialized.
Application and synthetic-seeder shutdown drain the executor before disposing the
database, including startup failure. Offloading does not shorten the SQLite writer
lock held during indexing/reconciliation; transaction/outbox changes require
separate evidence.
`GET /api/search/status` reports extension readiness; the reindex response's
`semantic` flag reports whether the rebuilt index contains a ready vector.


### 6.4 Optional Local-First Calendar Interoperability

Calendar interoperability is documented here and in the
[calendar synchronization guide](docs/calendar-sync.md). The former root `todo.md`
is absent; current local follow-ups live in the [feature backlog](features/todo.md).
ICS snapshots, backend
connection setup, conditional dispatch, and a durable background queue are
implemented, including Settings setup, explicit block selection, and synchronization
controls. Read-only file imports are also implemented. ICS-03 evaluates subscriptions;
URL polling and Journal feed publishing remain unimplemented. The sections below
distinguish current modules from their future integration contracts.

- **Local-only by default**: SQLite remains the source of truth for local tasks and time blocks. Calendar features require no app account; Google APIs, browser OAuth, and cloud notification relays are outside scope.
- **ICS milestone first**: Export selected time blocks as iCalendar (`.ics`) events without calendar accounts, credentials, or a server. File export is a snapshot; import, read-only subscriptions, and CalDAV are separate later extensions instead of prerequisites.
- **Optional CalDAV connection API**: Connect to a user-managed server using supported password/app-password authentication through the backend API. Settings provides setup, explicit per-block opt-in, pause/enablement, and manual synchronization. Radicale may run as a user-level service, installed and managed by the user; Journal does not bundle, install, start, or manage it. Verify server interoperability separately, including Nextcloud and Baïkal. OAuth-only server configurations are outside scope.
- **Sync availability**: Journal synchronizes only while running. A localhost server serves clients on the same machine; other devices need a reachable server. No public callback endpoint is required.
- **Domain separation**: Calendar events and task-linked time blocks remain distinct from task deadlines, completion, and scoring. CalDAV `VTODO` task synchronization is a separate optional feature.
- **Module boundary**: Keep ICS serialization self-contained and independent of CalDAV. The implemented CalDAV adapter, synchronization service, worker, and connection routes live in separate modules. Local changes commit independently of the server; persist resource links, UIDs, ETags, and queued work. Use conditional writes and explicit conflict states; use optional sync tokens with an ETag-based reconciliation fallback.
- **Connection credentials (CAL-03)**: Server credentials use a dedicated OS credential-store interface, outside ordinary settings and data exports. Linux desktop calendar bridges remain optional extensions. Outgoing automation has its own opt-in configuration and delivery ledger, independent of calendar synchronization.

#### Optional outgoing automation (HOOK-01 through HOOK-04)

- `backend/app/webhooks/` owns event capture, management routes, signing, and background delivery. Schema v14 adds endpoint configuration, durable per-entity versions, and a transactional per-endpoint outbox. Normal migrations, recovery checkpoints, and SQLite backups include these tables; portable exports continue to exclude automation configuration, delivery payloads, and credentials.
- SQLAlchemy flush capture writes `time_block.created`, `time_block.updated`, `time_block.deleted`, and `task.completed` deliveries in the same transaction as source changes. Database-cascaded time-block deletions retain a snapshot before deletion. Rollback removes the corresponding outbox work. Local saves do not call HTTP endpoints or the credential vault.
- Version-1 envelopes contain stable event/entity IDs, monotonic per-entity versions, UTC occurrence timestamps, and explicitly allowlisted scheduling metadata. Retries retain their envelope identity and payload. All-day intervals use exclusive date ends; timed intervals use UTC instants and retain time-zone metadata. Task deadlines retain none/date/timed semantics. Journal text, task descriptions, and credentials are excluded; sharing task titles requires separate opt-in.
- Endpoints select event types and either all tasks or explicit list IDs. Scope is evaluated at the source change; this is a future-event stream, without historical inventory or automatic reconciliation when a task moves between lists. Configuration changes cancel queued/failed payloads so an earlier privacy choice cannot be replayed to a new destination. Disable/removal also cancel queued work; re-enabling does not revive canceled events. Already accepted HTTP work cannot be recalled.
- The backend lifecycle runs the delivery worker only while Journal is running. Pending work survives restart. Transient network failures and retryable HTTP responses use durable delayed retries; terminal errors remain available for manual retry. Delivery is at least once, independent across endpoints; consumers deduplicate event IDs and compare entity versions instead of assuming arrival order or gapless versions. Consumer tombstones prevent delayed updates from resurrecting deletions.
- HMAC-SHA256 signs `timestamp + "." + raw JSON body`, using `X-Journal-Timestamp` and `X-Journal-Signature: sha256=<hex>`; `X-Journal-Event-Id` identifies retries. Secrets use the existing credential-store interface with a webhook-specific database namespace, never ordinary settings or payloads. HTTP redirects are not followed. Endpoint URLs reject userinfo, query strings, and fragments. HTTP loopback/private endpoints remain usable for user-managed local workflows.
- Settings owns endpoint selection, event/list scope, explicit title sharing, enable/disable/removal, synthetic test delivery, delivery status/errors, and retry. A delivered request means receiver acknowledgement, not confirmed calendar synchronization. The independent module does not require a public listener, cloud account, or calendar connection.
- `docs/webhooks.md` documents the contract and workflow. `examples/webhooks/local_workflow.py` is an optional standard-library loopback receiver with signature verification, durable receipt deduplication, version checks, deletion tombstones, and a separate completion policy. It stores a projection instead of issuing real calendar writes; downstream effects need their own durable/idempotent integration. Dedicated backend and frontend tests use fake vaults and stub endpoints, without real credentials or network services.


#### Calendar integration foundation (CAL-02)

Schema v8 adds `calendar_connections` and `calendar_links` without credentials.
Connections record server/calendar URLs, explicit connection state, and disabled
synchronization by default. Links retain block identity, destination/resource
identity, UID, acknowledged ETag, local/acknowledged revisions, desired action,
payload preparation state, sync state, and error state. One link per original
block prevents simultaneous destinations; destination/resource pairs are unique.
A nullable block FK uses SET NULL on source deletion while independent identity
and mapping survive; connection deletion is restricted while links exist.
No existing block is opted in during migration. Frozen migration, pre-upgrade
checkpoint, backup, and offline restore paths include the new tables. Portable
export's existing allowlist excludes synchronization metadata and payloads.

`app/calendar_sync/adapter.py` implements async CalDAV wire operations using
caller-owned `httpx.AsyncClient` instances. It discovers principals, calendar
homes, event collections and write privileges; lists resource URLs/strong ETags;
and supports GET, conditional create/update, and conditional delete. DAV XML,
propstat/status failures, invalid ETags, redirects, and cross-origin hrefs fail
explicitly. DTD/entity declarations are rejected. Authentication, missing
resources, precondition conflicts, transport failures, and protocol failures
remain distinct. There are no hidden retries: transport or response failures
after a mutation can leave an uncertain outcome for CAL-04 to reconcile.
Inbound reconciliation (SYNC-02) additionally issues a `sync-collection`
REPORT with a strict multistatus parser that accepts the `D:sync-token` child,
maps `403` + `D:valid-sync-token` to a recoverable `SyncTokenInvalid`, and
probes `supported-report-set` for capability detection. Complete Depth-1
listings remain the fallback and the deletion authority in listing mode.
No provider-specific support is claimed beyond tested Radicale interoperability.

`service.py` compares a complete listing against explicitly supplied link
snapshots. `worker.py` exposes one read-only inspection pass with an injected
adapter factory. Only enabled, connected destinations and acknowledged `synced`
links are inspected. Changed/missing remote resources become conflicts;
authentication failures mark the connection authentication-required. Conditional
local updates protect newer revisions, detached links, and changed connection
state from stale inspection results. Network/protocol failures propagate without
inferring remote deletions. The worker never publishes or deletes remote events.
The lifecycle queue invokes read-only inspection after dispatching each eligible
connection; callers can still invoke inspection independently.

`/api/calendar/connections` provides GET and POST for local disconnected drafts.
POST accepts only same-origin HTTP(S) server/calendar URLs, without credentials,
query strings or fragments; the collection URL ends in `/`. Unknown/enabling
fields are rejected. GET `/{id}/links` exposes only that connection's mappings;
DELETE `/{id}` removes only disconnected, disabled drafts without links. These
draft routes perform no server requests. CAL-03 adds explicit authentication
operations below; CAL-06 adds user controls. Calendar connections, status, and
links use independent frontend query families, separate from tasks/time blocks.

CAL-03 supplies credential-store-backed verification, selection, and
reconnection as described below. CAL-04 adds explicitly invoked conditional
dispatch and uncertain-outcome recovery; adapter mutation primitives alone do
not implement idempotent sync.
CAL-05 adds atomic deletion/edit capture and lifecycle queue scheduling below.
A BEFORE DELETE trigger records remote cleanup before SET NULL removes the source
FK. CAL-06 owns opt-in/enablement controls; CAL-07 owns live-server/packaged
interoperability checks.

#### Authenticated calendar connections (CAL-03)

`calendar_sync/connections.py` owns explicit discovery, connect/credential
replacement, verification, disconnect, and draft deletion. Authentication inputs
require username, password/app password, and `auth_type` (`basic` or `digest`).
`transport.py` creates isolated authenticated clients: default certificate
verification, no redirects, environment/netrc/proxy authentication disabled, and
no implicit retries. Credential-bearing API operations require HTTPS or exact
localhost/loopback HTTP. Remote plaintext HTTP and browser OAuth are outside the
API's supported authentication policy. Users supply and manage their server;
there is no automatic server installation, calendar creation, or cloud account.

Additional POST operations under `/api/calendar/connections/{id}`:

| Operation | Input and behavior |
|---|---|
| `/discover` | Username/password/auth type; return discovered calendar URLs, names, writable and VEVENT capabilities without persisting credentials or selecting a calendar |
| `/connect` | Same credentials plus a selected `calendar_url`; rediscover and verify that exact writable event calendar before saving credentials |
| `/verify` | Use saved OS credentials to rediscover and verify the selected calendar |
| `/disconnect` | Disable activity, detach mappings, remove local credentials, leave remote resources unchanged |

Connect and verify return connection metadata only. Calendar selection is
explicit; recommend a dedicated Meditations calendar. Existing links prevent
retargeting a connection, including when detached. Supplying changed credentials
replaces the stored credential blob only after successful verification. Failed
connect/verify attempts leave synchronization disabled and the connection
`authentication_required`; unsuccessful replacement discovery leaves previous
credentials untouched. Missing credentials require resubmission. Unavailable or
locked OS storage returns an actionable failure instead of a plaintext fallback.
Discovery is ephemeral and does not change an existing connection's state.

Schema v9 appends `credential_state` (`absent`, `present`, `removal_pending`) to
connections; all v8 rows begin absent. These are bookkeeping values, instead of
secrets. Username, password, and auth type live in a single versioned OS-vault
blob per connection under a database-scoped service name. The namespace hashes
the canonical database path; separate file databases use separate credentials,
and each in-memory lifecycle uses a new namespace. Moving/copying a database to
a different path requires supplying credentials again; old vault records require
cleanup using the original database/path or the OS vault interface. SQLite
backups/checkpoints preserve metadata but cannot back up or restore OS secrets.
Ordinary exports continue to exclude all integration tables and credentials.

`credentials.py` selects a deterministic built-in backend per platform: Linux
Secret Service, macOS Keychain, Windows Credential Manager. KWallet can be used
through a Secret Service-compatible interface where provided; direct KWallet
DBus fallback is not selected. The store never uses keyring plugin/chainer or
file/plaintext fallbacks, and never switches vaults because one is temporarily
unavailable. Backend access is lazy and off the event loop; local-only startup,
CRUD, and unused-draft deletion need no unlocked vault. Credential-thread
cancellation drains the running operation before lifecycle cleanup continues.
The audited `keyring` dependency and platform backend are included in sidecar
packaging; native service availability still depends on the user's OS/session.

Per-connection locks serialize credential changes, verification, disconnect,
and deletion within the database-owning backend. Before writing or removing a
vault blob, persist disabled `removal_pending` metadata. A crash, cancellation,
or ambiguous store/DB failure leaves that state recoverable: explicitly retry
disconnect to remove any possible blob before reconnecting. Disconnect commits
disabled/disconnected state and detached links before deleting credentials. A
locked-store removal failure returns an error with removal still pending; it
never reports complete cleanup. Repeating disconnect is idempotent. Link payload,
identity and revisions survive detachment; a previously syncing link receives an
explicit uncertain-outcome marker. No disconnect path sends remote DELETEs.
Draft deletion requires no links and credential state absent.

Every backend startup disables connection activity and changes previously
connected rows to `authentication_required`, without opening a vault or making a
network request. Call verify (or connect with new credentials) explicitly after
restart/restore; connected means the last explicit verification succeeded,
instead of a continuous reachability guarantee. Connection verification never
enables synchronization, opts in blocks, reattaches mappings, or settles remote
conflicts. The CAL-05 queue reconciles eligible work through CAL-04 before
retrying writes; verification and explicit enablement remain prerequisites.
Settings exposes these operations through CAL-06 below. CAL-07 verifies Radicale
3.9.0 over isolated loopback HTTP; Nextcloud/Baïkal and native credential-service
connectivity remain unverified. Packaged discovery is tested separately below.

#### Conditional outbound dispatch (CAL-04)

`app/calendar_sync/outbound.py` exposes `OutboundService(sessions, manager)` with
explicit `prepare(link_id)`, `dispatch(link_id)`, and local-only `detach(link_id)`
operations. CAL-05 supplies a lifecycle worker and transactional source-change
capture; CAL-06 exposes explicit opt-in, enablement, and user controls through
connection-scoped HTTP routes. Setup and verification alone never publish blocks.

Schema v10 adds `calendar_dispatches`: one immutable revision per link, containing
the action, resource URL, UID, expected ETag, serialized payload, and explicit
attempted flag. Links also record `acknowledged_action` (`unknown`, `upsert`, or
`delete`); legacy acknowledged ETags backfill `upsert`, otherwise `unknown`.
This distinguishes a confirmed remote deletion from missing acknowledgment
metadata. It survives source changes and cascaded source deletion through
the retained link. Migration/checkpoint/backup/offline restore include the table;
ordinary portable exports exclude it. Preparation freezes ICS-01 projection and
DTSTAMP, adding a random `X-JOURNAL-DISPATCH` ownership marker. Retrying preserves
the entire payload. Source representation errors persist locally and can be
retried after repair without contacting the provider.

All operations share the application-scoped connection manager's lifecycle lock;
callers MUST reuse that manager. This serializes writes, credential replacement,
disconnect, and detachment in the single database-owning backend. Database
transactions end before HTTP. Preparation validates the stable block UID and
immediate resource membership in the recorded selected calendar. Dispatch checks
identity, revision bounds, and expected ETag again. Missing source rows do not
prevent dispatch of an already frozen revision or durable deletion intent.

Before each mutation, GET reconciles the exact linked resource. A first create
requires absence even if an existing event has identical UID or payload. The
attempted flag commits before a conditional request; creation uses
`If-None-Match: *`, updates/deletes use the acknowledged strong `If-Match`.
After interruption, identical validated properties including the random marker
are ownership evidence for acknowledging a previously attempted upsert. Only
RFC line folding and property order within the same component are ignored;
values, parameters, whitespace, cardinality, and component boundaries remain exact. An absent
resource permits retry of that same uncertain create, never a second URL.
Unchanged acknowledged ETags allow retry of unapplied updates/deletes. Absence
after an attempted delete acknowledges removal; absence before a first delete
or update is a conflict. Divergent remote content/ETags, precondition failures,
or unsupported remote semantics become conflicts instead of unconditional writes.

Remote validation deliberately accepts a narrow serializer-compatible grammar:
one nonrecurring VEVENT, matching UID, UTC timed or exclusive-end DATE intervals,
and known properties. Unknown properties/parameters, nested components,
recurrence, attendees, and organizer block automatic writes. Property reordering
and folding are supported because Radicale applies these syntax-only changes.
Other canonicalization, including changed property values or added fields,
can still produce a conflict after a successful but unacknowledged write.
Explicit detachment leaves remote content unchanged and retains
unresolved dispatch evidence. Detached/conflicted links cannot dispatch again.

Successful acknowledgment and dispatch removal commit together. Only that
revision is acknowledged; newer edits or deletion intents remain pending and
use the returned ETag on the next pass. Authentication failures disable the
connection and require verification; other operational failures retain retryable
intent with fixed, privacy-safe errors. Cancellation or acknowledgment-commit
failure leaves the dispatch available for reconciliation. A newer opt-in after
an acknowledged deletion conditionally creates at the same URL/UID instead of
starting an independent identity. An orphan `syncing` link or acknowledged link
without an ETag or confirmed deletion requires explicit detachment. Startup
continues to disable connections, so recovery never initiates outbound writes
without explicit verification and later enablement. The lifecycle queue preserves
this ordering.

#### Durable offline queue (CAL-05)

Schema v11 installs three frozen SQLite triggers. Relevant block shape, interval,
zone, or ownership changes and task title/canceled-status changes increment each
active link's local revision in the same transaction as the source write.
Timestamp-only edits, task completion/reopening among non-canceled states,
deadlines, descriptions, focus, and scoring do not change the event projection.
No trigger creates a link or opts in a block. Detached links and existing delete
intent stay untouched; conflicts remain conflicts. Block deletion, including
cascaded task/subtask deletion, records delete intent before SET NULL. Legacy
active orphan links acquire delete intent during migration. Cached link payloads
are invalidated; immutable dispatch rows, URLs, UIDs, and ETags remain intact.
Backup/restore includes triggers; restore rejects missing or modified required
trigger definitions. Older backups acquire them through staged migration.

`calendar_sync/queue_worker.py` owns `QueueWorker.run_once()` and lifecycle
`serve()`. A pass selects a finite snapshot of eligible work, dispatches each
link at most once, and inspects acknowledged resources for remote changes.
Only connected, explicitly enabled, credential-present connections participate;
conflicted/detached links are excluded. Each operation rechecks lifecycle gates
under the shared connection manager lock. A failed link does not block other
links on ordinary transport/authentication failures. Local source writes never
wait for the vault or server. No SQLite transaction spans an HTTP request.

The worker runs immediately after startup verification/search recovery, then
waits 30 seconds after each completed pass. This is fixed-interval retry, without
exponential backoff, OS network notifications, or persistent attempt timing.
SQLite intent and dispatch evidence are authoritative; recreating the worker
needs no in-memory recovery state. Network/vault failures retry on later passes;
authentication failures disable activity until explicit verification and
reenablement. Conflict resolution remains explicit detachment instead of remote
overwrite. Read-only inventory failures never imply remote deletion. Worker
cancellation is awaited before engine disposal and preserves uncertain dispatches.

An offline create deleted before any remote mutation attempt is settled locally
without creating or deleting an event. If creation may have been attempted,
reconcile its immutable revision first and process the newer deletion on a later
pass. Acknowledgment evaluates the current local revision in SQL at UPDATE time;
a concurrent source edit cannot be mislabeled synced by a stale read. Only the
acknowledged revision is settled; newer revisions remain pending. Reopening the
app still requires verification and explicit enablement, and disconnect retains
detached mappings without remote cleanup. CAL-06 exposes opt-in, pause/resume,
queue status, and manual synchronization below. Setup alone leaves the queue
disabled. CAL-07 verifies live Radicale and packaged discovery below; native
vault and full desktop synchronization remain separate unverified checks.

#### Settings and synchronization controls (CAL-06)

`components/calendar-settings.tsx` and its connection-controls component extend
Settings without making calendar setup a prerequisite for local use. The setup
flow creates a disabled draft, discovers calendars using explicit Basic/Digest
credentials, then requires selection of a writable event calendar before saving
credentials. A dedicated Meditations calendar is recommended. Password-bearing
discovery/connect requests stay outside React Query caches; passwords remain
component-local and clear after connection or failure. Ordinary controls use an
independent calendar query family; task data remains in the canonical tasks cache.
Connection status and links refresh every ten seconds while Settings is mounted.

`calendar_sync/controls.py` exposes connection-scoped local intent and user
operations, reusing the application queue worker and connection lifecycle locks:

| Route suffix under `/api/calendar/connections/{id}` | Behavior |
|---|---|
| `PATCH /sync` with `{ "enabled": true/false }` | Explicit enable/pause; enabling requires a verified connection and stored credentials |
| `GET /status` | Connection metadata, queued/conflict/error/detached counts, and acknowledgment-based last-success information |
| `POST /sync-now` | One finite, connection-scoped queue pass; requires explicit enablement, without opting in blocks |
| `POST /blocks/{block_id}/opt-in` | Link only the selected whole block; reuse its retained identity on explicit re-opt-in after opt-out |
| `POST /blocks/{block_id}/opt-out` | Queue conditional remote deletion while preserving the local block/task; works while paused or authentication is required |
| `POST /links/{link_id}/detach` | Stop synchronization and retain remote content; explicit conflict resolution without overwriting either side |

Setup, verification, and enablement never select blocks automatically. Settings
identifies blocks by owner title and timed/all-day interval. Synced links have a
server acknowledgment; queued local saves, conflicts, errors, and detached
mappings remain distinct. Sync now can finish with pending/error/conflict work
and is not a blanket success assertion. Unlock/retry OS credential failures;
verify or replace credentials for authentication errors. Conflicts can be detached
instead of forcing remote overwrites. Disconnect removes credentials and keeps
remote copies; opt-out queues deletion instead. Setup never installs a server.
The app and user-managed server must be running and reachable; localhost serves
only the same device. CAL-07 adds live Radicale and packaged discovery checks;
native-vault and full desktop end-to-end synchronization remain unverified.

Schema v12 adds `last_synced_at` and explicit link `selection_state`
(`opted_in`, `opted_out`, `detached`). A real or reconciled remote acknowledgment
records naive-UTC sync time, preserved through later edits and conflicts.
Historical acknowledgment times remain unknown rather than being inferred from
`updated_at`; status distinguishes `observed`, `unknown`, and `never`. Settling a
never-attempted canceled create locally does not invent a successful remote sync.
Explicit selection state distinguishes completed opt-out cleanup, which permits
re-opt-in at the same URL/UID, from deliberate detach/disconnect, which requires
reconciliation. Pending/uncertain deletion keeps its immutable dispatch when a
newer explicit opt-in queues the next revision. Migration, checkpoints, and
offline recovery preserve these fields; portable export excludes sync metadata.

#### Outbound time-block synchronization contract (CAL-01)

This is the implementation contract for CAL-02 through CAL-07; connection APIs
and the durable dispatch queue exist, with explicit Settings controls in CAL-06.
ICS-01 remains a separate,
per-download snapshot operation. The first CalDAV phase publishes individual
local work blocks as independent `VEVENT` resources; inbound overlays,
calendar series, and bidirectional edits remain later work.

**Selection and ownership**

- Connection setup selects one writable event calendar. Recommend a dedicated
  **Meditations** calendar, but never create or select one without consent.
  Server installation and availability remain user-managed.
- Each block starts explicitly `unlinked`. Only an explicit per-block opt-in
  creates a durable link to that connection and selected calendar. Connecting,
  opening Calendar, downloading ICS, creating a block, or selecting a task/list
  does not opt in any block. Opt-in applies to the whole interval, independent
  of the displayed month, search, or terminal-task visibility.
- The initial outbound scope permits one active destination per block. Calendar
  changes cannot silently retarget existing links: resolve or explicitly detach
  old links before selecting a replacement destination. Bulk selection must
  identify the affected blocks before confirmation.
- SQLite owns local task and block data. A linked remote event is a published
  projection, instead of permission to modify local tasks. Remote changes never
  complete tasks, record focus, recalculate scores, or spawn recurring tasks.
  New blocks and completion-generated successors require their own opt-in.

**Event projection**

| Local source | Outbound representation |
|---|---|
| Block ID | The stable ICS-01 UUID5-derived UID, unchanged by edits, opt-out/re-opt-in, or reconnect |
| Timed start/end | UTC `DTSTART`/`DTEND` with `Z`; persist local naive-UTC values unchanged |
| Timed IANA metadata | `X-JOURNAL-TIMEZONE`; UTC instants remain authoritative |
| All-day start/end | `VALUE=DATE` labels with exclusive `DTEND`; no UTC conversion |
| Owner task title | Escaped `SUMMARY` |
| Owner task status | `canceled` maps to `CANCELLED`; todo, in-progress, and completed map to `CONFIRMED` |
| Block creation/update and task update | `CREATED` and `LAST-MODIFIED` follow ICS-01; `DTSTAMP` belongs to the persisted outbound revision |

The exact UID formula and serialization rules are defined in ICS-01 above.
Each resource contains one nonrecurring event, without `RRULE`, `RECURRENCE-ID`,
attendees, organizer, or scheduling invitations. Task deadlines, descriptions,
tags, journals, ratings, credentials, focus history, and task recurrence rules
are excluded. Whole-second precision and atomic validation failures follow
ICS-01; unrepresentable content enters an actionable error state instead of
changing local data. A retry of the same queued revision retains its payload
and timestamps; a later edit to the projected content creates a newer revision.
Task timestamp changes alone do not enqueue writes. When a mapped content field
changes, compute LAST-MODIFIED from the current source timestamps.

**Lifecycle and remote effects**

| Local action | Required outbound effect |
|---|---|
| Edit a linked block's interval, kind, zone, or task association | Update the same linked resource and UID from the latest owner/block projection |
| Rename the owner task | Update SUMMARY for its opted-in blocks only |
| Complete or reopen the owner | Keep the event and link; apply the status mapping without inferring attendance |
| Cancel the owner | Keep the event and publish CANCELLED; reopening restores CONFIRMED |
| Change deadline, list, hierarchy, focus, or task recurrence | No event-content change unless a mapped field also changes |
| Delete a block, task, or containing list with cascaded blocks | Persist linked-resource deletion intent in the local deletion transaction before rows disappear |
| Opt out of a linked block | Queue deletion of its linked event; keep local block/task data intact |
| Pause synchronization | Keep links and pending changes; perform no remote writes until resumed |
| Disconnect | Stop work, remove local credentials, and leave remote events in place; detach links only after in-flight outcomes are recorded or marked uncertain |

Deletion intent retains destination identity, UID, resource URL, last known ETag,
and local revision after the source row is gone. It survives offline operation
and restart until deletion is acknowledged or the user explicitly detaches it.
Opt-out remains visibly pending until resolved. Opt-in during pending deletion
must serialize reconciliation of the same identity instead of issuing an
independent create. Local edits and deletions commit without waiting for network
access; the worker runs only while the backend is running.

Disconnect is distinct from opt-out. Pending work must never resume merely
because credentials for a different server/calendar are entered. Retain detached
mapping and unresolved-outcome metadata without credentials for explicit
reconnection/recovery; disconnect itself performs no remote cleanup. Remote
cleanup, if offered, requires a separate confirmation identifying only linked
resources and must finish while authenticated, or report unresolved resources
before detachment. Deleting an entire remote calendar is outside this contract.

**Identity, failures, and conflict boundary**

- Persist connection/calendar identity, UID, resource URL, acknowledged ETag,
  local revision, and explicit sync state. Display `unlinked`, `pending`,
  `syncing`, `synced`, `conflict`, `error`, and `detached` link states; connection
  authentication state is separate. A local save is never presented as remote
  success. A newer local revision stays pending after an older write succeeds.
  Permit at most one in-flight mutation per link; subsequent writes use the
  latest acknowledged ETag. Only undispatched revisions may be coalesced. An
  opt-out during an uncertain create must resolve creation before cleanup.
- Creation uses a durable resource identity and creation precondition. Recover
  uncertain creates by inspecting that resource and UID before retrying; never
  create a second event to resolve an unknown result. Stable UID alone is
  insufficient evidence of ownership: an ICS-imported event with the same UID
  is a collision to resolve, instead of a resource to adopt or overwrite.
- Updates and deletes use acknowledged ETags and conditional requests. Remote
  edits or deletion of a linked event enter `conflict`; they do not silently
  overwrite local data or trigger unconditional recreation/deletion. Missing
  resources after an uncertain delete require reconciliation before success.
  Remote recurrence or other unsupported semantics also block automatic writes.
  Conflict resolution must offer explicit detachment that leaves the remote
  resource unchanged. Deliberate republishing of local content requires review
  of current remote state and fresh conditional-write protection; unsupported
  recurrence remains blocked instead of being flattened by that action.
- Authentication/network failures retain intent and expose retryable states.
  Only linked resources in the recorded destination may be changed. Reconnect
  to the same destination requires explicit reconciliation of detached mappings,
  uncertain writes, and remote changes before pending work resumes. A different
  destination requires fresh opt-in; previously published copies remain there.
- Backup restore preserves IDs and can roll back synchronization metadata. Before
  outbound writes after recovery, reconcile recorded links with the server;
  never assume a restored `synced` state or ETag is current. Concurrent writers
  from copied databases are outside the initial supported ownership model.

**Implementation acceptance scenarios**

CAL-02 through CAL-07 must test the following with a fake adapter before claiming
this contract is implemented: an unlinked block and ordinary deadline cause no
remote writes; opt-in publishes only the selected block; title/interval/kind
changes keep identity; completion leaves blocks and telemetry independent;
cancellation/reopening changes event status; offline opt-out and cascaded delete
retain recoverable deletion intent; pause and disconnect leave remote copies
intact; edits and opt-out during in-flight writes cannot resurrect events;
reconnect and uncertain creates cannot duplicate events; remote edits or
deletes block automatic writes; and timed/all-day values retain ICS-01 semantics
across DST. Server-specific interoperability and packaged connectivity require
separate verification under CAL-07.

#### Interoperability verification (CAL-07)

Ordinary `uv run pytest` collects only `backend/tests/`: adapters, vaults, AI,
and embeddings remain stubbed, with no real accounts or network services.
The explicit `calendar-test` dependency group pins Radicale 3.9.0 solely for
`uv run --locked --group calendar-test pytest integration/test_radicale.py`.
Radicale is not an application dependency and Journal never starts it in normal
operation. The integration fixture runs its real WSGI application over a bound
loopback socket with temporary collections, disposable Basic credentials, and
owner-only rights. Each test closes the server/thread and disposes its isolated
database. No OS vault or user database is accessed.

The live suite verifies principal/home/calendar discovery, authentication denial,
strong ETags, conditional create/update/delete and stale preconditions, selected
block publication, completion/cancellation, all-day exclusive ends, UTC instants
across both DST transitions, remote-edit conflicts, retained copies on disconnect,
interrupted writes, and offline create/edit/delete through actual SQLite
close/reopen, worker recreation, and explicit restart verification. Temporary WAL
databases retain dispatch rows across those connection lifetimes. Lost-response
checks cover creates, updates, and
deletes; strict payload-identity unit tests cover syntax-only server rewrites
without accepting semantic edits or preexisting resource collisions.

Setting `JOURNAL_TEST_SIDECAR` to the absolute frozen executable also runs the
existing isolated health/CRUD smoke with credential-bearing discovery against
that same local server, writable VEVENT capability checks, and invalid-password
rejection. It creates/removes only a disconnected local draft; it does not
connect to an OS vault or inject a test credential-store bypass into production.
The release workflow requires this suite after building the exact sidecar and
before Tauri packaging or publication. Native vault access and full desktop
outbound synchronization are not covered by this packaged discovery check.
Nextcloud and Baïkal remain unverified; no provider-wide compatibility is claimed.

[Calendar synchronization guide](docs/calendar-sync.md) documents optional
user-managed Radicale setup, user-level service operation, device reachability,
explicit publication, recovery, and unsupported recurrence.

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

Settings forms derive untouched fields from query data and keep edited fields
as local drafts, including edits made before the initial response. Background
refetches preserve those drafts. Successful save/reset responses update the query
cache and release acknowledged field overrides; edits made to a field while the
request is pending remain local. Acknowledged fields then follow later query
updates again. An acknowledged API key is cleared even if another field was
edited during the request, while a newer key draft is retained. Preference saves
likewise release their draft only when there is no newer edit. API keys are never
prefilled, and a blank key input leaves the stored key unchanged on save.

### 7.2 Review runners and deterministic scoring

The executable implementation lives in source instead of duplicated example agents:

| Responsibility | Implementation |
|---|---|
| Model construction, settings overrides, retry wrapper and readable errors | `backend/app/ai_factory.py` |
| Output schemas, prompt defaults, bounded prompt rendering and runners | `backend/app/agents.py` |
| Target-period context, configured request models, review persistence and stream lifecycle | `backend/app/ai_orchestration.py` |
| HTTP routes and request validation | `backend/app/routers/agents.py` |
| Usage recording | `backend/app/ai_usage.py` |
| Deterministic metrics, score and effective target | `backend/app/telemetry.py`, `backend/app/scoring.py`, `backend/app/score_service.py` |
| Scheduled catch-up and durable job ownership | `backend/app/review_scheduler.py` |

Agents use PydanticAI's `output_type=` and read `result.output`. Review runners
accept `system_prompt=` and `on_usage=` overrides. The daily runner clips today's
text to 4,000 characters and each of six earlier excerpts to 500 characters;
period-specific context selection remains in the orchestration module. HTTP
adapters and scheduled catch-up call the same review workflows; daily streaming
and non-streaming paths share preparation and snapshot persistence. Briefing
paths share their data projection and final payload construction. The shared
`DailyScoreResponse` schema lives in `app/schemas.py`. The model supplies
narrative and a bounded nudge instead of computing scores or trends. Streaming
uses the shared SSE protocol described in §6.3.

### 7.3 Task decomposition and fast-tier features

`run_task_decomposition` uses the configured main model and returns validated
subtask drafts. Capture, briefing, Q&A, and editor assists use the fast model tier,
falling back to the configured main tier. Callers MUST load settings and prompt
overrides before building request models. Calling `create_agent_model()` without
settings reads environment defaults only and bypasses the user's saved provider.
See §6.3 for endpoint and context contracts.

---

## 8. Historical implementation roadmap

These completed phases preserve original delivery intent and branch names. Their
day estimates and feature descriptions are historical, not current acceptance
evidence. Use §§2–7 for implemented contracts and the local
[feature backlog](features/todo.md#review-follow-up-backlog) for remaining work.

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

## 9. Development commands and dependencies

Run each block from the repository root. `backend/pyproject.toml` and
`frontend/package.json` declare dependencies; `backend/uv.lock` and
`frontend/package-lock.json` resolve versions. Do not install from historical
example manifests. `./setup.sh` and `./dev.sh` provide the combined development
workflow described in [Quick start](README.md#quick-start-dev).

```bash
# Backend, Python 3.12+
(cd backend && uv sync --locked)
(cd backend && uv run pytest)
(cd backend && uv run uvicorn app.main:app --reload)
```

```bash
# Frontend, Node ^20.19.0 or >=22.12.0
(cd frontend && npm ci)
(cd frontend && npm run test)
(cd frontend && npm run build)
(cd frontend && npm run lint)
(cd frontend && node --test scripts/test-timezones.node-test.mjs)
(cd frontend && npm run test:timezones)
(cd frontend && npm run dev)
```

Run servers in separate terminals. Ordinary endpoint tests use in-memory SQLite;
file-backed migration, backup, restore, locking, and WAL tests use disposable
fixtures. AI/embedding calls are stubbed. Optional local Radicale integration
requires the separate `calendar-test` group; see §6.4 and the
[developer verification guide](docs/calendar-sync.md#developer-verification).
Desktop builds additionally require Rust, system libraries, and a frozen backend;
see [desktop setup](README.md#desktop-app-tauri-v2). Test counts belong in dated
verification reports instead of command comments.

---

## 10. Git Workflow, Branching Strategy & Project Hygiene

To ensure clean development, isolation of complex AI/frontend features, and easy rollback, the project enforces a strict Git branching workflow.

### 10.1 Branch Structure

* **`main`**: The single source of truth. Always deployable and buildable. Direct commits to `main` are allowed for docs and one-line fixes only.
* **`feat/<feature-name>`**: Dedicated branch for every feature or architectural phase.
  * `feat/backend-data-layer`: FastAPI models, SQLite schema, CRUD routes.
  * `feat/task-engine-ui`: Quick-add bar, task list, Kanban views, optimistic UI.
  * `feat/focus-tiptap-journal`: TipTap block editor, daily activity embeds, focus clock.
  * `feat/ai-compaction-agents`: Daily, weekly, monthly PydanticAI rollups (historical branch; scheduling now uses the backend lifecycle worker).
  * `feat/ai-provider-config`: UI & API settings for custom `base_url` and `api_key`.
  * `feat/rag-desktop-polish`: sqlite-vec search, Tauri v2 desktop integration.
* **`fix/<bug-name>`**: Targeted fixes for unexpected behavior or edge-case regressions.
* **`refactor/<component>`**: Non-functional refactoring or performance optimization.

### 10.2 Feature Branch Lifecycle Workflow

For every new feature, follow this standard cycle from the repository root.
Preserve unrelated worktree changes; stage only intended files. Obtain an
independent subagent review and resolve blockers before merging a non-trivial
branch. Review and applicable verification precede the final commit and merge.

```bash
# 1. Ensure main is clean and up to date
git checkout main
git pull origin main

# 2. Branch off into an isolated feature branch
git checkout -b feat/task-engine-ui

# 3. Verify the intended changes before committing
(cd backend && uv run pytest)
(cd frontend && npm run test)
(cd frontend && npm run build)
(cd frontend && npm run lint)
(cd frontend && npm run test:timezones)

# 4. Stage intended files and commit after independent review
# Replace <files> with explicit paths; preserve unrelated changes
git add <files>
git commit -m "feat(tasks): add chrono-node inline NLP parsing to quick-add bar"

# 5. Merge feature back into main (using --no-ff or PR to preserve history)
git checkout main
git merge --no-ff feat/task-engine-ui -m "merge: feat/task-engine-ui into main"

# 6. Clean up the merged branch
git branch -d feat/task-engine-ui
```

### 10.2.1 Pull-request checks

Branch pushes and pull requests run `.github/workflows/ci.yml` independently of
release tags. Its required-check candidates are `Backend tests`, `Frontend test`,
`Frontend build`, `Frontend lint`, and `Frontend timezones`. Backend checks use
Python 3.12 and the uv lockfile; frontend checks use Node 24 and `npm ci`. The
frontend test/build/lint matrix runs all three checks even if one fails. The
independent timezone job runs the existing seven-zone `npm run test:timezones`
script, retaining the six baseline zones plus Australia/Lord_Howe's half-hour
DST coverage. Calendar range, projection, time-grid, time-edit, Year and mode
integration suites are included. Node runner tests verify all zones are invoked
and failures, signal termination and process-start errors produce failed checks.
Tests retain isolated SQLite fixtures and stubbed AI/embedding calls; CI disables
scheduled reviews and Hugging Face downloads.
A repository administrator must require these five checks in the target branch's
ruleset or branch protection to enforce merge blocking. The release workflow
calls this workflow through `workflow_call` and waits for all five checks.

### 10.2.2 Cross-feature contract coverage

Dedicated `cross-feature-contracts.test.tsx` and
`test_cross_feature_contracts.py` suites connect existing feature boundaries.
The frontend suite uses real Sidebar/Header navigation and the canonical task
cache across List, Board, Calendar and Matrix. It retains Board's scoped Done
policy and Matrix's independent All scope with shared search. Pending completion
failure is checked before refetch resolves, followed by retry and cross-view
placement checks. This extends QA-01's combined flow at the component/API level;
it does not replace browser or packaged-desktop acceptance.

Backend endpoint compositions check chart windows against lifetime streaks,
recurring completion against journal/activity/score telemetry, historical review
reruns after newer rollups, and local journal/FTS atomicity during indexing
failure and recovery. Clocks are fixed; AI and embeddings are stubbed; databases
are isolated. Local save and recovered indexing do not imply remote sync
acknowledgement. The frontend contract suite is included in the seven-zone
timezone runner, enforced by the independent `Frontend timezones` CI/release check.

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
   tests plus frontend tests, build, lint, and timezone regressions to pass. The
   bundle job then builds inside an **`ubuntu:22.04` container** on the current runner
   (the 22.04 runner label retired Sept 2026): glibc floor stays at 2.35 and
   old binutils avoids the `.relr.dyn`/old-strip breakage. Python 3.12, pinned uv,
   and the locked `packaging` dependency group build the PyInstaller sidecar.
   Before Tauri runs, `backend/scripts/smoke_sidecar.py` launches that exact
   executable on an OS-assigned loopback port. Health and linked list/task CRUD
   must pass against an isolated temporary database. The smoke check also downloads
   a backup containing linked sentinel records, stops the server, and invokes the
   same frozen executable's offline restore into a separate disposable database;
   integrity, foreign keys, and restored relationship/content checks must pass.
   The harness isolates its
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
  entry point so it needs an explicit hiddenimport; `sqlite_vec`'s loadable
  extension (`vec0.so` / `vec0.dylib` / `vec0.dll`) needs explicit
  `collect_dynamic_libs` search patterns. Default Unix patterns require a `lib`
  prefix and omit `vec0.so`; `collect_data_files` also excludes shared libraries.
  Missing sqlite-vec can leave startup in keyword-only mode while offline restore
  fails, so frozen acceptance must exercise recovery, not only health/CRUD.
  onnxruntime also needs `collect_dynamic_libs`.
- **Frozen-runtime traps** (both crashed the packaged app on real machines):
  pydantic plugins (logfire, via pydantic-ai) call `inspect.getsource()` —
  impossible in frozen apps, so `sidecar_main.py` sets
  `PYDANTIC_DISABLE_PLUGINS=1` before any import; and deps reading their
  version via `importlib.metadata` (genai_prices, …) need their dist-info
  shipped — the spec copies ALL distributions' metadata. PyInstaller's
  `build/` analysis cache silently ignores spec data changes on rebuild —
  `build-sidecar.sh` deletes it first.
