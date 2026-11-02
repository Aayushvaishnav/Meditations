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
npm run test:timezones  # Calendar/date/timer suite in UTC, Kolkata, New York, Kiritimati
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
- **Calendar** (`src/components/calendar-view.tsx`): month grid of task due dates,
  sharing smart/list scope and title/tag search with the list view. Creation keeps
  the selected list; drag moves preserve local clock time, including seconds and
  milliseconds. Canceled tasks stay hidden; completed tasks appear in Completed.
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
- Date-only quick-add input and calendar creation use 09:00 local time as a
  fallback, rather than an all-day flag. Calendar moves use native local Date
  construction: DST gaps advance by the gap and ambiguous times use the earlier
  offset. Separate scheduling/all-day/timezone metadata remains planned work.
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
