import type { Task } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { selectScopedTasks } from "./task-filter"

export function selectBoardTasks(tasks: Task[], scope: Scope, search: string, now = new Date()): Task[] {
  return selectScopedTasks(tasks, scope, search, now, "include-in-all-and-list")
    .filter(task => task.parent_id === null)
}
