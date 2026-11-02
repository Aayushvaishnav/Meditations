# Project improvement backlog

Created: 2026-10-10
Source: project review of Journal / Meditations and local-first calendar integration options.

Checkboxes track implementation progress. Remaining unchecked items are pending. `plan.md` remains the authoritative architecture document.

## Priorities and execution order

- **P0:** Correctness fixes that protect journal content, task continuity, and reliable reviews.
- **P1:** Data recovery, schema evolution, testing, and release confidence.
- **P2:** Scheduling semantics, calendar usability, and portable ICS export.
- **P3:** ICS import/subscriptions, optional CalDAV sync with user-managed servers, and optional local calendar bridges or webhook automation.

Recommended order: P0 fixes → migrations and backup → scheduling model → ICS export. ICS import/subscriptions and CalDAV are later, optional extensions; neither blocks the ICS milestone.

## Calendar integration recommendation

- Keep the application usable entirely offline, with SQLite as the source of truth for local tasks and time blocks. Calendar connections are optional.
- Remove Google Calendar API, Google Tasks, desktop OAuth, cloud notification relays, and provider-specific cloud APIs from the roadmap. Calendar integration introduces no app account or sign-in requirement.
- Start with **iCalendar (`.ics`) export** for portable calendar files; add import and optional read-only subscriptions separately. A file export is a snapshot, not live synchronization.
- Defer **CalDAV synchronization** until after the ICS milestone; Journal would act only as a client of a user-managed server. Support a server URL plus username/password or app password for servers that allow it; OAuth-only configurations are outside scope. CalDAV itself does not eliminate server authentication.
- Leave **Radicale entirely optional and user-managed**: Journal does not bundle, install, start, or manage it. Users may run it as a user-level service on their computer or use an existing server. Nextcloud Calendar and Baïkal are alternative servers for future interoperability checks.
- Other calendar clients connect to the same server, rather than directly to each other. Examples include Thunderbird and Evolution on desktop, Apple Calendar, and Android calendars through DAVx⁵. Actual event/task capabilities vary by client.
- A server bound to localhost is accessible only on that machine. Phone or other-device sync needs a reachable server, such as a home server or one accessed over a private network.
- Consider a **Linux desktop calendar bridge** through Evolution Data Server or Akonadi only if sharing existing desktop calendars is needed; these are platform-specific alternatives, not dependencies of the core app.
- Keep calendar events (`VEVENT`) separate from task synchronization (`VTODO`); CalDAV can support both, but task hierarchy, completion, recurrence, and client support require their own mapping.
- Keep outgoing webhooks as optional automation. They are unnecessary for ICS export or ordinary CalDAV polling, and the desktop needs no public callback endpoint.

## P0: Correctness and operational fixes

- [x] **FIX-01: Cancel or replace obsolete journal saves after undo.**
  - Files: `frontend/src/components/journal-editor.tsx`.
  - Trigger: load markdown A, edit to B, then undo to A before the 700 ms debounce expires; B is still saved.
  - Reconcile the pending payload and timer before the baseline early-return. Preserve legitimate mood/energy changes when text returns to its baseline.
  - Acceptance: type → undo and delete → undo persist the editor's final content; rating changes still save; visiting an empty day creates no entry.
  - Add dedicated fake-timer regression tests for undo, ratings, and day switches; retain payload freezing at schedule time.

  - Implemented on `fix/journal-obsolete-saves`; real TipTap component tests with fake timers in `frontend/src/components/journal-editor.test.tsx` cover edit/delete undo, staggered deadlines, both ratings, rating clearing, empty visits, programmatic loads, and day navigation.
  - Validation: 23 frontend tests pass; production build passes; lint has 10 existing warnings and no errors. Backend: 129 passed, known QA-01 filter test failed. Subagent review found no FIX-01 blockers.
  - Follow-up outside the before-debounce trigger: undoing to the loaded baseline after an edit has already saved can still leave the saved edit persisted.

- [x] **FIX-02: Give recurring task series and occurrences stable identity.**
  - Files: `backend/app/models.py`, `backend/app/routers/tasks.py`, `backend/app/recurrence.py`; corresponding frontend task types.
  - Trigger: complete identically named daily recurring tasks in two lists with matching due times; only one next instance is created.
  - Replace title/rule/date-based cross-task duplicate detection with recurrence-series and occurrence identity. Preserve completed instances and their telemetry.
  - Acceptance: independent series each produce a next instance; uncomplete/recomplete produces no duplicate within a series; renaming or moving a task does not change its series identity.
  - Coordinate persistent schema changes with DATA-01; test the behavior without real databases or network calls.
  - Implemented on `fix/recurrence-identity`: `backend/app/recurring_tasks.py` owns successor creation; server-managed series IDs and zero-based occurrence numbers have a unique SQLite index. Recompletion cannot duplicate an existing successor regardless of edits or status; finished rows and focus history remain intact. Frontend task types and optimistic creation include identity fields.
  - `backend/tests/test_recurrence_identity.py` has 16 regression tests; the original cross-list collision and completed-successor duplication were both demonstrated failing before the fix. Legacy recurring rows become independent series because historical lineage cannot be recovered safely; deletion and rule-change semantics are documented in `plan.md` and `backend/README.md`.
  - Validation: 36 focused recurrence/migration tests pass; full backend suite has 151 passed and two pre-existing date-dependent failures (`test_task_filters`, `test_monthly_rollup_from_weeks`), both reproduced against unchanged HEAD. Frontend: 23 tests pass, build passes, lint has 10 existing warnings and no errors. Subagent review found no blockers; independent-connection concurrency regression coverage remains a non-blocking follow-up.

- [x] **FIX-03: Keep journal/rollup sources and search indexes consistent.**
  - Files: `backend/app/routers/journal.py`, `backend/app/routers/agents.py`, `backend/app/search.py`.
  - Trigger: source data commits and indexing fails afterward; search keeps old content or deleted-document results.
  - Use a single transaction for compatible source/index writes, or a durable indexing outbox with explicit pending state. Keep FTS available when semantic embeddings are unavailable.
  - Make full reindex remove orphan records and replace stale content. Make startup recovery detect unfinished or stale indexing work instead of checking document existence only.
  - Acceptance: failure injection during create, update, and delete leaves either a consistent transaction or recoverable queued work; recovery returns current content and removes ghost results.
  - Implemented on `fix/search-consistency`: journal save/delete, capture appends, and weekly/monthly rollups commit sources and FTS together. Embedding inference failures preserve current FTS; storage failures roll back the transaction. Schema v3 adds durable `search_vector_state` (`pending`/`ready`) so extension outages cannot hide stale vectors.
  - Startup reconciliation repairs missing/stale/duplicate FTS, removes FTS/vector/state orphans, and retries pending or missing vectors. Full reindex replaces derived indexes, including orphan cleanup. Both acquire the SQLite writer lock before reading sources and commit atomically; healthy vectors avoid repeated inference.
  - Regression coverage: `backend/tests/test_search_consistency.py` and `backend/tests/test_rollup_search_consistency.py`, plus v3 rollback/retry coverage in `backend/tests/test_migrations.py`; 45 focused tests pass. Initial failure injection reproduced create/update/delete divergence, stale startup content, reindex ghosts, and embedding failures before the fix.
  - Validation: full backend suite 189 passed with the two existing QA-01 date-dependent failures; frontend 23 tests and build pass; lint has 10 existing warnings and no errors. Final subagent review found no blockers. A persisted independent-connection concurrency regression remains a non-blocking follow-up; the reviewer verified the no-op write lock against a competing connection.

