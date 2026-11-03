# Meditations Frontend

React 19 + Vite + Tailwind v4 + shadcn/ui (Base UI) frontend for the Meditations life-OS.

## Run

```bash
npm install
npm run dev        # http://localhost:5173, expects backend on :8000 (see ../backend)
```

## Test & build

```bash
npm run test            # Vitest component, hook, store, and utility regressions
npm run test:timezones  # Dates/deadlines/timers in UTC, Kolkata, New York, Kiritimati, São Paulo, Apia
npm run build           # tsc -b + vite build
```

## Section loading

The tasks shell loads immediately. Journal, Insights, Second Brain, and Settings
load on first selection and reuse their loaded modules on later visits. During
loading, the central pane announces the selected section while navigation,
the timer, and the command palette stay available. Section navigation still
unmounts the previous view and flushes pending journal saves.

To inspect production chunks, run `npm run build -- --manifest` and read
`dist/.vite/manifest.json`. Include each entry's recursive static `imports`
when measuring initial JavaScript; dynamically imported sections are deferred.
PERF-01 reduced that initial total from 1.40 MB to 818 KB minified (41.6%).
The remaining large-chunk build advisory is unchanged in configuration.

## Phase 2 scope

- **Quick add** (`src/lib/parsing.ts`): `buy milk tomorrow 5pm !1 #personal @errands ~10m` —
  chrono-node dates (auto-roll-forward for bare past times/weekdays), `!1/!2/!3` priority,
  `#list` (auto-created if missing), `@tags`, `~durations`, `every mon, wed` → RRULE.
  Live parse preview under the input; `?` popover documents the syntax.
- **List view** (`src/components/task-sections.tsx`): sections Overdue / Today / Tomorrow /
  Upcoming / No date / Completed, scoped to smart views or a list; search filter;
  inline rename (double-click), subtasks (expand + add), per-task menu (priority, due, move, delete).
- **Calendar** (`src/components/calendar-view.tsx`): month grid of task deadlines,
  sharing smart/list scope and title/tag search with the list view. Creation keeps
  the selected list and creates a date-only deadline. Dragging changes the deadline,
  preserving date-only intent or a timed deadline's local clock precision. Timed
  09:00 values show their time instead of being treated as date-only. Canceled tasks
  stay hidden; completed tasks appear in Completed. Work blocks use shaded chips
  with timed ranges or an All day label, following their owner's scope/search even
  without a deadline. Overnight/multi-day blocks appear on every overlapping day;
  exclusive ends are respected. Dragging a block changes only that block. Moving a
  continuation shifts the whole interval by the dragged-day delta. The day dialog
  offers a date-input Move block action as an alternative to dragging.
  Block creation/deletion and time-of-day editing remain API-only.
- **Focus timer** (`src/stores/timer.ts`): wall-clock-based Pomodoro and stopwatch,
  including delayed callbacks and suspend during the current app lifecycle. Pauses
  exclude elapsed time. A delayed Pomodoro logs one work session, consumes the
  break, and stops; reset/mode changes preserve completed work and discard unfinished
  progress. Reload preserves settings and resets progress. Session dates use backend
  recording time; the client event queue is not durable network idempotency.
- **Board view** (`src/components/kanban-board.tsx`): @dnd-kit Kanban across
  To Do / In Progress / Done with drag overlay and fractional `order_index` writes.
- **Optimistic updates** (`src/hooks/api.ts`): task mutations patch the TanStack Query
  cache on `onMutate` and roll back on error; work-block moves wait for server confirmation.

## Conventions

- All datetimes arrive naive UTC from the API and are parsed with `parseUTC()`
  (appends `Z`); outgoing datetimes are aware ISO (`toISOString()`), which the
  backend normalizes.
