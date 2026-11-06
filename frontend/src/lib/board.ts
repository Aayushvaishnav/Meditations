import type { Task } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { selectScopedTasks } from "./task-filter"

export function selectBoardTasks(tasks: Task[], scope: Scope, search: string, now = new Date()): Task[] {
  return selectScopedTasks(tasks, scope, search, now, "include-in-all-and-list")
    .filter(task => task.parent_id === null)
}

export function boardColumns(tasks: Task[]) {
  return (["todo", "in_progress", "completed"] as const).map(status => {
    const all = tasks.filter(task => task.status === status).sort((a, b) =>
      a.order_index - b.order_index || a.created_at.localeCompare(b.created_at),
    )
    return { status, tasks: status === "completed" ? all.slice(0, 30) : all,
      overflow: status === "completed" ? Math.max(0, all.length - 30) : 0 }
  })
}
