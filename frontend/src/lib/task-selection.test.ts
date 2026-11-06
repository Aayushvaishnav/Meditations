import { describe, expect, it } from "vitest"
import type { Task } from "@/api/types"
import { taskSections } from "./task-sections"
import { boardColumns, selectBoardTasks } from "./board"
import { selectMatrixTasks } from "./eisenhower"

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, list_id: null, parent_id: null, description: null, priority: 0,
    importance: "unassigned", urgency: "unassigned", status: "todo", deadline: { kind: "none" },
    due_date: null, estimated_minutes: null, actual_minutes: 0, recurrence_rule: null,
    recurrence_series_id: null, recurrence_occurrence: null, tags: [], order_index: 0,
    completed_at: null, created_at: "2026-11-01T00:00:00", updated_at: "2026-11-01T00:00:00", ...patch }
}
const scope = { kind: "smart", id: "all" } as const
const now = new Date(2026, 10, 6, 12)

describe("bulk selection display boundaries", () => {
  it("includes only rendered list roots and their direct scoped children", () => {
    const tasks = [task("parent"), task("child", { parent_id: "parent" }),
      task("grandchild", { parent_id: "child" }), task("canceled", { status: "canceled" }),
      task("completed", { status: "completed" })]
    expect(taskSections(tasks, scope, "", now).selectable.map(t => t.id)).toEqual(["parent", "child"])
    expect(taskSections(tasks, scope, "grandchild", now).selectable.map(t => t.id)).toEqual(["grandchild"])
  })
  it("respects the List completed backlog cap, including nested children", () => {
    const tasks = Array.from({ length: 25 }, (_, i) => task(`done-${i}`, { status: "completed", completed_at: `2026-11-${String(i + 1).padStart(2, "0")}T00:00:00` }))
    tasks.push(task("hidden-child", { parent_id: "done-0", status: "completed" }))
    const result = taskSections(tasks, { kind: "smart", id: "completed" }, "", now)
    expect(result.sections[0].tasks).toHaveLength(20)
    expect(result.selectable.some(t => t.id === "done-0" || t.id === "hidden-child")).toBe(false)
  })
  it("uses Board's rendered Done cap and excludes subtasks", () => {
    const tasks = Array.from({ length: 35 }, (_, i) => task(`done-${i}`, { status: "completed", order_index: i }))
    tasks.push(task("child", { parent_id: "done-0" }))
    const columns = boardColumns(selectBoardTasks(tasks, scope, "", now))
    expect(columns.flatMap(column => column.tasks)).toHaveLength(30)
    expect(columns[2].overflow).toBe(5)
    expect(boardColumns(selectBoardTasks(tasks, scope, "done-34", now))[2].tasks.map(t => t.id)).toEqual(["done-34"])
  })
  it("keeps Matrix's independent active-task policy and search", () => {
    const tasks = [task("parent"), task("child", { parent_id: "parent", tags: ["review"] }), task("done", { status: "completed" })]
    expect(selectMatrixTasks(tasks, scope, "", now).map(t => t.id)).toEqual(["child", "parent"])
    expect(selectMatrixTasks(tasks, scope, "review", now).map(t => t.id)).toEqual(["child"])
  })
})
