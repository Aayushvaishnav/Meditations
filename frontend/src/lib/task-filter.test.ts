import { deadlineFromLegacy } from "./task-deadlines"
import { describe, expect, it } from "vitest"
import type { Task } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { selectScopedTasks } from "./task-filter"

const now = new Date(2026, 2, 7, 12)
function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: null, parent_id: null, priority: 0, status: "todo", due_date: null,
    estimated_minutes: null, actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00", deadline: deadlineFromLegacy(patch.due_date ?? null), ...patch }
}
const tasks = [
  task("overdue", { due_date: new Date(2026, 2, 6, 23, 59).toISOString() }),
  task("today", { due_date: new Date(2026, 2, 7).toISOString() }),
  task("tomorrow", { due_date: new Date(2026, 2, 8).toISOString() }),
  task("future", { due_date: new Date(2026, 2, 10).toISOString() }),
  task("undated"), task("completed", { status: "completed" }), task("canceled", { status: "canceled" }),
]
describe("shared task scope selection", () => {
  it.each([
    ["today", ["overdue", "today"]], ["overdue", ["overdue"]], ["upcoming", ["tomorrow", "future"]],
    ["all", ["overdue", "today", "tomorrow", "future", "undated"]], ["completed", ["completed"]],
  ] as const)("selects %s without mutating source order or task data", (id, expected) => {
    const snapshot = structuredClone(tasks)
    expect(selectScopedTasks(tasks, { kind: "smart", id }, "", now).map(task => task.id)).toEqual(expected)
    expect(tasks).toEqual(snapshot)
  })
  it("intersects list, status, title and tag filters", () => {
    const scope: Scope = { kind: "list", id: "work" }
    const rows = [task("Planning", { list_id: "work" }), task("Review", { list_id: "work", tags: ["PLAN"] }),
      task("Planning at home", { list_id: "home" }), task("Finished plan", { list_id: "work", status: "completed" }),
      task("Canceled plan", { list_id: "work", status: "canceled" })]
    expect(selectScopedTasks(rows, scope, "plan", now).map(task => task.id)).toEqual(["Planning", "Review"])
    expect(selectScopedTasks(rows, scope, "absent", now)).toEqual([])
  })
})
