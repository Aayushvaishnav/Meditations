import type { Task } from "@/api/types"
import type { Scope, SmartView } from "@/stores/ui"
import { groupOf, type TaskGroup } from "./dates"
import { matchTaskSearch } from "./search"

export const TASK_GROUPS_BY_SCOPE: Record<SmartView | "list", TaskGroup[]> = {
  today: ["overdue", "today"],
  overdue: ["overdue"],
  upcoming: ["tomorrow", "upcoming"],
  all: ["overdue", "today", "tomorrow", "upcoming", "nodate"],
  completed: ["completed"],
  list: ["overdue", "today", "tomorrow", "upcoming", "nodate"],
}

export function selectScopedTasks(
  tasks: Task[], scope: Scope, search: string, now = new Date(),
  completed: "scope" | "include-in-all-and-list" = "scope",
): Task[] {
  const scopeKey = scope.kind === "list" ? "list" : scope.id
  const groups = TASK_GROUPS_BY_SCOPE[scopeKey]
  const includeCompleted = completed === "include-in-all-and-list" && (scopeKey === "all" || scopeKey === "list")
  return tasks.filter(task =>
    task.status !== "canceled" &&
    (scope.kind !== "list" || task.list_id === scope.id) &&
    matchTaskSearch(task, search) &&
    (groups.includes(groupOf(task, now)) || (includeCompleted && task.status === "completed")),
  )
}
