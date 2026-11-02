import type { QueryClient } from "@tanstack/react-query"
import type { Task } from "@/api/types"

export const tasksKey = ["tasks"] as const
type Change = (tasks: Task[]) => Task[]
export interface TaskChange {
  apply: Change
  status: "pending" | "success" | "error"
}
interface Batch {
  snapshot: Task[]
  changes: TaskChange[]
}
const batches = new WeakMap<QueryClient, Batch>()

function replay(batch: Batch) {
  return batch.changes.reduce((tasks, change) => change.status === "error" ? tasks : change.apply(tasks), batch.snapshot)
}

export async function beginTaskChange(client: QueryClient, apply: Change): Promise<TaskChange> {
  await client.cancelQueries({ queryKey: tasksKey })
  let batch = batches.get(client)
  if (!batch) {
    batch = { snapshot: client.getQueryData<Task[]>(tasksKey) ?? [], changes: [] }
    batches.set(client, batch)
  }
  const change: TaskChange = { apply, status: "pending" }
  batch.changes.push(change)
  client.setQueryData(tasksKey, replay(batch))
  return change
}

export function rollbackTaskChange(client: QueryClient, change: TaskChange) {
  change.status = "error"
  const batch = batches.get(client)
  if (batch) client.setQueryData(tasksKey, replay(batch))
}

export function settleTaskChange(client: QueryClient, change: TaskChange | undefined, confirmed?: Change) {
  const batch = batches.get(client)
  if (change && batch) {
    if (change.status === "pending") change.status = "success"
    if (confirmed) change.apply = confirmed
    client.setQueryData(tasksKey, replay(batch))
    if (batch.changes.every(item => item.status !== "pending")) batches.delete(client)
  }
  return invalidateTasks(client)
}

export function invalidateTasks(client: QueryClient) {
  return client.invalidateQueries({ queryKey: tasksKey, refetchType: batches.has(client) ? "none" : "active" })
}

// Refetches from remount, focus, or reconnect must retain in-flight edits;
// refresh the base so rollback also preserves unrelated server changes.
export function reconcileTasks(client: QueryClient, tasks: Task[]) {
  const batch = batches.get(client)
  if (!batch) return tasks
  batch.snapshot = tasks
  return replay(batch)
}

export function withoutTaskTree(tasks: Task[], id: string) {
  const children = new Map<string, string[]>()
  for (const task of tasks) {
    if (task.parent_id !== null) {
      const siblings = children.get(task.parent_id) ?? []
      siblings.push(task.id)
      children.set(task.parent_id, siblings)
    }
  }
  const removed = new Set<string>()
  const pending = [id]
  while (pending.length) {
    const next = pending.pop()!
    if (removed.has(next)) continue
    removed.add(next)
    pending.push(...(children.get(next) ?? []))
  }
  return tasks.filter(task => !removed.has(task.id))
}