- [x] **FIX-04: Use the configured focus target in every score calculation.**
  - Files: `backend/app/routers/agents.py`, `backend/app/routers/scores.py`, `backend/app/routers/preferences.py`, `backend/app/scoring.py`.
  - Trigger: two hours of focus with a two-hour target produces a live weighted score of 50.0, but a review score of 32.5 using the default four-hour target.
  - Centralize effective target resolution and deterministic score calculation for live scores, daily rollups, streaming daily rollups, and weekly fallback scoring.
  - Acceptance: identical metrics, target, and nudge produce identical scores across these paths; non-default preferences are covered by regression tests.
  - Define how a later target change affects historical reviews; distinguish persisted review snapshots from live recalculation in the API/UI.
  - Implemented on `fix/configured-focus-target`: `backend/app/score_service.py` resolves targets and delegates deterministic scoring for live/daily/streaming/weekly fallback paths. Final review persistence uses the same scorer, including the nudge and rubric. Preferences share target resolution; saving preferences invalidates live score caches.
  - Reviews remain snapshots until re-run; live scores use current metrics/target and any saved nudge. API `score_basis` and `saved_review_score` distinguish the two, and the journal card shows the saved score separately. Contracts documented in `plan.md` and `backend/README.md`.
  - Regression coverage: 21 tests in `backend/tests/test_configured_focus_target.py` and a frontend preference-cache hook test; both scoring mismatch and stale-cache failures reproduced before fixes.
  - Validation: backend 210 passed with the two existing QA-01 date-dependent failures; frontend 24 tests and build pass; lint has 10 existing warnings and no errors. Subagent review found no blockers; activity-change snapshot and nudge-boundary integration coverage remain non-blocking follow-ups.


- [x] **FIX-05: Make scheduled reviews reach the correct application database.**
  - Files: `systemd/`, `frontend/src-tauri/src/lib.rs`, `backend/sidecar_main.py`; backend scheduling module if introduced.
  - Trigger: installed timers POST to port 8000, while the packaged desktop backend uses an ephemeral loopback port; jobs fail or reach a separate development database.
  - Integrate review scheduling with the backend/application lifecycle, or use explicit runtime discovery tied to the intended instance. Remove reliance on the development port for packaged operation.
  - Pass explicit target days/weeks/months; persist catch-up state so delayed execution reviews the intended period instead of the execution-time default.
  - Define local-time versus UTC period boundaries while preserving naive-UTC datetime storage.
  - Acceptance: packaged-app jobs reach its database; a concurrent dev backend is untouched; restart and missed weekly/monthly runs select the correct periods without duplicate processing.
  - Implemented on `fix/review-scheduling`: `backend/app/review_scheduler.py` runs inside the backend lifecycle using its session factory, with explicit period arguments and no HTTP/port discovery. Packaged startup enables it; standalone/dev defaults off (`JOURNAL_SCHEDULED_REVIEWS=true` opts in). Shutdown cancels the worker before engine disposal.
  - Schema v4 persists `review_jobs` (`pending`/`completed`/`skipped`). Saved outputs recover interrupted ledger completion without repeating the model call. Work is ordered by UTC closing date, with daily → weekly → monthly tie-breaking, preserving aggregation inputs and earlier contextual summaries. Months wait for their final Monday-owned week to close. Terminal jobs remain snapshots; historical edits require manual reruns.
  - Removed legacy HTTP unit files; `systemd/install.sh` now retires installed user timers/services. Existing installations must run it to stop old port-8000 calls. Updated `plan.md`, root README, and backend README with UTC boundaries, catch-up costs, one-backend-per-database ownership, and migration instructions.
  - Regression coverage: scheduler unit/integration tests cover explicit targets, independent packaged/dev databases, boundaries/year rollover/leap years, retries, deleted sources, all-tier output persistence, interruption after each output commit, multi-month context ordering, worker lifecycle, sidecar opt-out, and idempotent timer retirement; migration tests cover v4 rollback/retry. The legacy-port regression and multi-month context failure were demonstrated before their fixes.
  - Validation: 32 focused scheduler/migration tests pass; full backend 234 passed with the two existing QA-01 date-dependent failures. Frontend 24 tests and build pass; lint has 10 existing warnings and no errors. Subagent review's context-ordering finding was fixed and follow-up review found no blockers. Packaged binary launch and a real systemd user-manager run remain unverified; tests use isolated in-memory databases and a stubbed systemctl.

- [x] **FIX-06: Resolve the monthly rollup default before parsing.**
  - File: `backend/app/routers/agents.py`.
  - Trigger: omit `month` on a date other than the first; `None.split()` causes HTTP 500.
  - Implement the documented default explicitly: current month ordinarily, previous month on the first; retain explicit `previous` and `YYYY-MM` support.
  - Acceptance: omitted month works on the first and other dates; January rollover works; invalid input returns HTTP 422; a valid period with no summaries returns the appropriate empty-data response instead of HTTP 500.
  - Implemented on `fix/monthly-rollup-default`: resolve the omitted current month before parsing, preserve first-day/`previous` behavior, and validate explicit `YYYY-MM` syntax and calendar bounds. UTC defaults and HTTP 422/404 contracts are documented in `plan.md`.
  - Regression coverage: 31 controlled-date, in-memory tests in `backend/tests/test_monthly_rollup_defaults.py`, with model/embedding stubs, cover period selection, January rollover, leap years, persistence, exclusion of neighboring months, invalid input, and missing summaries. Before the fix, nine cases failed, including the reported `None.split()` crash.
  - Validation: backend 265 passed with the two existing QA-01 date-dependent failures; frontend 24 tests and build pass; lint has 10 existing warnings and no errors. Subagent review found no blockers; a near-midnight UTC boundary test remains a non-blocking coverage follow-up.

## P1: Data ownership and recovery

