import { describe, expect, it } from "vitest"
import type { Task } from "@/api/types"
import { deadlineFromLegacy } from "./task-deadlines"
import { classificationForZone, MATRIX_ZONES, matrixZoneOf, selectMatrixTasks } from "./eisenhower"

const now = new Date(2026, 2, 7, 12)
function task(id: string, patch: Partial<Task> = {}): Task {
  return {
    id, title: id, description: null, list_id: null, parent_id: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo",
    due_date: null, estimated_minutes: null, actual_minutes: 0, recurrence_rule: null,
    recurrence_series_id: null, recurrence_occurrence: null, tags: [], order_index: 0,
    completed_at: null, created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00",
    deadline: deadlineFromLegacy(patch.due_date ?? null), ...patch,
  }
}

describe("matrix classification", () => {
  it.each([
    ["important", "urgent", "do"],
    ["important", "not_urgent", "schedule"],
    ["not_important", "urgent", "delegate"],
    ["not_important", "not_urgent", "eliminate"],
    ["unassigned", "urgent", "unclassified"],
    ["unassigned", "not_urgent", "unclassified"],
    ["important", "unassigned", "unclassified"],
    ["not_important", "unassigned", "unclassified"],
    ["unassigned", "unassigned", "unclassified"],
  ] as const)("classifies %s / %s as %s", (importance, urgency, expected) => {
    expect(matrixZoneOf({ importance, urgency })).toBe(expected)
  })

  it("orders the five zones and supplies independent two-field patches", () => {
    expect(MATRIX_ZONES.map(zone => zone.id)).toEqual(["do", "schedule", "delegate", "eliminate", "unclassified"])
    for (const zone of MATRIX_ZONES) {
      const patch = classificationForZone(zone.id)
      expect(patch).toEqual({ importance: zone.importance, urgency: zone.urgency })
      expect(matrixZoneOf(patch)).toBe(zone.id)
      patch.importance = "not_important"
      expect(classificationForZone(zone.id)).toEqual({ importance: zone.importance, urgency: zone.urgency })
    }
  })
})

describe("matrix selection", () => {
  const rows = [
    task("overdue", { due_date: new Date(2026, 2, 6).toISOString() }),
    task("today", { due_date: new Date(2026, 2, 7).toISOString() }),
    task("tomorrow", { due_date: new Date(2026, 2, 8).toISOString() }),
    task("future", { due_date: new Date(2026, 2, 10).toISOString() }),
    task("undated"), task("completed", { status: "completed" }), task("canceled", { status: "canceled" }),
  ]

  it.each([
    ["today", ["overdue", "today"]], ["overdue", ["overdue"]],
    ["upcoming", ["future", "tomorrow"]],
    ["all", ["future", "overdue", "today", "tomorrow", "undated"]],
    ["completed", ["completed"]],
  ] as const)("honors the %s scope", (id, expected) => {
    expect(selectMatrixTasks(rows, { kind: "smart", id }, "", now).map(task => task.id)).toEqual(expected)
  })

  it("intersects list and title/tag search without including canceled or completed tasks", () => {
    const rows = [task("Plan", { list_id: "work" }), task("Review", { list_id: "work", tags: ["PLAN"] }),
      task("Plan home", { list_id: "home" }), task("Plan done", { list_id: "work", status: "completed" }),
      task("Plan canceled", { list_id: "work", status: "canceled" })]
    expect(selectMatrixTasks(rows, { kind: "list", id: "work" }, "plan", now).map(task => task.id)).toEqual(["Plan", "Review"])
    expect(selectMatrixTasks(rows, { kind: "smart", id: "all" }, "absent", now)).toEqual([])
  })

  it("includes subtasks exactly once, independently of parent visibility, and sorts without mutation", () => {
    const rows = [task("z", { order_index: 2 }), task("b", { parent_id: "parent" }),
      task("a", { parent_id: "hidden", status: "in_progress" }),
      task("older", { created_at: "2026-02-01T00:00:00" }),
      task("parent", { order_index: 1 }), task("hidden", { status: "completed" })]
    const snapshot = structuredClone(rows)
    const selected = selectMatrixTasks(rows, { kind: "smart", id: "all" }, "", now)
    expect(selected.map(task => task.id)).toEqual(["older", "a", "b", "parent", "z"])
    expect(new Set(selected.map(task => task.id)).size).toBe(selected.length)
    expect(rows).toEqual(snapshot)
    expect(selectMatrixTasks([...rows].reverse(), { kind: "smart", id: "all" }, "", now)).toEqual(selected)
    expect(selectMatrixTasks(rows, { kind: "smart", id: "all" }, "b", now).map(task => task.id)).toEqual(["b"])
  })
})
