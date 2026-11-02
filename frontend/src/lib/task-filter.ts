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

export function selectScopedTasks(tasks: Task[], scope: Scope, search: string, now = new Date()): Task[] {
  const groups = TASK_GROUPS_BY_SCOPE[scope.kind === "list" ? "list" : scope.id]
  return tasks.filter(task =>
    task.status !== "canceled" &&
    (scope.kind !== "list" || task.list_id === scope.id) &&
    matchTaskSearch(task, search) &&
    groups.includes(groupOf(task, now)),
  )
}
