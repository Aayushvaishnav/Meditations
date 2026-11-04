import type { Task, TimeBlock } from "@/api/types"
import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import type { InboundOverlayItem } from "@/api/calendar-inbound-types"
import { deadlineCalendarDate, deadlineDayKey, localDayParam } from "./task-deadlines"
import { blockOnDay } from "./time-blocks"
import { importedEventOnDay } from "./calendar-overlay"
import { parseUTC } from "./date-values"
import { sortTasks } from "./dates"

type Placement = { id: string; allDay: boolean; timing: { kind: "all-day" } | { kind: "timed"; clock: string }; placement: "placed" }
export type CalendarItem = Placement & (
  | { kind: "deadline"; task: Task; editable: true }
  | { kind: "block"; block: TimeBlock; task: Task; editable: true }
  | { kind: "imported"; event: ImportedOverlayItem; editable: false }
  | { kind: "live"; event: InboundOverlayItem; editable: false }
)
export type CalendarDay = { day: Date; items: CalendarItem[] }

function clock(date: Date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`
}

// Unplaced source records stay in overlay disclosures; never invent a placement
export function projectCalendar(days: Date[], tasks: Task[], blocks: TimeBlock[], imported: ImportedOverlayItem[], live: InboundOverlayItem[]): CalendarDay[] {
  const taskById = new Map(tasks.map(task => [task.id, task]))
  const sortedTasks = [...tasks].sort(sortTasks)
  return days.map(day => {
    const items: CalendarItem[] = []
    const key = localDayParam(day)
    for (const task of sortedTasks) {
      if (deadlineDayKey(task.deadline) !== key) continue
      items.push({ kind: "deadline", id: `deadline:${task.id}`, task, editable: true, allDay: task.deadline.kind === "date", timing: task.deadline.kind === "timed" ? { kind: "timed", clock: clock(deadlineCalendarDate(task.deadline)!) } : { kind: "all-day" }, placement: "placed" })
    }
    for (const block of blocks) {
      const task = taskById.get(block.task_id)
      if (!task || !blockOnDay(block, day)) continue
      items.push({ kind: "block", id: `block:${block.id}`, task, block, editable: true, allDay: block.kind === "all_day", timing: block.kind === "timed" ? { kind: "timed", clock: clock(parseUTC(block.start_at)!) } : { kind: "all-day" }, placement: "placed" })
    }
    for (const event of imported) {
      if (importedEventOnDay(event, day)) items.push({ kind: "imported", id: `imported:${event.source_id}:${event.id}`, event, editable: false, allDay: event.interval.kind === "date", timing: event.interval.kind === "date" ? { kind: "all-day" } : { kind: "timed", clock: event.interval.kind === "floating" ? event.interval.start.slice(11, 19) : clock(new Date(event.interval.start)) }, placement: "placed" })
    }
    for (const event of live) {
      if (importedEventOnDay(event, day)) items.push({ kind: "live", id: `live:${event.connection_id}:${event.id}`, event, editable: false, allDay: event.interval.kind === "date", timing: event.interval.kind === "date" ? { kind: "all-day" } : { kind: "timed", clock: event.interval.kind === "floating" ? event.interval.start.slice(11, 19) : clock(new Date(event.interval.start)) }, placement: "placed" })
    }
    items.sort((a, b) => Number(b.allDay) - Number(a.allDay) || (a.timing.kind === "timed" && b.timing.kind === "timed" ? a.timing.clock.localeCompare(b.timing.clock) : 0) || a.kind.localeCompare(b.kind) || a.id.localeCompare(b.id))
    return { day, items }
  })
}

export function calendarDaySummary({ items }: CalendarDay): string {
  const count = (kind: CalendarDay["items"][number]["kind"]) => items.filter(item => item.kind === kind).length
  return `${items.length} items: ${count("deadline")} task deadlines, ${count("block")} work blocks, ${count("imported")} imported events, ${count("live")} live events`
}