- [x] **DATA-01: Introduce versioned SQLite schema migrations.**
  - File: `backend/app/db.py`; add a dedicated migration directory/module.
  - Replace schema-upgrade reliance on `SQLModel.metadata.create_all()` with versioned upgrades; retain a clear fresh-install path.
  - Establish a baseline for existing installations and migrate before normal requests or scheduled jobs run.
  - Acceptance: fresh databases and existing-schema fixtures reach the same schema without data loss; failed upgrades leave a recoverable database and actionable error.
  - Implemented alongside FIX-02: `backend/app/migrations/` freezes the pre-identity schema as v1 and adds/backfills recurrence identity as v2. `PRAGMA user_version` records progress; explicit `BEGIN IMMEDIATE` makes the pending migration batch atomic before search/API initialization, and newer schema versions are refused.
  - `backend/tests/test_migrations.py`: seven in-memory tests cover fresh/legacy/model schema equivalence, task/list/focus preservation, independent identity backfill, repeat startup, uniqueness, newer-version refusal, and injected failures that roll back DDL/data/version before successful retry. Automatic pre-upgrade backup checkpoints remain DATA-03.

- [x] **DATA-02: Add a SQLite-consistent backup operation.**
  - Use SQLite's backup mechanism or an equivalent consistent snapshot instead of copying only the live main database file while WAL writes are active.
  - Expose backup from Settings and document the packaged/dev database locations.
  - Acceptance: a backup taken during writes restores committed tasks, journals, ratings, reviews, and focus history consistently.
  - Implemented on `feat/database-backup`: `backend/app/backup.py` uses SQLite's online backup API against the active engine. `POST /api/backup` delivers a private staged snapshot and cleans up after delivery, errors, and cancellation. Cancellation drains the SQLite worker before releasing its connections.
  - Settings has a self-contained backup section with browser downloads and native desktop save dialogs. First-party Tauri dialog/filesystem plugins use narrowly scoped permissions, exclusive creation, and Unix mode `0600`; the native minimum Rust version is now 1.90. Backups include stored credentials; UI, root/backend READMEs, and `plan.md` document sensitive contents, database locations, committed-state semantics, and deferred restore.
  - Regression coverage: nine backend tests in `backend/tests/test_backup.py` cover source/relationship/schema/search preservation, temporary cleanup, repeated cancellation, and concurrent committed/uncommitted WAL writes. Ordinary fixtures remain in-memory; only the WAL regression uses an isolated pytest `tmp_path` database. Seventeen frontend API/component tests cover binary responses, active sidecar URLs, pending state, browser resource cleanup/errors/retries, and native cancellation/errors/exclusive writes.
  - Validation: backend 274 passed with the two existing QA-01 date-dependent failures; frontend 41 tests and production build pass; lint has 10 existing warnings and no errors. Locked native `cargo check` passes. A real Chromium download against an isolated in-memory backend was opened with SQLite and its task/journal/ratings verified; the backup section was inspected at desktop and minimum desktop widths in dark/light themes. Final subagent review found no blockers after fixing cancellation lifetime and browser error handling.
  - Remaining verification: a packaged desktop native-save smoke test is unverified. Native write failures can leave an incomplete new file and report that explicitly. Restore/pre-upgrade checkpoints remain DATA-03. npm audit reports 19 advisories elsewhere in the dependency graph, with no findings for the new official plugins.

- [x] **DATA-03: Add verified restore and pre-upgrade recovery.**
  - Depends on DATA-01 and DATA-02.
  - Validate backup integrity and schema compatibility; preserve the current database before replacement; coordinate restore with database connections and the desktop sidecar.
  - Create a recovery checkpoint before schema upgrades and document failure recovery.
  - Acceptance: restoring a known fixture preserves source data, supports search reconstruction, and offers a recoverable path after an incompatible backup or failed upgrade.
  - Implemented on `feat/database-recovery`: `backend/app/recovery.py` provides offline `restore BACKUP --database DESTINATION` through `python -m app.recovery` or the packaged sidecar. A private staged SQLite snapshot is checked for integrity, relationships, versioned columns/FKs/unique-index semantics, and schema compatibility, then migrated before replacement. The input backup stays unchanged. Current databases receive a verified recovery checkpoint before WAL checkpointing and atomic replacement; normal startup reconstructs missing search indexes.
  - `backend/app/database_lock.py` enforces cooperative per-database ownership across backend startup/shutdown and offline restore. Quit the desktop tray process before restoring. Startup failures clean up; cancellation drains disposal/checkpoint workers before releasing ownership, and disposal errors retain state for retry. Existing file databases receive private pre-upgrade checkpoints before pending DDL; checkpoint failures abort upgrades. Root/backend READMEs and `plan.md` document commands, recovery, retention, sensitive contents, and advisory-lock limitations.
  - Regression coverage: 36 tests across `test_recovery.py`, `test_database_lock.py`, `test_recovery_checkpoints.py`, `test_restore_roundtrip.py`, and `test_sidecar_recovery.py` cover legacy/current restore, incompatible/corrupt backups, WAL snapshots, replacement/migration failures, permissions, process lock contention, cancellation, all-domain backup round trips, and search reconstruction with stubbed embeddings. Review's disposal-lifetime blocker and unique-index collation gap were reproduced with failing tests, corrected, and verified by follow-up review with no remaining blockers.
  - Validation: backend 313 passed; frontend 176 passed; production build passes; lint has 9 existing warnings and no errors. Both CLI help paths run successfully. Native frozen-sidecar restore and Windows locking remain unverified; older apps, hard-link aliases, and external SQLite tools do not participate in the advisory lock. Offline restore intentionally has no Settings button; checkpoints require user-managed retention.

- [x] **DATA-04: Add portable data export.**
  - Export journal entries as Markdown and structured task/focus/habit/review data in a documented format; read related records from one consistent database snapshot.
  - Keep credential values out of ordinary exports; define date/time and stable-ID semantics.
  - Acceptance: exports can be inspected without the app and preserve content, ratings, task status, scheduling metadata, and associations; concurrent-write tests confirm related records come from the same snapshot.
  - Implemented on `feat/portable-data-export`: `backend/app/data_export.py` and `routers/data_export.py` provide `POST /api/export`, returning a private staged ZIP with exact dated Markdown journals, nine explicitly allowlisted JSON source collections, a versioned manifest, and a field/date/identity format guide. One explicit SQLite read transaction pins all related records; collections retain primary-key ordering, existing IDs/FKs, recurrence identity, fractional UTC timestamps, ratings, scheduling values, and saved review snapshots. No migration, telemetry recalculation, or external service is involved.
  - The archive excludes the entire settings table (including saved credentials/prompts), AI usage, review jobs, and search indexes/state; user-authored text remains unchanged and may contain private information. Root/backend/frontend READMEs and `plan.md` document the format, committed-state/privacy boundaries, and distinction from restorable SQLite backups. No ZIP importer is implied.
  - Settings has a separate portable-export section with browser downloads and private exclusive native saves. `lib/file-download.ts` shares delivery mechanics while backup/export wrappers and hooks retain independent states and object-URL lifetimes. Existing backup behavior is retained; its footer now points to offline restore. Pending/cancel/success/error/retry states are covered without adding dependencies or native permissions.
  - Regression coverage: nine backend tests in `test_data_export.py` cover all domains, exact Unicode/frontmatter/line-ending Markdown, rating-only entries, exclusions, stable IDs, precision, empty archives, cleanup/failures/cancellation, and an isolated WAL concurrent writer proving related records share a snapshot. Twelve export component tests and an additional binary API test cover browser/native routing, privacy-safe exclusive writes, failures/retries, unmount lifetimes, and independence from backup; all 12 existing backup tests still pass.
  - Validation: backend 322 passed; frontend 189 passed; production build passes; lint has 9 existing warnings and no errors. Real Chromium with an isolated in-memory backend downloaded/inspected the ZIP, verified credential-canary exclusion, keyboard activation, error/retry, and no page errors or horizontal overflow at 1440px dark and 1024px light. Independent code review found no blockers; visual review returned ship with no material fixes. Native packaged save-dialog smoke remains unverified.

