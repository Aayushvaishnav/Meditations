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
  stay hidden; completed tasks appear in Completed. This is a deadline calendar;
  task-linked work blocks have a separate backend API; their UI remains UX-03.
- **Focus timer** (`src/stores/timer.ts`): wall-clock-based Pomodoro and stopwatch,
  including delayed callbacks and suspend during the current app lifecycle. Pauses
  exclude elapsed time. A delayed Pomodoro logs one work session, consumes the
  break, and stops; reset/mode changes preserve completed work and discard unfinished
  progress. Reload preserves settings and resets progress. Session dates use backend
  recording time; the client event queue is not durable network idempotency.
- **Board view** (`src/components/kanban-board.tsx`): @dnd-kit Kanban across
  To Do / In Progress / Done with drag overlay and fractional `order_index` writes.
- **Optimistic updates** (`src/hooks/api.ts`): all mutations patch the TanStack Query cache
  on `onMutate` and roll back on error — check-offs and captures feel instant.

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
  backend API with IANA metadata and all-day intervals; UI support remains UX-03.
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
