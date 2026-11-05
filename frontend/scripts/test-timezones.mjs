import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const root = fileURLToPath(new URL("../", import.meta.url))
const vitest = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url))
const tests = [
  "src/lib/dates.test.ts",
  "src/lib/parsing.test.ts",
  "src/lib/task-filter.test.ts",
  "src/components/kanban-board.test.tsx",
  "src/lib/eisenhower.test.ts",
  "src/lib/task-deadlines.test.ts",
  "src/lib/time-blocks.test.ts",
  "src/lib/calendar-overlay.test.ts",
  "src/lib/calendar-range.test.ts",
  "src/lib/calendar-projection.test.ts",
  "src/lib/calendar-time-grid.test.ts",
  "src/lib/calendar-time-edit.test.ts",
  "src/components/calendar/month.test.tsx",
  "src/components/calendar/time-grid.test.tsx",
  "src/components/calendar/year.test.tsx",
  "src/components/calendar/time-edit.test.tsx",
  "src/components/calendar-modes.test.tsx",
  "src/components/calendar/deadline-move.test.tsx",
  "src/components/calendar-imported-overlay.test.tsx",
  "src/hooks/use-deadline-passed.test.ts",
  "src/components/quick-add.test.tsx",
  "src/components/task-overdue.test.tsx",
  "src/components/calendar-view.test.tsx",
  "src/components/task-sections.test.tsx",
  "src/components/header.test.tsx",
  "src/stores/timer.test.ts",
  "src/components/focus-timer.test.tsx",
]
for (const timezone of ["UTC", "Asia/Kolkata", "America/New_York", "Pacific/Kiritimati", "America/Sao_Paulo", "Pacific/Apia", "Australia/Lord_Howe"]) {
  console.log(`\nTimezone: ${timezone}`)
  const result = spawnSync(process.execPath, [vitest, "run", "--maxWorkers=4", ...tests], {
    cwd: root,
    env: { ...process.env, TZ: timezone },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