## P1: Tests, CI, and release confidence

- [x] **QA-01: Remove wall-clock dependence from the failing task-filter test.**
  - File: `backend/tests/test_lists_tasks.py`, `test_task_filters`.
  - Freeze the router clock or use dates derived from a controlled clock instead of assuming September 15, 2026 is always in the future.
  - Acceptance: overdue, boundary-time, completed, and canceled filtering assertions pass consistently regardless of the execution date.
  - Additional date-dependent baseline failure confirmed during FIX-02: `backend/tests/test_agents.py::test_monthly_rollup_from_weeks` chooses this week's Monday and the following Monday, so month-end execution can place the second fixture outside the requested month. Use a controlled month/week fixture in a follow-up; this failure also reproduces on unchanged HEAD.
  - Implemented on `fix/date-independent-tests`: task filtering uses two controlled router clocks with future dates relative to each; assertions cover active/terminal statuses, unscheduled tasks, strict overdue/due-before boundaries, and inclusive due-after boundaries. Monthly aggregation uses two explicit September Mondays and verifies both weekly outputs reach the agent.
  - Both original failures were reproduced before edits. Validation: full backend suite passes; 41 frontend tests and production build pass; lint has 10 existing warnings and no errors. Subagent review found no blockers. Application behavior is unchanged.

- [x] **QA-02: Add journal component lifecycle tests.**
  - Cover initial content loading, empty-day visits, debounced saves, undo, rating changes, day navigation, section changes, and late asynchronous activity results.
  - Verify that programmatic loads do not schedule unintended saves and that an operation started on one day cannot modify another day.
  - Use a dedicated component test file with fake timers and stubbed API calls.
  - Implemented on `test/journal-lifecycle`: `frontend/src/components/journal-editor.test.tsx` now has 27 real-TipTap tests covering delayed loads, empty visits, debounce/undo/ratings, navigation, section exit/unmount, StrictMode, and deferred activity completion. Local-noon fake time also passes under `TZ=Pacific/Kiritimati`; the real slash extension is retained in tests.
  - Regression tests exposed missing exit flushes, stale activity insertion, wrong-day writes while loading, and an unconsumed initial navigation command. The editor now flushes frozen payloads on lifecycle exits, invalidates departed activity requests, disables editing until the selected entry loads, and consumes external navigation commands once. Retained extension callbacks forward to current handlers.
  - Validation: backend 277 passed; frontend 58 passed; production build passes; lint has 9 existing warnings and no errors. Review caught a stale slash callback introduced by the loading guard; a failing regression reproduced it, and follow-up review confirmed the correction with no blockers. `plan.md` documents the lifecycle contracts. Calendar-popup navigation and real mutation/cache integration remain non-blocking coverage follow-ups.

- [x] **QA-03: Test task-cache concurrency and domain invalidation.**
  - File: `frontend/src/hooks/api.ts`; dedicated hook tests.
  - Cover overlapping optimistic updates with mixed success/failure, query cancellation, rollback, and mutation settlement.
  - Verify that task/focus changes refresh dependent journal activity, live scores, and insights as appropriate; preserve the canonical `['tasks']` cache.
  - Acceptance: one failed mutation does not erase another successful change, and recently visited telemetry screens do not retain stale metrics.
  - Implemented on `test/task-cache-concurrency`: `frontend/src/hooks/task-cache.ts` owns per-QueryClient snapshot/replay batches. Failed changes roll back independently; successful overlapping changes remain visible. Task refetch waits for the batch to settle; independent refetches preserve pending edits over fresh server data, and canceled responses cannot change rollback snapshots. List removal shares task coordination; optimistic deletion includes all descendants, and creation preserves descriptions and replaces temporary IDs.
  - Task/focus/capture mutations refresh activity, daily scores, and insights across cached dates/ranges. Focus summaries and capture's journal metadata refresh separately; task-only changes do not invalidate journal-day metadata. `plan.md` documents the contracts.
  - Regression coverage: 19 concurrency hook tests and 14 domain-invalidation tests use deferred API responses and real React Query clients, including mixed outcomes/orderings, same-task fields, empty caches, cancellation, refetch, recursive deletion, list removal, focus overlap, and active/inactive telemetry caches. Before implementation, 18 of the initial 24 tests failed. Review's confirmed-create refetch edge case was reproduced with an additional failing test and corrected.
  - Validation: backend 277 passed; frontend 91 passed; production build passes; lint has 9 existing warnings and no errors. Initial and follow-up subagent reviews found no blockers. Direct window-focus/reconnect events, cross-QueryClient isolation, and overlapping mutations to the separate lists cache remain non-blocking coverage/follow-up work.

- [x] **QA-04: Add calendar, date, and timer regression coverage.**
  - Cover calendar filtering, selected-list creation, rescheduling, date-only versus timed values, UTC parsing, local-day boundaries, and DST transitions.
  - Cover focus-timer behavior during background throttling and suspend/resume; define elapsed-time semantics and fix any demonstrated drift.
  - Acceptance: tests assert the chosen scheduling/timer contracts without dependence on real time or a particular host timezone.
  - Implemented on `test/calendar-date-timer`: dedicated date, calendar, header, shared-selector, nested-list, timer-store, and timer-component regressions use controlled clocks. Parsing tests no longer depend on the wall clock. `npm run test:timezones` runs 94 targeted tests in fresh processes under UTC, Asia/Kolkata, America/New_York, and Pacific/Kiritimati.
  - Calendar tests reproduced ignored scope/search, missing list context on creation, and lost seconds/milliseconds on drag. `task-filter.ts` now shares list/calendar selection; nested children use that selection too, and the calendar header exposes the effective search filter and its keyboard shortcuts. Calendar creation preserves list context. DST gaps/folds and the current 09:00 local date-only fallback are documented rather than introducing all-day schema changes. These fixes also complete UX-01 and UX-02.
  - Timer tests reproduced callback-count drift, stale stopwatch logging, and dropped work completion on pause/reset/mode change after suspend. The timer now uses wall-clock deltas with fractional carry; a separate controller drains captured completion events once, including under StrictMode. Pause excludes paused time; overdue work counts once, consumes break overflow, then stops without additional cycles. Reload resets progress; session dates remain backend recording time. `plan.md` and the frontend README document these contracts.
  - Validation: backend 277 passed; frontend 176 passed; timezone matrix 94 passed in each of four zones; production build passes; lint has 9 existing warnings and no errors. Subagent review's reset/mode-switch finding was reproduced, fixed, and verified by follow-up review with no further timer blockers. Real Chromium smoke checks at 1440px dark and 1024px light verified visible filtering, selected-list creation, real pointer drag precision, and delayed stopwatch logging against stubbed APIs, with no page errors or horizontal overflow. Actual OS suspend and durable network idempotency remain outside the automated verification.

