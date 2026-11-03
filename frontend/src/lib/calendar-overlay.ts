import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import { localDayParam } from "./task-deadlines"

export function importedEventOnDay(event: ImportedOverlayItem, day: Date): boolean {
  const { kind, start, end } = event.interval
  const label = localDayParam(day)
  if (kind === "date") return start <= label && label < end
  if (kind === "floating") {
    const next = new Date(`${label}T00:00:00Z`)
    next.setUTCDate(next.getUTCDate() + 1)
    const lower = `${label}T00:00:00`
    const upper = `${next.toISOString().slice(0, 10)}T00:00:00`
    return start === end ? start.slice(0, 10) === label : start < upper && end > lower
  }
  const lower = new Date(day)
  lower.setHours(0, 0, 0, 0)
  const upper = new Date(lower)
  upper.setDate(upper.getDate() + 1)
  const from = new Date(start).getTime()
  const to = new Date(end).getTime()
  return from === to
    ? from >= lower.getTime() && from < upper.getTime()
    : from < upper.getTime() && to > lower.getTime()
}

export function importedEventLabel(event: ImportedOverlayItem): string {
  const { kind, start, end } = event.interval
  if (kind === "date") return `All day: ${start} to ${end} (end exclusive)`
  if (kind === "floating") return `${start.replace("T", " ")} to ${end.replace("T", " ")} (floating local time)`
  return `${new Date(start).toLocaleString()} to ${new Date(end).toLocaleString()} (your local time)`
}
