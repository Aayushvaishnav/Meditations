import type { Task } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { groupOf, sortTasks } from "./dates"
import { selectScopedTasks, TASK_GROUPS_BY_SCOPE } from "./task-filter"

export function taskSections(tasks: Task[], scope: Scope, search: string, now = new Date()) {
  const visible = selectScopedTasks(tasks, scope, search, now)
  const ids = new Set(visible.map(task => task.id))
  const roots = visible.filter(task => task.parent_id === null || !ids.has(task.parent_id))
  const sections = TASK_GROUPS_BY_SCOPE[scope.kind === "list" ? "list" : scope.id].map(group => {
    const bucket = roots.filter(task => groupOf(task, now) === group).sort(sortTasks)
    return { group, tasks: group === "completed"
      ? bucket.sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? "")).slice(0, 20)
      : bucket }
  }).filter(section => section.tasks.length > 0)
  const rootIds = new Set(sections.flatMap(section => section.tasks.map(task => task.id)))
  const selectable = visible.filter(task => rootIds.has(task.id) || (task.parent_id !== null && rootIds.has(task.parent_id)))
  return { sections, visible, hasAny: visible.length > 0, selectable }
}