- [x] **CI-01: Run fast checks on pull requests and branch pushes.**
  - Add a CI workflow for backend pytest, frontend tests, frontend production build, and frontend lint.
  - Use locked dependencies; keep backend fixtures in-memory and stub AI/embedding/network calls.
  - Acceptance: failed tests or builds block merge; checks run independently of release tags.
  - Implemented on `feat/pull-request-ci`: `.github/workflows/ci.yml` runs on all branch pushes, pull requests, and manual dispatches with read-only repository permissions. Independent backend and frontend matrix jobs use Python 3.12 / pinned uv with `uv sync --locked`, and Node 24 / `npm ci`; frontend failures do not cancel sibling checks. Scheduled reviews and Hugging Face downloads are disabled in backend CI; existing isolated fixtures and AI/embedding stubs are retained.
  - Root README and `plan.md` document the four stable check names and required administrator setup: enable branch protection/rulesets and require `Backend tests`, `Frontend test`, `Frontend build`, and `Frontend lint` after their first GitHub run. Workflow files alone cannot enforce merge blocking. Release publication gating remains CI-02.
  - Validation: locked dependency installs succeed; backend 322 passed, frontend 189 passed, production build passes, and lint has 9 existing warnings with no errors. Actionlint 1.7.12 accepts the workflow; independent subagent review found no blockers; GitHub-hosted execution and branch-protection configuration remain unverified. `npm ci` reports 22 existing dependency advisories; this task adds no application dependencies.

- [x] **CI-02: Gate release publication on tests and a packaged backend smoke test.**
  - File: `.github/workflows/release.yml`.
  - Run the relevant checks before publishing bundles; launch the packaged sidecar against an isolated temporary database and verify `/api/health` and representative local CRUD.
  - Acceptance: a bundle with a backend startup or CRUD failure cannot be published; the smoke test touches no user database.
  - Implemented on `feat/release-validation`: release tags and manual builds call the reusable CI-01 workflow and require all four checks before the Linux bundle job. The job builds with Python 3.12, pinned uv, and a locked PyInstaller `packaging` group, then smoke-tests the exact executable Tauri will bundle before any Tauri build, draft creation, or asset upload. `build-sidecar.sh` shares the locked packaging setup. Only the bundle job has release-write permissions.
  - `backend/scripts/smoke_sidecar.py` launches the frozen executable directly with an isolated temporary database, working directory, HOME/XDG/cache paths, scheduling disabled, and Hugging Face offline mode. It discovers the OS-assigned loopback port from uvicorn's startup log and verifies health plus linked list/task create/read/update/delete and missing-record responses. It reports process logs on failure and terminates/waits/kills the child before removing temporary data. Journal writes are deliberately omitted because even rating-only saves can initialize embeddings.
  - Seven behavioral tests in `backend/tests/test_smoke_sidecar.py` exercise real fake-server subprocesses: success/isolation, early exit, readiness deadline, malformed health/JSON, CRUD failure, and forced-kill cleanup. A clean PyInstaller rebuild passed the actual frozen-binary smoke; `/bin/false` produced the expected nonzero CLI failure. Backend 329 passed; frontend 189 passed; build passes; lint has 9 existing warnings and no errors. Actionlint accepts both workflows; shell syntax validation passes. Independent review and a follow-up review of manual/tag event isolation found no blockers. Manual dispatches, including those targeting a tag, build artifacts without entering release-upload steps.
  - Root README and `plan.md` document gates and local smoke usage. Hosted GitHub/container execution, complete Tauri packaging, and draft-upload behavior remain unverified. Administrators can still manually publish an older draft or upload outside the workflow; this change gates workflow-generated artifacts instead of repository-wide administrative actions.

- [x] **QA-05: Triage the frontend lint warnings.**
  - Review hook dependency and render-purity warnings for actual behavior issues; fix those at their source.
  - Resolve component-export/children warnings with idiomatic code or narrowly justified rule configuration instead of blanket suppression.
  - Acceptance: remaining warnings are explicitly justified; journal save behavior and build/test results remain correct.
  - Implemented on `fix/frontend-lint`: the baseline has nine warnings rather than ten. Removed unused button/badge variant exports and renamed task-data `children` to `subtasks`, preserving React's content prop. No rule suppressions or dependencies were added.
  - Settings now derive untouched fields from query data and preserve local edits across initial loading and background refetches. Save/reset acknowledgements release unchanged field drafts back to query-backed values while preserving newer edits; acknowledged API keys clear independently of other fields. Preferences follow the same acknowledgement contract. `plan.md` documents these semantics.
  - `hooks/use-deadline-passed.ts` replaces render-time clock reads for list/board/calendar overdue indicators. Deadline timers update idle views, replace obsolete subscriptions on rescheduling, handle long browser delays, and recheck on focus/visibility changes. Scope/group/relative-label refresh behavior is unchanged and documented.
  - Regression coverage: nine Settings tests with a real QueryClient and deferred API responses, seven deadline-hook tests, and six real task-view tests. Three original overdue cases and three original Settings cases were demonstrated failing before their fixes; four acknowledgement regressions failed before the review follow-up fix. Journal lifecycle regressions remain passing.
  - Validation: backend 329 passed; frontend 211 passed; production build passes; lint has zero warnings and errors. Existing timezone matrix passes 94 tests in each of four zones; all 13 new deadline/task-view tests also pass in Pacific/Kiritimati. Independent review and follow-up found no blockers; acknowledged-field and API-key findings were fixed, and post-acknowledgement assertions now wait for mutation completion. The existing large-bundle build advisory remains PERF-01; packaged/browser manual smoke was not repeated for these nonvisual changes.

## P2: Scheduling model and calendar UX

