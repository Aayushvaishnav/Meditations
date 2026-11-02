import type { Task } from "@/api/types"
import { calendarDayDistance, deadlineCalendarDate, deadlineDayKey, localDayParam } from "./task-deadlines"
export * from "./date-values"

export type TaskGroup = "overdue" | "today" | "tomorrow" | "upcoming" | "nodate" | "completed"

export function groupOf(task: Task, now: Date = new Date()): TaskGroup {
  if (task.status === "completed") return "completed"
  const day = deadlineDayKey(task.deadline)
  if (day === null) return "nodate"
  const diff = calendarDayDistance(localDayParam(now), day)
  if (diff < 0) return "overdue"
  if (diff === 0) return "today"
  if (diff === 1) return "tomorrow"
  return "upcoming"
}

export const GROUP_ORDER: TaskGroup[] = ["overdue", "today", "tomorrow", "upcoming", "nodate", "completed"]

export const GROUP_LABELS: Record<TaskGroup, string> = {
  overdue: "Overdue",
  today: "Today",
  tomorrow: "Tomorrow",
  upcoming: "Upcoming",
  nodate: "No date",
  completed: "Completed",
}

/** Sort by local day, date-only before timed, then manual order and creation. */
export function sortTasks(a: Task, b: Task): number {
  const aDay = deadlineDayKey(a.deadline)
  const bDay = deadlineDayKey(b.deadline)
  if (aDay !== bDay) {
    if (aDay === null) return 1
    if (bDay === null) return -1
    return calendarDayDistance(bDay, aDay)
  }
  if (a.deadline.kind !== b.deadline.kind) return a.deadline.kind === "date" ? -1 : 1
  if (a.deadline.kind === "timed" && b.deadline.kind === "timed") {
    const diff = deadlineCalendarDate(a.deadline)!.getTime() - deadlineCalendarDate(b.deadline)!.getTime()
    if (diff !== 0) return diff
  }
  if (a.order_index !== b.order_index) return a.order_index - b.order_index
  return a.created_at.localeCompare(b.created_at)
}