- `Task.deadline` explicitly distinguishes `none`, `date` (`YYYY-MM-DD`), and
  `timed` (UTC instant). Quick-add date-only phrases and calendar/menu day choices
  keep date labels instead of inventing a time. A date-only deadline becomes
  overdue at the next local midnight. Explicit times, including 09:00, remain
  timed; every legacy due instant keeps its original value and timed intent.
- `lib/task-deadlines.ts` owns deadline display, day selection, cutoff, and moves;
  `lib/date-values.ts` owns UTC parsing and calendar arithmetic. Timed moves use
  native Date setters: DST gaps advance by the gap and overlaps use the earlier
  offset. Date labels bypass UTC conversion. Task-linked work blocks use a separate
  cache (`["time-blocks"]`) with IANA metadata and all-day intervals. Block moves
  preserve browser-local displayed start time, precise elapsed duration, and saved
  IANA metadata, independently of deadlines/status/focus/scores. Nonexistent target
  times are rejected; repeated times use the earlier occurrence. All-day moves
  preserve the calendar-date span without inventing UTC instants. Server-confirmed
  moves disable block controls until settlement/refetch and retain data on error;
  task/list deletion refreshes blocks after backend cascades.
- Legacy `due_date` remains a timed-only API projection. New writes use `deadline`
  instead of mixing both fields; optimistic mutations keep both projections
  consistent. A task without a deadline is independent of future scheduled work.
- Single tasks cache (`["tasks"]`) — grouping/filtering happens client-side;
  mutations invalidate after settle.
- UI state (view, scope) persists to localStorage via zustand `persist`.
- shadcn v4 on this project uses **Base UI** primitives (`@base-ui/react`), not Radix:
  triggers take a `render={<Element />}` prop instead of Radix's `asChild`.


## Backup and portable export

Settings exposes independent **Database backup** and **Portable data export**
actions. The backup is a complete `.db` for offline restore and contains saved
credentials. The export is a `.zip` of Markdown journals, JSON domain records,
and a format guide; application settings and saved provider credentials are
excluded. Both include committed state; finish saving editor changes first.

`lib/backup.ts` and `lib/data-export.ts` configure a shared `lib/file-download.ts`
transport. Native dialogs use exclusive file creation with Unix mode `0600`;
canceling the dialog sends no API request. A failed native write can leave an
incomplete new file and reports that possibility. An already selected native
save finishes even if the view unmounts.

`useBackup` and `useDataExport` in `hooks/api.ts` keep separate pending/error
states and browser object URLs. Leaving the view prevents late browser downloads
and releases retained URLs; retries replace only that action's prior URL.
Native packaged export still needs a real save-dialog smoke check. The browser
and component regressions do not claim native filesystem verification.


## Calendar snapshot export

In Calendar, expand **Export work blocks**, select the blocks to share, then
choose **Download .ics**. The list follows the displayed month and current owner
list/search/status filters. Blocks overlapping the month export their full
intervals. Deadlines remain separate. Blocks start unchecked; changing the month
or filters clears selection. Finish saving edits before downloading.

The unencrypted snapshot includes task titles and block dates/times, instead of
journals or saved credentials. Timed events retain UTC instants and display in
the receiving app's timezone; all-day dates keep their exclusive ends. Selected
blocks are individual events, including blocks owned by recurring tasks. Export
is independent of task completion and recorded focus.

Open/import the file in a calendar app. Stable block-derived UIDs preserve
identity across exports, but each client's reimport/update behavior varies and
repeated imports can create duplicates. Later changes do not synchronize.
Subscriptions and calendar-series export remain deferred. File imports have an
independent read-only inventory in Settings (see below). Optional
outbound CalDAV controls are available in Settings as described below.

`components/calendar-export.tsx` owns selection and feedback; `useCalendarExport`
in `hooks/api.ts` sends frozen string IDs through `lib/calendar-export.ts` to
`POST /api/calendar/export`. Browser and exclusive private native downloads reuse
`lib/file-download.ts`. Canceling a native dialog sends no API request; failures
allow retry. Pending block moves and unavailable block queries disable export.