- [x] **SCHED-01: Define task deadlines separately from scheduled work.**
  - Document how the existing `due_date` maps to deadline versus scheduling intent before migrating data.
  - Define unscheduled, date-only, and timed scheduling states explicitly; avoid inferring all-day intent from a synthetic 9 am timestamp.
  - Acceptance: API and UI semantics are documented in `plan.md`; existing tasks retain their intended dates through migration.
  - Implemented on `feat/task-deadline-model` after the user confirmed that every legacy due instant remains a timed deadline, including 09:00. Schema v5 adds indexed `deadline_date` and a named CHECK preventing date/timed conflicts without rewriting legacy values. Task IDs, recurrence identity, history, and saved reviews are preserved; normal pre-upgrade checkpoints and offline restore migrations apply.
  - Canonical `deadline` has explicit `none`, `date`, and `timed` states. Legacy `due_date` remains a timed write alias/read projection; null clears either kind. Conflicting fields, raw date-column writes, null/malformed deadlines, and extra state properties return 422. Shared static TaskFields/TaskResponse schemas keep computed API fields out of ORM inserts. Capture and decomposition return the same contract.
  - Quick add, calendar/menu creation, task views, grouping, drag, and optimistic cache projections preserve explicit deadline intent. Date-only input no longer creates a 09:00 instant; explicit and legacy 09:00 times stay visible. Date-only overdue uses next local midnight in the browser; API defaults to UTC today with optional `as_of_date` for a caller's calendar cutoff. Timed filters/telemetry remain compatible; date-only recurrence, telemetry, briefing, export, and backup/restore are covered.
  - `plan.md` and frontend/backend READMEs distinguish no deadline from unscheduled work. No work blocks or all-day events are inferred or created; multiple task-linked sessions remain SCHED-02, and IANA zones/all-day event intervals remain SCHED-03. Portable export v1 adds nullable `deadline_date` compatibly.
  - Review's missing decomposition deadline was reproduced and fixed. Static storage checks and date-only round-trip coverage close the integrity gaps. Midnight DST gaps, skipped local dates, and upper-year local projections have dedicated regressions; cutoff and upper-year failures were demonstrated before correction. Independent backend/frontend reviews and follow-up reviews found no remaining blockers.
  - Validation: backend 354 passed; frontend 235 passed; expanded timezone matrix 128 passed in each of six zones; production build passes; lint has zero warnings/errors. Regression coverage includes v5 rollback/retry, legacy timestamp preservation, API transitions/validation, date-only recurrence, metrics, capture/decomposition, briefing, export/offline backup restore, parsing, calendar operations, idle cutoff updates, and optimistic overlap/rollback. No dependencies or user databases were changed. Browser/packaged manual smoke remains unverified; the existing PERF-01 bundle advisory and recovery schema comparison's general lack of CHECK-definition validation remain follow-ups.

- [x] **SCHED-02: Add task-linked time blocks.**
  - Depends on DATA-01 and SCHED-01.
  - Define tables in `backend/app/models.py` and keep scheduling operations in a self-contained module/router.
  - Support multiple work blocks per task, start/end validation, and task association; keep task completion independent of calendar attendance.
  - Acceptance: splitting a task into multiple sessions leaves its deadline, status, and telemetry intact.
  - Implemented on `feat/task-time-blocks`: `TimeBlock` and schema v6 add required task ownership, indexed UTC start/end instants, an interval CHECK, and cascading deletion. `app/time_blocks.py` validates inputs; the dedicated `/api/time-blocks` router provides create/list/read/full replacement/delete, task filtering, and half-open overlap queries. Overlaps are allowed; completion/cancellation preserves blocks and recurring successors receive none.
  - Block operations leave task deadlines, status, recorded focus, and scores independent. No deadlines become blocks during migration. Portable export v1 adds the allowlisted `time_blocks` collection; SQLite backup/offline restore preserve identity, task associations, and precise timestamps. `plan.md` and backend/frontend READMEs document API-only scope; calendar UI, all-day intervals, and wall-clock zones remain UX-03/SCHED-03.
  - Regression coverage: 58 API cases in `backend/tests/test_time_blocks.py`, v6 rollback/retry and storage constraints in `test_migrations.py`, exact portable export coverage, and current/legacy offline restore checks. The initial API regressions failed with missing routes before implementation.
  - Validation: backend 415 passed; frontend 235 passed; production build passes; lint has zero warnings/errors. Independent subagent review found no blockers. Packaged/native manual smoke was not run; existing PERF-01 bundle advisory remains. Explicit cancellation, cross-midnight filter, and successful extreme-year API cases remain non-blocking coverage follow-ups.

- [x] **SCHED-03: Preserve timezone and all-day semantics.**
  - Keep timed instants as naive UTC and store IANA timezone metadata separately where wall-clock intent or recurrence requires it.
  - Represent all-day intervals with dates and explicit exclusive-end semantics.
  - Define behavior for DST gaps/ambiguities and recurring wall-clock times.
  - Acceptance: timed and all-day events round-trip without date shifts; DST tests preserve the documented scheduling intent.
  - Implemented on `feat/time-block-timezones`: schema v7 rebuilds blocks with explicit timed/all-day shapes, IANA metadata, date-only exclusive ends, and a storage CHECK preventing mixed/partial intervals. Legacy rows retain their IDs, links, timestamp bytes, and UTC meaning; no zone or all-day intent is guessed. Migration rollback/retry and current/legacy offline restore preserve data.
  - The dedicated input module accepts canonical timed instants, explicit `local` wall-clock input resolving to timed UTC, and all-day date labels. The user selected rejection of nonexistent local times and explicit matching offsets for repeated times. `app/time_zones.py` verifies both fold candidates by UTC round trip; mismatching offsets, overflow, and malformed shapes return 422. GET supports separate half-open instant/date range families without inventing all-day UTC instants. Full replacements clear incompatible fields.
  - Portable export v1 allowlists kind, zone, and date fields. The audited PSF `tzdata` dependency is locked and bundled with the sidecar as an offline fallback. `plan.md` and backend/frontend READMEs document the API, migration, DST policy, and future local-clock recurrence contract; actual block series/exception expansion and calendar UI remain SCHED-04/UX-03. Task deadlines, completion-triggered recurrence, focus, and scoring remain independent.
  - Regression coverage: 110 semantic API cases, four dedicated shape/migration tests, nine zone/fallback tests, and export/backup/restore coverage. Tests reproduced an ORM default replacing all-day timezone null with `UTC`; explicit nullable-column semantics fix it without test-only SQL-null workarounds. Review also exposed acceptance of host-only timezone keys; three failing regressions reproduced it before validation was restricted to the bundled IANA registry, preserving portable aliases.
  - Validation: backend 539 passed; frontend 235 passed; production build passes; lint has zero warnings/errors. The 119 semantic/zone/fallback tests also pass in Pacific/Kiritimati with host timezone lookup disabled. Independent review's portability finding was fixed; follow-up review found no remaining blockers. A rebuilt frozen sidecar passed ordinary health/CRUD smoke with host timezone lookup disabled; isolated timezone/all-day checks also verified both overlap offsets, gap/ambiguity rejection, date filtering, and cascades. Full desktop UI smoke remains outside scope; existing PERF-01 bundle advisory remains.

