import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const root = fileURLToPath(new URL("../", import.meta.url))
const vitest = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url))
const tests = [
  "src/lib/dates.test.ts",
  "src/lib/parsing.test.ts",
  "src/lib/task-filter.test.ts",
  "src/lib/task-deadlines.test.ts",
  "src/lib/time-blocks.test.ts",
  "src/lib/calendar-overlay.test.ts",
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
for (const timezone of ["UTC", "Asia/Kolkata", "America/New_York", "Pacific/Kiritimati", "America/Sao_Paulo", "Pacific/Apia"]) {
  console.log(`\nTimezone: ${timezone}`)
  const result = spawnSync(process.execPath, [vitest, "run", ...tests], {
    cwd: root,
    env: { ...process.env, TZ: timezone },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
