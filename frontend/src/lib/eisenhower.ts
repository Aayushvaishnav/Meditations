import type { Task } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { selectScopedTasks } from "./task-filter"

export type MatrixClassification = Pick<Task, "importance" | "urgency">

export const MATRIX_ZONES = [
  { id: "do", label: "Urgent & important", importance: "important", urgency: "urgent" },
  { id: "schedule", label: "Not urgent & important", importance: "important", urgency: "not_urgent" },
  { id: "delegate", label: "Urgent & not important", importance: "not_important", urgency: "urgent" },
  { id: "eliminate", label: "Not urgent & not important", importance: "not_important", urgency: "not_urgent" },
  { id: "unclassified", label: "Unclassified", importance: "unassigned", urgency: "unassigned" },
] as const satisfies readonly (MatrixClassification & { id: string; label: string })[]

export type MatrixZoneId = typeof MATRIX_ZONES[number]["id"]

export function matrixZoneOf(task: MatrixClassification): MatrixZoneId {
  if (task.importance === "unassigned" || task.urgency === "unassigned") return "unclassified"
  if (task.importance === "important") return task.urgency === "urgent" ? "do" : "schedule"
  return task.urgency === "urgent" ? "delegate" : "eliminate"
}

export function classificationForZone(id: MatrixZoneId): MatrixClassification {
  const { importance, urgency } = MATRIX_ZONES.find(zone => zone.id === id)!
  return { importance, urgency }
}

export function selectMatrixTasks(tasks: Task[], scope: Scope, search: string, now = new Date()): Task[] {
  return selectScopedTasks(tasks, scope, search, now).sort((a, b) =>
    a.order_index - b.order_index ||
    a.created_at.localeCompare(b.created_at) ||
    a.id.localeCompare(b.id),
  )
}