- [ ] **SCHED-04: Define recurrence ownership at the calendar boundary.**
  - Depends on FIX-02 and SCHED-03.
  - Separate completion-triggered recurring tasks from provider calendar series and occurrence exceptions.
  - Define the supported RRULE subset and reject or represent unsupported provider recurrence explicitly instead of silently changing it.
  - Acceptance: importing/exporting recurrence cannot create duplicate task clones or lose edited/canceled occurrence identity.

- [x] **UX-01: Make calendar filtering consistent with its controls.**
  - Files: `frontend/src/App.tsx`, `frontend/src/components/calendar-view.tsx`; shared selectors where appropriate.
  - Choose and document whether the calendar follows list/smart scope and search. Prefer shared filtering selectors across task views; if the calendar is global, make that explicit and remove misleading controls.
  - Acceptance: selecting a list or searching has the documented effect; completed/canceled visibility is consistent.
  - Implemented with QA-04: list sections and calendar share `lib/task-filter.ts`; the application passes scope/search into the calendar, including title/tag matching and terminal-state visibility. Calendar search is visible, clearable, and keyboard-accessible. Selector/component regressions and a Chromium smoke check cover the contract; `plan.md` documents it.

- [x] **UX-02: Preserve list context when creating calendar tasks.**
  - File: `frontend/src/components/calendar-view.tsx`.
  - Propagate the selected list into task creation where the chosen filtering contract supports list-scoped calendars.
  - Acceptance: adding a task from a list-scoped calendar places it in that list and on the selected day.
  - Implemented with QA-04: calendar creation sends the active list ID, or explicit no-list for smart scopes, with the selected local day at 09:00 serialized as UTC. Component regressions cover blank titles, selected-list and smart-scope creation; Chromium verifies the list/date payload against a stubbed API.

- [ ] **UX-03: Make scheduling actions reflect the explicit model.**
  - Depends on SCHED-01 through SCHED-03.
  - Render date-only and timed items distinctly; show actual times instead of hiding every item whose hour is 9.
  - Ensure dragging edits the intended time block or date instead of accidentally changing a task deadline.
  - Acceptance: the visible calendar agrees with persisted scheduling intent before and after rescheduling.

- [ ] **PERF-01: Split the frontend bundle by application section.**
  - File: `frontend/src/App.tsx`; related build configuration only where needed.
  - Lazy-load heavier sections such as the journal editor, insights, second brain, and settings; measure the resulting bundles and startup behavior.
  - Acceptance: the current roughly 1.38 MB minified monolithic JS bundle is reduced on the initial path; transitions retain stable loading feedback and tests/build pass.

## P2: Portable calendar export

- [ ] **ICS-01: Export selected time blocks as iCalendar files.**
  - Depends on SCHED-01 through SCHED-04; ordinary deadlines do not automatically become appointment start times.
  - Export opted-in time blocks as `VEVENT` with stable UIDs, timed/all-day values, timezone semantics, and explicit recurrence support.
  - Keep serialization in a self-contained calendar module; exclude journals and credentials.
  - Acceptance: exported files open in representative calendar clients without date shifts; document that export is a snapshot and reimport/update behavior varies by client.

## P3: Optional CalDAV synchronization after ICS

Deferred scope: opt-in outbound task-linked time blocks to a user-selected CalDAV calendar, after ICS-01 ships. Server installation, hosting, updates, and lifecycle belong to the user; Radicale is an optional user-level service instead of an app dependency. SQLite remains the source of truth for local tasks. Journal sync runs only while the application is running; an independently running CalDAV server can continue serving other clients.

- [ ] **CAL-01: Specify the outbound integration contract.**
  - Depends on ICS-01 and SCHED-01 through SCHED-04; outside the initial ICS milestone.
  - Use selected task-linked time blocks as the export unit; recommend a dedicated Meditations calendar.
  - Define field mapping and what completion, cancellation, block/task deletion, and disconnect do to linked events.
  - Acceptance: only opted-in blocks are exported; ordinary deadlines remain independent of appointment start times.

- [ ] **CAL-02: Add a calendar integration module with a CalDAV adapter.**
  - Separate the adapter, synchronization service, worker, and connection routes; define persistent tables in `backend/app/models.py`.
  - Keep discovery, resource URLs, UIDs, ETags, and optional WebDAV sync tokens inside the adapter. Avoid speculative provider abstractions; expose the capabilities the sync service actually needs.
  - Persist connection/calendar/resource identity, local block links, versions, and explicit sync state; keep event/time-block query families separate from the canonical tasks cache.
  - Acceptance: task CRUD works with no server configured or reachable; synchronization tests use a fake adapter, with server-specific interoperability tests separately.

- [ ] **CAL-03: Connect to an existing CalDAV server.**
  - Configure server URL and supported authentication explicitly; discover calendars and allow selection of a writable event calendar.
  - Accept a user-provided server; Radicale is an optional compatibility target, with Nextcloud and Baïkal verified separately. Support passwords/app passwords where offered; omit browser OAuth, cloud developer registration, and automatic server installation or startup.
  - Store credentials through a dedicated OS credential-store interface, separate from ordinary settings, exports, and fixtures. Model disconnected, connected, and authentication-required states explicitly.
  - Acceptance: connect, invalid credentials, restart, changed credentials, read-only calendar, and disconnect behave predictably. Disconnect removes local credentials without deleting remote events unless explicitly requested.

- [ ] **CAL-04: Implement idempotent event creation and conditional updates.**
  - Depends on CAL-01 through CAL-03.
  - Use stable event UIDs and resource mapping; define recovery after interrupted creates or uncertain remote outcomes.
  - Use conditional writes with ETags and creation preconditions where supported; handle conflicts explicitly instead of overwriting unseen remote edits.
  - Acceptance: retries cannot duplicate events; updates/deletions stay within linked resources in the selected calendar; unrelated events remain untouched.

- [ ] **CAL-05: Add a durable offline sync queue.**
  - Persist pending, syncing, synced, conflict, and error states; local edits commit without waiting for the server.
  - Resume/reconcile on startup and network recovery; retain pending edits through authentication and network failures.
  - Acceptance: offline create/edit/delete survives restart and converges after reconnection; remote changes to linked events are surfaced instead of silently overwritten.

- [ ] **CAL-06: Add connection and synchronization controls in Settings.**
  - Expose server setup, Disconnect, calendar selection, synchronization enablement, and manual Sync now.
  - Show queued changes, last successful sync, conflicts, and authentication errors; distinguish locally saved from remotely synced.
  - Acceptance: local-only use requires no account; explain app/server availability and give actionable connection errors.

