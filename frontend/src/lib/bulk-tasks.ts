import type { Task, TaskStatus } from "@/api/types"

export type BulkTaskAction =
  | { kind: "list"; listId: string | null; label: string }
  | { kind: "status"; status: TaskStatus }
  | { kind: "add-tag" | "remove-tag"; tag: string }

export function selectableTasks(tasks: Task[]): Task[] {
  return tasks.filter(task => !task.id.startsWith("temp-"))
}

export function bulkTaskPatch(task: Task, action: BulkTaskAction): Partial<Task> {
  switch (action.kind) {
    case "list": return { list_id: action.listId }
    case "status": return { status: action.status }
    case "add-tag": return { tags: [...new Set([...task.tags, action.tag])] }
    case "remove-tag": return { tags: task.tags.filter(tag => tag !== action.tag) }
  }
}

export function describeBulkAction(action: BulkTaskAction): string {
  switch (action.kind) {
    case "list": return `Assign list: ${action.label}`
    case "status": return `Set status: ${action.status.replaceAll("_", " ")}`
    case "add-tag": return `Add tag: ${action.tag}`
    case "remove-tag": return `Remove tag: ${action.tag}`
  }
}
