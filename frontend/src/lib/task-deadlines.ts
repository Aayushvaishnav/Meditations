import type { TaskDeadline } from "@/api/types"
import { formatDue, parseUTC } from "./date-values"

function calendarDayNumber(label: string): number {
  const [year, month, day] = label.split("-").map(Number)
  const date = new Date(0)
  date.setUTCFullYear(year, month - 1, day)
  return date.getTime() / 86_400_000
}

export function calendarDayDistance(from: string, to: string): number {
  return calendarDayNumber(to) - calendarDayNumber(from)
}

export function localDayParam(date: Date): string {
  return `${String(date.getFullYear()).padStart(4, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}

function calendarDate(label: string, dayOffset = 0): Date {
  const [year, month, day] = label.split("-").map(Number)
  const date = new Date(0)
  date.setFullYear(year, month - 1, day + dayOffset)
  date.setHours(0, 0, 0, 0)
  return date
}

export function deadlineCalendarDate(deadline: TaskDeadline): Date | null {
  if (deadline.kind === "none") return null
  if (deadline.kind === "timed") return parseUTC(deadline.at)
  return calendarDate(deadline.date)
}

export function deadlineDayKey(deadline: TaskDeadline): string | null {
  if (deadline.kind === "date") return deadline.date
  const date = deadlineCalendarDate(deadline)
  return date === null ? null : localDayParam(date)
}

export function deadlineCutoff(deadline: TaskDeadline): number | null {
  if (deadline.kind === "date") return calendarDate(deadline.date, 1).getTime() - 1
  return deadlineCalendarDate(deadline)?.getTime() ?? null
}

export function formatDeadline(deadline: TaskDeadline): string {
  if (deadline.kind === "none") return ""
  if (deadline.kind === "timed") {
    const date = parseUTC(deadline.at)
    return date === null ? "" : formatDue(date)
  }
  const now = new Date()
  const diff = calendarDayDistance(localDayParam(now), deadline.date)
  if (diff === 0) return "Today"
  if (diff === 1) return "Tomorrow"
  if (diff === -1) return "Yesterday"
  // UTC is a formatting frame; locally skipped dates retain their label
  const date = new Date(`${deadline.date}T00:00:00Z`)
  return date.toLocaleDateString(undefined, {
    timeZone: "UTC",
    weekday: diff > 1 && diff < 7 ? "short" : undefined,
    month: "short", day: "numeric",
    year: date.getUTCFullYear() === now.getFullYear() ? undefined : "numeric",
  })
}

export function moveDeadline(deadline: TaskDeadline, target: Date): TaskDeadline {
  if (deadline.kind === "none") return { kind: "none" }
  if (deadline.kind === "date") return { kind: "date", date: localDayParam(target) }
  const date = deadlineCalendarDate(deadline)!
  // Date setters resolve DST gaps forward and overlaps to the earlier instant.
  date.setFullYear(target.getFullYear(), target.getMonth(), target.getDate())
  return { kind: "timed", at: date.toISOString() }
}

export function deadlineFromLegacy(due_date: string | null): TaskDeadline {
  return due_date === null ? { kind: "none" } : { kind: "timed", at: due_date }
}