- [ ] **CAL-07: Test and document outbound synchronization.**
  - Stub CalDAV responses in unit tests; cover discovery, conditional-write conflicts, interruption, duplicate retries, offline restart, deletion, completion policy, all-day values, and DST.
  - Add isolated interoperability checks against Radicale; verify Nextcloud and Baïkal before claiming support.
  - Provide optional user-level Radicale setup notes, separate from Journal installation; document multi-device connectivity, disconnect/recovery, and unsupported recurrence. Update `plan.md`.
  - Acceptance: ordinary tests use no real accounts, network services, or user database; packaged local-server connectivity is verified before release.

## P3: Calendar import and read-only subscriptions

- [ ] **ICS-02: Import iCalendar files as external calendar data.**
  - Keep imported appointments separate from tasks and telemetry; define UID matching, duplicate handling, recurrence exceptions, and unsupported components.
  - Acceptance: repeated imports follow a documented merge policy; malformed files leave local data intact; appointments never imply task completion.

- [ ] **ICS-03: Evaluate read-only calendar subscriptions.**
  - Distinguish subscribing to an external ICS URL from publishing Journal's own read-only feed.
  - External URLs need no inbound listener. Publishing needs a stable address reachable by the consuming client; a loopback feed works only for clients on the same machine while Journal is running.
  - Define exported scope and access controls before publishing; omit cloud hosting and public relays from the initial design.
  - Acceptance: document client-controlled refresh delays and one-way behavior; subscription edits cannot write back to Journal.

## P3: Inbound CalDAV events and bidirectional sync, phase 2

- [ ] **SYNC-01: Add a read-only external calendar overlay.**
  - Keep external events distinct from tasks and time blocks; showing an appointment does not mark a task complete or affect task-score telemetry.
  - Acceptance: selected remote events are visible without granting authority to rewrite local task data.

- [ ] **SYNC-02: Implement capability-aware reconciliation.**
  - Use WebDAV collection sync tokens where supported; otherwise compare resource URLs/ETags and fetch changed resources. Process deletions explicitly.
  - Complete the relevant listing/change batch before advancing durable reconciliation state; recover invalid tokens by rebuilding the affected cache while preserving local tasks and pending edits.
  - Reconcile on startup, resume, manual request, and periodically while running; define cache windows so events outside a queried date range are not mistaken for deletions.
  - Acceptance: missed changes, servers without sync-token support, expired tokens, and incomplete responses recover without data loss or duplicate events.

- [ ] **SYNC-03: Define and implement bidirectional conflict policies.**
  - Define field ownership, simultaneous edits, remote/local deletion, and recurrence exceptions before enabling inbound writes.
  - Use ETags and preconditions; prevent echo loops and retain recoverable conflict information.
  - Acceptance: concurrent edits follow a documented policy instead of silently overwriting local task content.

## P3: Optional local calendar bridges and task synchronization

- [ ] **LOCAL-01: Evaluate Linux desktop calendar access.**
  - Compare Evolution Data Server and Akonadi only if direct access to existing desktop calendars is needed.
  - Keep the bridge platform-specific and optional; document desktop-service dependencies and account permissions instead of requiring a second CalDAV server by default.
  - Acceptance: ordinary local-only and CalDAV use work without either desktop service installed.

- [ ] **TASKDAV-01: Specify CalDAV task synchronization if needed.**
  - Keep `VTODO` task synchronization separate from `VEVENT` time-block sync.
  - Evaluate server/client support for completion, hierarchy, date-only deadlines, timed values, and recurrence; preserve unsupported local fields.
  - Acceptance: task recurrence does not duplicate calendar occurrences; users can distinguish task sync from time-block event export.

## P3: Optional generic outgoing webhook automation

This is independent of calendar synchronization. Use it only for explicitly configured workflows, such as a local n8n instance; no public desktop listener is required.

- [ ] **HOOK-01: Specify versioned automation events and privacy boundaries.**
  - Define opted-in `time_block.created`, `time_block.updated`, `time_block.deleted`, and `task.completed` events with stable event/entity IDs, versions, timestamps, and scheduling metadata.
  - Exclude journal content and connection credentials by default.
  - Acceptance: consumers can identify retries/deletions and interpret timed versus all-day values; users control which data leaves the app.

- [ ] **HOOK-02: Implement durable outgoing webhook delivery.**
  - Depends on HOOK-01; use a self-contained module with a transactional outbox, per-endpoint state, and documented request authentication/signatures.
  - Persist offline work, retry eligible failures, and support manual retry; define at-least-once delivery and ordering/version semantics.
  - Acceptance: interruption/restart preserves work; duplicate attempts retain event identity; local saves succeed while endpoints are unavailable.

- [ ] **HOOK-03: Add opt-in configuration and delivery status.**
  - Expose endpoint/event/scope selection, enable/disable, test delivery, errors, and manual retry; store credentials through the credential interface.
  - Define queued-delivery behavior on disable/removal; distinguish webhook delivery from confirmed calendar synchronization.
  - Acceptance: calendar features work with automation disabled; users can diagnose delivery failures without exposing credentials.

- [ ] **HOOK-04: Add an optional local workflow example and tests.**
  - Demonstrate event mapping, persistent resource identity, idempotency, deletion, and completion policy with a local workflow service.
  - Test request authentication, offline retries, duplicates, out-of-order updates, and restart with stubbed endpoints.
  - Acceptance: retries update an existing event instead of creating duplicates; examples use no real credentials or mandatory cloud service.

## Completion checklist for each implementation branch

- [ ] Add dedicated regression tests for the changed contract; use in-memory databases and stub external services.
- [ ] Run `cd backend && uv run pytest`.
- [ ] Run `cd frontend && npm run test`, `npm run build`, and `npm run lint`.
- [ ] Update `plan.md` when architecture or behavior changes; update user documentation when workflows change.
- [ ] Obtain subagent review before merging non-trivial branches and resolve blocker findings.
- [ ] Mark the completed task here with a short implementation/test reference.

## Integration references

- [CalDAV protocol, RFC 4791](https://www.rfc-editor.org/rfc/rfc4791)
- [iCalendar format, RFC 5545](https://www.rfc-editor.org/rfc/rfc5545)
- [WebDAV collection synchronization, RFC 6578](https://www.rfc-editor.org/rfc/rfc6578)
- [Radicale documentation](https://radicale.org/v3.html)
- [Nextcloud Calendar documentation](https://docs.nextcloud.com/server/latest/user_manual/en/groupware/calendar.html)
- [Baïkal CalDAV/CardDAV server](https://sabre.io/baikal/)
- [DAVx⁵ documentation](https://www.davx5.com/)