## Optional calendar synchronization

**Settings → Calendar synchronization** connects a user-managed CalDAV server
using Basic/Digest password or app-password authentication. Local use requires no
account. Journal does not install or start a server; OAuth-only sign-in is outside
scope. Use HTTPS, or HTTP only for loopback, and choose a writable event calendar.
A dedicated **Meditations** calendar is recommended.

Discover calendars, explicitly select one, then connect. Credentials use the
backend's OS vault, instead of settings/exports. Verify after restart or replace
credentials to recover authentication errors. Setup alone leaves sync paused and
selects no blocks. Choose individual task-linked blocks, then enable sync or use
Sync now. The list identifies owners and timed/all-day intervals; a local save
and a remote acknowledgment remain separate states. Queued changes, conflicts,
authentication errors, and last successful acknowledgment time appear inline.

Remove remote event queues deletion while preserving local data. Stop syncing
keeps the remote copy and provides conflict resolution without overwriting either
side. Disconnect removes credentials and keeps remote events. Both Journal and
the server must be running and reachable to sync; localhost is limited to this
device. Actual provider/native-vault interoperability remains CAL-07 verification.

`calendar-settings.tsx` owns ephemeral credential requests outside Query caches;
`calendar-connection-controls.tsx` owns per-connection controls. Calendar query
hooks in `hooks/api.ts` have a separate cache family, ten-second status/link
refresh, server-confirmed intent mutations, and shared mutation pending state.
They do not invalidate or modify the canonical tasks cache. Status distinguishes
never-synced, unknown historical time, and observed acknowledgment time.


## Read-only calendar imports

**Settings → Import calendar files** accepts UTF-8 `.ics` files into a new named
calendar or an explicitly selected existing destination. The inventory retains
appointments, series and exceptions without creating tasks, recording attendance,
or expanding occurrences onto Calendar. Matching uses source + UID + original
typed recurrence identity; the latest explicit import replaces matching records,
while omitted identities remain. Removal requires confirmation.

`components/calendar-import-settings.tsx` owns the import form and inventory.
Hooks in `hooks/api.ts` use only the independent `['calendar-imports']` cache
family. Shared mutation state locks controls during file reading and requests,
including navigation/remount; completion still refreshes caches after departure.
No upload library or native permission was added. Database backups retain source
files and history; portable ZIP exports exclude them. See the
[import guide](../docs/calendar-import.md) for merge policy, privacy and API details.


### Imported Calendar overlay

Calendar's **Imported calendar** selector starts Hidden and displays one imported
file destination independently of task list/search/status filters. The view-local
selection survives month changes and resets on Calendar unmount. Dashed Imported
chips open read-only day details; no drag or task mutation is registered for them.
`calendar-imported-overlay.tsx` owns source selection and loading/error/retry states;
`lib/calendar-overlay.ts` owns local-day overlap and interval labels. The overlay
hook in `hooks/api.ts` shares import invalidation, without task/telemetry changes.
Date ends are exclusive, timed instants use local day boundaries, floating labels
stay unconverted, and no-end timed records are points. Opaque series, cancellations,
durations and unsafe intervals remain in an explicit outside-grid inventory.
Files require reimport to refresh; this feature does not fetch live calendars.

### Optional outgoing webhooks

Settings has an independent outgoing-webhooks section for endpoint creation and
editing, event/list scopes, explicit title sharing, enable/disable/removal, test
delivery, status, and manual retry. `webhook-settings.tsx` owns this surface;
`hooks/webhooks.ts` owns the React Query hooks re-exported by `hooks/api.ts`.
Signing secrets are write-only and clear after an acknowledged save. Configuration
changes cancel old queued work, and delivered means workflow acknowledgement,
instead of confirmed calendar synchronization. Calendar features remain available
without enabling automation. See [the workflow guide](../docs/webhooks.md).
